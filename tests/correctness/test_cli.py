"""Tests for the command-line interface.

WHY THESE EXIST: the README and a disclosure sent to a third-party maintainer both instructed
readers to `pipx install` this package and run `mcpgauntlet audit <url>`. Neither worked — there was
no entry point and no CLI module. The instruction was written before the thing it described, and
nothing checked that the documented command existed.
"""

from __future__ import annotations

import json

import pytest

from mcpgauntlet import cli
from mcpgauntlet.spec import (
    INTRODUCED_IN_2026_07_28,
    REVISION_INDEPENDENT,
    RULES,
    classify,
)


class TestClassificationCoversEveryRule:
    """The classification sets are strings; nothing checked them against the rules they name."""

    def test_no_phantom_rule_ids(self) -> None:
        """A set naming a rule that does not exist silently shrinks itself.

        `content-type-json` was in the original set and matches no rule, so the "real defect"
        category held one entry while appearing to hold two.
        """
        known = {r.id for r in RULES}
        phantom = (REVISION_INDEPENDENT | INTRODUCED_IN_2026_07_28) - known
        assert phantom == set(), f"classification names non-existent rules: {sorted(phantom)}"

    def test_every_rule_is_explicitly_classified(self) -> None:
        """Relying on `classify`'s default means nobody decided."""
        known = {r.id for r in RULES}
        unclassified = known - REVISION_INDEPENDENT - INTRODUCED_IN_2026_07_28
        assert unclassified == set(), f"unclassified rules: {sorted(unclassified)}"

    def test_the_two_sets_are_disjoint(self) -> None:
        assert not (REVISION_INDEPENDENT & INTRODUCED_IN_2026_07_28)

    def test_origin_is_a_defect_even_on_an_older_server(self) -> None:
        """The whole point of the split: this MUST predates the audited revision."""
        assert classify("origin-403", version_gap=True) == "defect"

    def test_a_new_rule_is_a_gap_on_an_older_server_but_a_defect_on_a_current_one(self) -> None:
        assert classify("get-405", version_gap=True) == "version-gap"
        assert classify("get-405", version_gap=False) == "defect"

    def test_an_unknown_rule_defaults_to_defect(self) -> None:
        """Excusing a violation the tool has no opinion about would understate a real finding."""
        assert classify("not-a-real-rule", version_gap=True) == "defect"


class TestPermissionGuard:
    """Read-only probes are still unsolicited requests to someone else's server."""

    @pytest.mark.parametrize(
        "url", ["https://example.com/mcp", "http://192.168.1.10/mcp", "https://gitmcp.io/docs"]
    )
    def test_a_remote_host_is_refused_without_the_flag(self, url: str, capsys) -> None:
        code = cli.main(["audit", url])
        assert code == 2
        assert "Refusing to probe" in capsys.readouterr().err

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:8000/mcp",
            "http://127.0.0.1:8000/mcp",
            "http://[::1]:8000/mcp",
        ],
    )
    def test_local_hosts_need_no_flag(self, url: str) -> None:
        """A tool that nags about auditing your own laptop will be run with the flag always on."""
        assert cli._is_local(url) is True

    def test_a_hostname_that_merely_contains_localhost_is_not_local(self) -> None:
        """`localhost.attacker.example` resolves wherever the attacker likes."""
        assert cli._is_local("https://localhost.attacker.example/mcp") is False

    def test_a_malformed_url_is_not_treated_as_local(self) -> None:
        assert cli._is_local("not a url at all") is False


class TestRulesCommand:
    def test_lists_every_rule_with_its_clause(self, capsys) -> None:
        assert cli.main(["rules"]) == 0
        out = capsys.readouterr().out
        for rule in RULES:
            assert rule.id in out
            assert rule.clause in out

    def test_json_output_is_machine_readable_and_complete(self, capsys) -> None:
        assert cli.main(["rules", "--json"]) == 0
        data = json.loads(capsys.readouterr().out)
        assert len(data) == len(RULES)
        assert all(r["clause"] for r in data), "a rule with no clause is an opinion"
        assert all(r["classification"] in {"defect", "version-gap"} for r in data)


class TestEntryPointIsDeclared:
    def test_pyproject_registers_the_console_script(self) -> None:
        """The bug this whole module fixes: documented command, no entry point."""
        import pathlib
        import tomllib

        root = pathlib.Path(__file__).resolve().parents[2]
        data = tomllib.loads((root / "pyproject.toml").read_text())
        scripts = data["project"].get("scripts", {})
        assert scripts.get("mcpgauntlet") == "mcpgauntlet.cli:main"
