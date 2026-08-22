#!/usr/bin/env python3
"""Audit a live MCP endpoint against spec 2026-07-28.

Usage:  python bench/conformance/audit.py <url> [<url> ...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mcpgantlet.conformance import Auditor, Verdict, summarise
from mcpgantlet.spec import PROTOCOL_VERSION, Severity

MARK = {Verdict.PASS: "pass", Verdict.FAIL: "FAIL", Verdict.INCONCLUSIVE: "?", Verdict.SKIPPED: "-"}


def main() -> None:
    urls = sys.argv[1:]
    if not urls:
        print(__doc__)
        sys.exit(2)

    report: list[dict[str, object]] = []

    for url in urls:
        print(f"\n{url}")
        print(f"against spec {PROTOCOL_VERSION}")
        print("-" * 78)
        with Auditor(url) as auditor:
            findings = auditor.run()

        for f in findings:
            sev = "MUST " if f.rule.severity is Severity.MUST else "SHOULD"
            print(f"  {MARK[f.verdict]:<5} {sev} {f.rule.id:<26} observed: {f.observed}")
            if f.is_violation and f.detail:
                print(f"        → {f.detail}")

        counts = summarise(findings)
        print()
        print(
            f"  {counts['pass']} pass · {counts['fail']} fail · "
            f"{counts['inconclusive']} inconclusive · "
            f"{counts['must_violations']} MUST violations"
        )
        report.append(
            {
                "url": url,
                "counts": counts,
                "findings": [
                    {
                        "rule": f.rule.id,
                        "severity": f.rule.severity.value,
                        "clause": f.rule.clause,
                        "verdict": f.verdict.value,
                        "observed": f.observed,
                        "detail": f.detail,
                    }
                    for f in findings
                ],
            }
        )

    out = Path(__file__).parent / "results" / "audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"spec": PROTOCOL_VERSION, "targets": report}, indent=2) + "\n")
    print(f"\nraw results → {out}")


if __name__ == "__main__":
    main()
