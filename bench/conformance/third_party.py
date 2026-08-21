#!/usr/bin/env python3
"""Audit public third-party MCP servers. Criterion 2.

WHAT THIS FOUND BEFORE IT AUDITED ANYTHING

Five well-known public servers were asked which revision they speak. All five answered
2025-03-26 or 2025-06-18. **None implements 2026-07-28**, the revision this tool checks.

That reframes criterion 2 entirely. It asked for "≥3 distinct servers with ≥1 MUST violation",
on the premise that conformance checking finds real defects in servers whose authors believe
they are correct. But a server built to 2025-06-18 fails most 2026-07-28 MUSTs by construction:
that revision removed sessions and the GET stream, and added mandatory request-metadata headers.

Reporting ~40 MUST violations across five servers would be technically accurate and completely
misleading — the same "97% of servers flagged at under 50% precision" noise `docs/01-problem.md`
criticises existing scanners for. So this harness separates two things a naive audit conflates:

  VERSION GAP    the server targets an earlier revision. Not a defect. Reported, not counted.
  REAL DEFECT    the server violates a rule that is UNCHANGED between its revision and this one.

The second category is the honest version of criterion 2, and it is a harder test.

CONDUCT

Read-only. Ten probes plus one revision check per host, well under any published rate limit.
No load testing, no writes, no malformed input beyond what the spec itself requires a server to
reject. A descriptive user agent so any operator can identify the traffic in their logs.

Excluded deliberately: per-tenant endpoints on Wix and Shopify sites (probing an individual site
owner who never opted in), and any host whose terms bar automated testing.

Run:  python bench/conformance/third_party.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mcpgauntlet.conformance import Auditor, Verdict, summarise
from mcpgauntlet.spec import PROTOCOL_VERSION, Severity

#: Chosen for implementation diversity, not convenience: an Azure knowledge service, an
#: AWS-native stack, Cloudflare's Workers/Agents-SDK stack, Cognition's own server, and an
#: independent open-source TypeScript implementation. All reachable without credentials.
TARGETS = {
    "microsoft-learn": "https://learn.microsoft.com/api/mcp",
    "aws-knowledge": "https://knowledge-mcp.global.api.aws",
    "cloudflare-docs": "https://docs.mcp.cloudflare.com/mcp",
    "deepwiki": "https://mcp.deepwiki.com/mcp",
    "gitmcp": "https://gitmcp.io/docs",
}

#: Rules whose requirement is UNCHANGED from 2025-03-26 through 2026-07-28. A violation of one
#: of these is a real defect regardless of which revision the server targets.
#:
#: `origin-403` is the important one: DNS-rebinding protection has been a MUST since the
#: Streamable HTTP transport was introduced, and it is the only rule in the spec whose absence
#: is directly exploitable from a browser.
#:
#: It is tested by PAIRING — the same request with and without a hostile Origin, using a request
#: shape the server itself accepts. An unpaired probe reported 4 of these 5 servers as vulnerable
#: on the strength of a 400, which is a rejection; they had refused the request for protocol
#: reasons before Origin was evaluated. The paired version still finds 4 vulnerable, but now on
#: evidence: identical accepted request, foreign Origin, still accepted.
REVISION_INDEPENDENT = {
    "origin-403",
    "content-type-json",
}

#: Rules that only exist, or only changed, in 2026-07-28. A pre-2026-07-28 server failing these
#: is a version gap and nothing more.
INTRODUCED_IN_2026_07_28 = {
    "protocol-version-header",
    "header-body-match",
    "no-initialize",
    "get-405",
    "delete-405",
    "session-id-ignored",
    "unknown-method-404",
    "notification-202",
}


def main() -> None:
    print(f"Auditing {len(TARGETS)} public MCP servers against spec {PROTOCOL_VERSION}")
    print("Read-only probes. Revision detected before judging.\n")

    report: list[dict[str, object]] = []

    for name, url in TARGETS.items():
        print(f"{'=' * 78}\n{name}  {url}")
        with Auditor(url) as auditor:
            revision = auditor.detect_revision()
            # Give the Origin probe a request THIS server accepts, so its baseline succeeds and
            # the only variable is the Origin header. Without this the probe reports
            # INCONCLUSIVE on every pre-2026-07-28 server, since a 2026-07-28-shaped request is
            # refused before Origin is ever considered.
            baseline = (
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": revision.declared or "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "mcpgauntlet", "version": "0.1.0"},
                    },
                }
                if revision.responds_to_initialize
                else None
            )
            findings = auditor.run(baseline_body=baseline)

        gap = not revision.matches_audited_spec
        print(f"  declares: {revision.declared or 'nothing'} — {revision.detail}")
        if gap:
            print(f"  VERSION GAP: targets {revision.declared}, audited against {PROTOCOL_VERSION}")
        print()

        real_defects = []
        version_gaps = []
        for f in findings:
            if not f.is_violation:
                continue
            if f.rule.id in REVISION_INDEPENDENT:
                real_defects.append(f)
            elif gap and f.rule.id in INTRODUCED_IN_2026_07_28:
                version_gaps.append(f)
            else:
                # Not classified either way — report as a defect rather than excusing it, but
                # say that the classification is uncertain.
                real_defects.append(f)

        for f in findings:
            mark = {
                Verdict.PASS: "pass ",
                Verdict.FAIL: "FAIL ",
                Verdict.INCONCLUSIVE: "?    ",
                Verdict.SKIPPED: "-    ",
            }[f.verdict]
            sev = "MUST " if f.rule.severity is Severity.MUST else "SHOULD"
            tag = ""
            if f in real_defects:
                tag = "  << REAL DEFECT"
            elif f in version_gaps:
                tag = "  (version gap)"
            print(f"  {mark}{sev} {f.rule.id:<26} {f.observed}{tag}")

        counts = summarise(findings)
        print()
        print(
            f"  {counts['pass']} pass · {counts['fail']} fail · "
            f"{counts['inconclusive']} inconclusive"
        )
        print(f"  → {len(real_defects)} real defect(s), {len(version_gaps)} version gap(s)")

        report.append(
            {
                "server": name,
                "url": url,
                "declared_revision": revision.declared,
                "audited_against": PROTOCOL_VERSION,
                "version_gap": gap,
                "counts": counts,
                "real_defects": [
                    {
                        "rule": f.rule.id,
                        "severity": str(f.rule.severity),
                        "clause": f.rule.clause,
                        "observed": f.observed,
                        "detail": f.detail,
                        "why_real": (
                            "this requirement is unchanged across revisions, so the server's "
                            "own target revision requires it too"
                        ),
                    }
                    for f in real_defects
                ],
                "version_gaps": [{"rule": f.rule.id, "observed": f.observed} for f in version_gaps],
            }
        )
        print()

    # ── criterion 2, honestly assessed ──
    with_defects = [r for r in report if r["real_defects"]]
    all_gapped = all(r["version_gap"] for r in report)

    print(f"{'=' * 78}\nCRITERION 2\n{'=' * 78}")
    print("Threshold: >=3 distinct servers with >=1 MUST violation.\n")
    print(f"  servers audited:                        {len(report)}")
    print(f"  servers targeting an earlier revision:  {sum(1 for r in report if r['version_gap'])}")
    print(f"  servers with a REAL defect:             {len(with_defects)}")
    for r in with_defects:
        rules = ", ".join(str(d["rule"]) for d in r["real_defects"])  # type: ignore[index]
        print(f"    {r['server']}: {rules}")

    print()
    if all_gapped:
        print("  FINDING: no audited server implements this revision. Every server checked")
        print(f"  targets 2025-03-26 or 2025-06-18, so most {PROTOCOL_VERSION} MUST failures are")
        print("  version gaps rather than defects. Criterion 2's premise — that authors believe")
        print("  their servers are correct against THIS revision — does not hold yet.")
        print()
    verdict = "MET" if len(with_defects) >= 3 else f"NOT MET ({len(with_defects)}/3 real defects)"
    print(f"  Criterion 2: {verdict}")

    out = Path(__file__).parent / "results" / "third-party.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "audited_against": PROTOCOL_VERSION,
                "servers": len(report),
                "all_target_earlier_revisions": all_gapped,
                "servers_with_real_defects": len(with_defects),
                "criterion_2_met": len(with_defects) >= 3,
                "revision_independent_rules": sorted(REVISION_INDEPENDENT),
                "reports": report,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nraw → {out}")


if __name__ == "__main__":
    main()
