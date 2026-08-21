"""Criterion 3: ZERO failures against a strictly conformant server.

A checker that flags a correct server is worse than no checker — the first false positive
teaches its user to ignore every later report. So the reference server is the tool's own
regression test.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from mcpgauntlet.conformance import Auditor, Verdict
from mcpgauntlet.spec import Severity
from tests.fixtures.reference_server import create_reference_app

PORT = 8391


@pytest.fixture(scope="module")
def reference_url() -> Iterator[str]:
    config = uvicorn.Config(create_reference_app(), host="127.0.0.1", port=PORT, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{PORT}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


def test_reference_server_has_zero_failures(reference_url: str) -> None:
    with Auditor(reference_url) as auditor:
        findings = auditor.run()

    failures = [f for f in findings if f.verdict is Verdict.FAIL]
    assert not failures, "false positives against a conformant server:\n" + "\n".join(
        f"  {f.rule.id}: observed {f.observed} — {f.detail}" for f in failures
    )


def test_reference_server_has_no_must_violations(reference_url: str) -> None:
    with Auditor(reference_url) as auditor:
        findings = auditor.run()
    must_fails = [
        f for f in findings if f.verdict is Verdict.FAIL and f.rule.severity is Severity.MUST
    ]
    assert not must_fails


def test_every_probe_reaches_a_verdict(reference_url: str) -> None:
    """No probe may silently skip. A skipped rule is an unchecked rule."""
    with Auditor(reference_url) as auditor:
        findings = auditor.run()
    assert all(f.verdict is not Verdict.SKIPPED for f in findings)
    assert len(findings) == 10


def test_every_rule_cites_a_spec_clause() -> None:
    """Criterion 1: a rule without a clause is one person's opinion."""
    from mcpgauntlet.spec import RULES

    assert RULES
    for rule in RULES:
        assert rule.clause.strip(), f"{rule.id} cites no clause"
        assert rule.rationale.strip(), f"{rule.id} gives no rationale"
