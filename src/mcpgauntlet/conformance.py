"""Conformance probes against a live MCP endpoint.

Each probe sends a real request and judges the real response against one rule from
`spec.py`. No probe infers a verdict from another probe's result — a server that fails
one rule may pass the next, and reporting otherwise would overstate the finding.

Probes report INCONCLUSIVE rather than guessing when a response is ambiguous. A
conformance tool that turns uncertainty into a failure is the same category of error as
one that turns it into a pass: both replace a measurement with an opinion.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

from .spec import PROTOCOL_VERSION, RULES_BY_ID, Rule, Severity


class Verdict(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INCONCLUSIVE = "inconclusive"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class Finding:
    rule: Rule
    verdict: Verdict
    observed: str
    detail: str = ""

    @property
    def is_violation(self) -> bool:
        return self.verdict is Verdict.FAIL


def _rpc(method: str, params: dict[str, Any] | None = None, rid: int | None = 1) -> dict[str, Any]:
    body: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if rid is not None:
        body["id"] = rid
    body["params"] = {
        **(params or {}),
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
            "io.modelcontextprotocol/clientInfo": {"name": "mcpgauntlet", "version": "0.1.0"},
            "io.modelcontextprotocol/clientCapabilities": {},
        },
    }
    return body


def _headers(
    method: str, name: str | None = None, version: str | None = PROTOCOL_VERSION
) -> dict[str, str]:
    h = {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "mcp-method": method,
    }
    if version is not None:
        h["mcp-protocol-version"] = version
    if name is not None:
        h["mcp-name"] = name
    return h


def _json_error_code(response: httpx.Response) -> int | None:
    try:
        body = response.json()
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(body, dict):
        return None
    err = body.get("error")
    return err.get("code") if isinstance(err, dict) else None


class Auditor:
    """Runs every probe against one endpoint."""

    def __init__(self, url: str, timeout: float = 15.0) -> None:
        self.url = url
        self._client = httpx.Client(timeout=timeout, follow_redirects=False)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Auditor:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def run(self) -> list[Finding]:
        return [
            self.probe_origin(),
            self.probe_get(),
            self.probe_delete(),
            self.probe_missing_version_header(),
            self.probe_header_body_mismatch(),
            self.probe_unknown_method(),
            self.probe_initialize(),
            self.probe_notification(),
            self.probe_content_type(),
            self.probe_session_id_echo(),
        ]

    # ── MUST rules ──────────────────────────────────────────────────────────

    def probe_origin(self) -> Finding:
        rule = RULES_BY_ID["origin-403"]
        try:
            r = self._client.post(
                self.url,
                headers={**_headers("tools/list"), "origin": "https://attacker.example"},
                json=_rpc("tools/list"),
            )
        except httpx.HTTPError as exc:
            return Finding(rule, Verdict.INCONCLUSIVE, "transport error", str(exc))

        if r.status_code == 403:
            return Finding(rule, Verdict.PASS, "403")
        return Finding(
            rule,
            Verdict.FAIL,
            f"{r.status_code}",
            "A foreign Origin was not rejected. A remote page can drive this endpoint "
            "via DNS rebinding.",
        )

    def probe_get(self) -> Finding:
        rule = RULES_BY_ID["get-405"]
        try:
            r = self._client.get(self.url)
        except httpx.HTTPError as exc:
            return Finding(rule, Verdict.INCONCLUSIVE, "transport error", str(exc))
        if r.status_code == 405:
            return Finding(rule, Verdict.PASS, "405")
        return Finding(
            rule,
            Verdict.FAIL,
            f"{r.status_code}",
            "GET answered with content. A client may read this as an older revision and "
            "negotiate down.",
        )

    def probe_delete(self) -> Finding:
        rule = RULES_BY_ID["delete-405"]
        try:
            r = self._client.request("DELETE", self.url)
        except httpx.HTTPError as exc:
            return Finding(rule, Verdict.INCONCLUSIVE, "transport error", str(exc))
        if r.status_code == 405:
            return Finding(rule, Verdict.PASS, "405")
        return Finding(rule, Verdict.FAIL, f"{r.status_code}", "DELETE was not rejected.")

    def probe_missing_version_header(self) -> Finding:
        rule = RULES_BY_ID["protocol-version-header"]
        try:
            r = self._client.post(
                self.url,
                headers=_headers("tools/list", version=None),
                json=_rpc("tools/list"),
            )
        except httpx.HTTPError as exc:
            return Finding(rule, Verdict.INCONCLUSIVE, "transport error", str(exc))
        if r.status_code == 400:
            return Finding(rule, Verdict.PASS, "400")
        return Finding(
            rule,
            Verdict.FAIL,
            f"{r.status_code}",
            "A request without MCP-Protocol-Version was accepted, so the server cannot "
            "know which protocol era its caller speaks.",
        )

    def probe_header_body_mismatch(self) -> Finding:
        rule = RULES_BY_ID["header-body-match"]
        body = _rpc("tools/call", {"name": "real_tool_name"})
        try:
            r = self._client.post(
                self.url,
                headers=_headers("tools/call", name="different_name"),
                json=body,
            )
        except httpx.HTTPError as exc:
            return Finding(rule, Verdict.INCONCLUSIVE, "transport error", str(exc))

        code = _json_error_code(r)
        if r.status_code == 400 and code == -32020:
            return Finding(rule, Verdict.PASS, "400 / -32020")
        if r.status_code == 400:
            return Finding(
                rule,
                Verdict.FAIL,
                f"400 / code={code}",
                "Rejected, but not with -32020 (HeaderMismatch), so a client cannot "
                "distinguish this from other 400s.",
            )
        return Finding(
            rule,
            Verdict.FAIL,
            f"{r.status_code}",
            "Mcp-Name contradicted params.name and was not rejected. An intermediary "
            "routing on the header would disagree with what the server executes.",
        )

    def probe_unknown_method(self) -> Finding:
        rule = RULES_BY_ID["unknown-method-404"]
        try:
            r = self._client.post(
                self.url,
                headers=_headers("does/not/exist"),
                json=_rpc("does/not/exist"),
            )
        except httpx.HTTPError as exc:
            return Finding(rule, Verdict.INCONCLUSIVE, "transport error", str(exc))
        code = _json_error_code(r)
        if r.status_code == 404 and code == -32601:
            return Finding(rule, Verdict.PASS, "404 / -32601")
        return Finding(
            rule,
            Verdict.FAIL,
            f"{r.status_code} / code={code}",
            "An unknown method must return 404 with -32601 so a client can tell a modern "
            "server from a legacy 404.",
        )

    def probe_initialize(self) -> Finding:
        rule = RULES_BY_ID["no-initialize"]
        try:
            r = self._client.post(
                self.url,
                headers=_headers("initialize"),
                json=_rpc("initialize"),
            )
        except httpx.HTTPError as exc:
            return Finding(rule, Verdict.INCONCLUSIVE, "transport error", str(exc))

        if r.status_code == 404:
            return Finding(rule, Verdict.PASS, "404 — initialize not implemented")

        try:
            body = r.json()
        except (json.JSONDecodeError, ValueError):
            return Finding(rule, Verdict.INCONCLUSIVE, f"{r.status_code}", "non-JSON response")

        result = body.get("result") if isinstance(body, dict) else None
        if isinstance(result, dict) and "protocolVersion" in result:
            claimed = result["protocolVersion"]
            return Finding(
                rule,
                Verdict.FAIL,
                f"200, claims {claimed}",
                f"The server answers the removed initialize handshake while advertising "
                f"{claimed}. If that version is {PROTOCOL_VERSION} it is advertising a "
                "revision it does not implement.",
            )
        return Finding(rule, Verdict.PASS, f"{r.status_code} — no initialize result")

    def probe_notification(self) -> Finding:
        rule = RULES_BY_ID["notification-202"]
        try:
            r = self._client.post(
                self.url,
                headers=_headers("notifications/progress"),
                json=_rpc("notifications/progress", rid=None),
            )
        except httpx.HTTPError as exc:
            return Finding(rule, Verdict.INCONCLUSIVE, "transport error", str(exc))
        if r.status_code == 202 and not r.content:
            return Finding(rule, Verdict.PASS, "202, empty body")
        if r.status_code == 202:
            return Finding(
                rule,
                Verdict.FAIL,
                "202 with a body",
                "A notification has no id, so a body has nowhere to go.",
            )
        if 400 <= r.status_code < 500:
            return Finding(
                rule, Verdict.PASS, f"{r.status_code} — notification declined, which is permitted"
            )
        return Finding(rule, Verdict.FAIL, f"{r.status_code}", "Expected 202 or a 4xx.")

    # ── SHOULD rules ────────────────────────────────────────────────────────

    def probe_content_type(self) -> Finding:
        rule = RULES_BY_ID["accept-both"]
        try:
            r = self._client.post(self.url, headers=_headers("tools/list"), json=_rpc("tools/list"))
        except httpx.HTTPError as exc:
            return Finding(rule, Verdict.INCONCLUSIVE, "transport error", str(exc))
        ct = r.headers.get("content-type", "")
        if "application/json" in ct or "text/event-stream" in ct:
            return Finding(rule, Verdict.PASS, ct.split(";")[0])
        return Finding(
            rule,
            Verdict.FAIL,
            ct or "(none)",
            "A conforming client cannot parse this content type.",
        )

    def probe_session_id_echo(self) -> Finding:
        rule = RULES_BY_ID["session-id-ignored"]
        try:
            r = self._client.post(
                self.url,
                headers={**_headers("tools/list"), "mcp-session-id": "probe-value"},
                json=_rpc("tools/list"),
            )
        except httpx.HTTPError as exc:
            return Finding(rule, Verdict.INCONCLUSIVE, "transport error", str(exc))
        echoed = r.headers.get("mcp-session-id")
        if echoed is None:
            return Finding(rule, Verdict.PASS, "not echoed")
        return Finding(
            rule,
            Verdict.FAIL,
            f"echoed {echoed!r}",
            "Echoing a session id tells the client sessions work, and it will then depend "
            "on state the server does not keep.",
        )


def summarise(findings: list[Finding]) -> dict[str, int]:
    counts = {v.value: 0 for v in Verdict}
    for f in findings:
        counts[f.verdict.value] += 1
    counts["must_violations"] = sum(
        1 for f in findings if f.is_violation and f.rule.severity is Severity.MUST
    )
    return counts
