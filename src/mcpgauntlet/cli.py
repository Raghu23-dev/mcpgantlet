"""Command-line interface.

WHY THIS EXISTS: the README and a disclosure sent to a third-party maintainer both told readers to
`pipx install` this package and run `mcpgauntlet audit <url>`. Neither worked — there was no entry
point and no CLI module, so the install produced a library and no command. The instruction was
written before the thing it described.

Deliberately argparse rather than typer or click: a conformance checker someone installs to audit
their own server should not drag a CLI framework into their environment. The only runtime dependency
is httpx, which the auditing genuinely needs.
"""

from __future__ import annotations

import argparse
import json
import sys
from urllib.parse import urlparse

from .conformance import Auditor, Verdict, summarise
from .spec import PROTOCOL_VERSION, RULES, classify

MARK = {
    Verdict.PASS: "pass ",
    Verdict.FAIL: "FAIL ",
    Verdict.INCONCLUSIVE: "?    ",
    Verdict.SKIPPED: "-    ",
}

#: Auditing a host you do not control is someone else's traffic. Read-only probes are still
#: unsolicited requests, so anything that is not local requires an explicit acknowledgement — the
#: same rule `docs/NON-GOALS.md` states for load testing.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


def _is_local(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in LOCAL_HOSTS


def _audit(args: argparse.Namespace) -> int:
    if not _is_local(args.url) and not args.i_have_permission:
        print(
            f"Refusing to probe {args.url}: it is not a local host.\n\n"
            "Every probe here is read-only, but they are still unsolicited requests to someone\n"
            "else's server. Pass --i-have-permission to confirm you operate it or have consent.\n",
            file=sys.stderr,
        )
        return 2

    with Auditor(args.url, timeout=args.timeout) as auditor:
        revision = auditor.detect_revision()
        # A server on an older revision refuses a 2026-07-28-shaped request outright, so the
        # Origin probe would report INCONCLUSIVE with nothing learned. Give it a request the
        # server actually accepts, so the only variable is the header being tested.
        baseline = None
        if revision.responds_to_initialize:
            baseline = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": revision.declared or "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "mcpgauntlet", "version": "0.1.0"},
                },
            }
        findings = auditor.run(baseline_body=baseline)

    gap = not revision.matches_audited_spec
    violations = [f for f in findings if f.is_violation]
    defects = [f for f in violations if classify(f.rule.id, version_gap=gap) == "defect"]
    gaps = [f for f in violations if classify(f.rule.id, version_gap=gap) == "version-gap"]

    if args.json:
        print(
            json.dumps(
                {
                    "target": args.url,
                    "audited_against": PROTOCOL_VERSION,
                    "declared_revision": revision.declared,
                    "version_gap": gap,
                    "counts": summarise(findings),
                    "defects": [
                        {
                            "rule": f.rule.id,
                            "severity": str(f.rule.severity),
                            "clause": f.rule.clause,
                            "observed": f.observed,
                            "detail": f.detail,
                        }
                        for f in defects
                    ],
                    "version_gaps": [{"rule": f.rule.id, "observed": f.observed} for f in gaps],
                },
                indent=2,
            )
        )
        return 1 if defects else 0

    print(f"{args.url}\naudited against spec {PROTOCOL_VERSION}")
    print(f"server declares: {revision.declared or 'nothing'} — {revision.detail}")
    if gap:
        print(
            f"\nVERSION GAP: this server targets {revision.declared or 'an unknown revision'}.\n"
            "Findings below are split: a version gap is not a defect."
        )
    print("-" * 78)

    for f in findings:
        tag = ""
        if f.is_violation:
            tag = "  << DEFECT" if f in defects else "  (version gap)"
        sev = "MUST " if str(f.rule.severity) == "MUST" else "SHOULD"
        print(f"  {MARK[f.verdict]}{sev} {f.rule.id:<26} {f.observed}{tag}")
        if f in defects and f.detail:
            print(f"        → {f.detail}")
            print(f"        → clause: {f.rule.clause}")

    counts = summarise(findings)
    print(
        f"\n  {counts['pass']} pass · {counts['fail']} fail · {counts['inconclusive']} inconclusive"
    )
    print(f"  → {len(defects)} defect(s), {len(gaps)} version gap(s)")

    # Exit 1 only for real defects. A version gap is information, not a failure — exiting non-zero
    # for it would make this useless in CI against the servers that actually exist today, since
    # none of them implements the current revision.
    return 1 if defects else 0


def _rules(args: argparse.Namespace) -> int:
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": r.id,
                        "severity": str(r.severity),
                        "clause": r.clause,
                        "description": r.description,
                        "rationale": r.rationale,
                        "classification": classify(r.id, version_gap=True),
                    }
                    for r in RULES
                ],
                indent=2,
            )
        )
        return 0
    print(f"{len(RULES)} rules for spec {PROTOCOL_VERSION}\n")
    for r in RULES:
        kind = classify(r.id, version_gap=True)
        print(f"{r.id}  [{r.severity}]  ({kind})")
        print(f"  {r.description}")
        print(f"  clause: {r.clause}")
        print(f"  why:    {r.rationale}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mcpgauntlet",
        description=f"Conformance checker for MCP Streamable HTTP, revision {PROTOCOL_VERSION}.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit", help="audit one MCP endpoint")
    audit.add_argument("url", help="the MCP endpoint, e.g. http://localhost:8000/mcp")
    audit.add_argument("--json", action="store_true", help="machine-readable output")
    audit.add_argument("--timeout", type=float, default=15.0, help="per-request timeout, seconds")
    audit.add_argument(
        "--i-have-permission",
        action="store_true",
        help="confirm you operate the target, or have the operator's consent",
    )
    audit.set_defaults(func=_audit)

    rules = sub.add_parser("rules", help="list the rules, each with its spec clause")
    rules.add_argument("--json", action="store_true", help="machine-readable output")
    rules.set_defaults(func=_rules)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
