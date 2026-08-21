"""Tests for the deployed reference server.

The claim is criterion 3: **zero findings against a server built strictly to spec**. A
conformance checker that flags a correct server is worse than no checker, because the first
false positive teaches its user to ignore every later report.

These run the probes against the deployed app rather than the bare fixture, because the
deployment sits behind a forwarding layer — and that layer already broke conformance once by
turning a bodiless 202 into `null`.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT / "api"))

from index import app

from mcpgauntlet.conformance import Auditor
from mcpgauntlet.spec import PROTOCOL_VERSION, RULES

client = TestClient(app)

PORT = 8947


@pytest.fixture(scope="module")
def live_url() -> Iterator[str]:
    """A real server on a real socket.

    The self-audit must traverse actual HTTP: an in-process transport would not exercise the
    forwarding layer, and the forwarding layer is where the one real conformance bug was.
    """
    config = uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        time.sleep(0.05)
        if server.started:
            break
    else:
        pytest.fail("server did not start")

    yield f"http://127.0.0.1:{PORT}"

    server.should_exit = True
    thread.join(timeout=5)


class TestCriterion3:
    def test_the_deployed_server_has_zero_violations(self, live_url: str) -> None:
        with Auditor(f"{live_url}/mcp") as auditor:
            findings = auditor.run()

        violations = [f for f in findings if f.is_violation]
        assert len(findings) == 10
        assert violations == [], [f"{f.rule.id}: {f.observed}" for f in violations]

    def test_no_probe_is_inconclusive(self, live_url: str) -> None:
        """Inconclusive against a known-good target means the probe cannot decide, which is a
        defect in the probe rather than a property of the server."""
        with Auditor(f"{live_url}/mcp") as auditor:
            findings = auditor.run()
        assert [f.rule.id for f in findings if f.verdict == "inconclusive"] == []

    def test_the_self_audit_endpoint_agrees(self, live_url: str) -> None:
        d = httpx.get(f"{live_url}/audit/self", timeout=90).json()
        assert d["violations"] == 0
        assert d["probes_run"] == 10
        assert "CONFORMANT" in d["verdict"]


class TestForwardingDoesNotAlterResponses:
    """The forwarding layer must be transparent, or the audited server is not the written one."""

    def test_a_notification_gets_202_with_no_body(self) -> None:
        """The bug this catches: wrapping everything in JSONResponse turned a bodiless 202 into
        the four bytes 'null', and the self-audit failed notification-202 on its first run."""
        r = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
                "mcp-protocol-version": PROTOCOL_VERSION,
                "mcp-method": "notifications/initialized",
            },
        )
        assert r.status_code == 202
        assert r.content == b"", f"expected an empty body, got {r.content!r}"

    def test_get_is_405(self) -> None:
        assert client.get("/mcp").status_code == 405

    def test_delete_is_405(self) -> None:
        assert client.delete("/mcp").status_code == 405

    def test_missing_version_header_is_rejected(self) -> None:
        r = client.post("/mcp", json={})
        assert r.status_code == 400
        assert r.json()["error"]["code"] == -32020

    def test_a_valid_request_succeeds(self) -> None:
        r = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
                "mcp-protocol-version": PROTOCOL_VERSION,
                "mcp-method": "tools/list",
            },
        )
        assert r.status_code == 200
        assert r.json()["result"] == {"tools": []}


class TestNoHostedAuditor:
    """`docs/NON-GOALS.md` ruled out a hosted service before any code existed.

    Asserted as a test so the commitment cannot be quietly reversed: an auditor accepting a URL
    from an anonymous visitor is a request-forgery gadget aimed at whatever a stranger types.
    """

    def test_no_endpoint_accepts_an_arbitrary_target(self) -> None:
        # `getattr` rather than `r.path` behind a stale `type: ignore[attr-defined]`: the
        # hasattr guard already proves the attribute is there, and the suppression had
        # become unused, which fails strict mode.
        paths = [getattr(r, "path", None) for r in app.routes]
        assert "/audit" not in paths
        for candidate in ("/audit?url=", "/audit?target="):
            assert client.get(f"{candidate}http://example.com/mcp").status_code in (404, 422)

    def test_self_audit_targets_only_this_instance(self) -> None:
        """It derives the target from the request's own base URL, never from a parameter."""
        source = (_ROOT / "api" / "index.py").read_text()
        assert "request.base_url" in source
        assert "def audit_self" in source


class TestSpecEndpoint:
    def test_every_rule_cites_a_clause(self) -> None:
        """Criterion 1. A probe that cannot cite a clause is an opinion."""
        d = client.get("/spec/rules").json()
        assert d["count"] == len(RULES)
        for rule in d["rules"]:
            assert rule["clause"].strip(), f"{rule['id']} cites no clause"
            assert rule["rationale"].strip()

    def test_health_reports_the_protocol_version(self) -> None:
        d = client.get("/health").json()
        assert d["protocol_version"] == PROTOCOL_VERSION
        assert d["must_rules"] == sum(1 for r in RULES if r.severity == "MUST")
