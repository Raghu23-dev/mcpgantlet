"""The package must actually be importable under its own name, and expose what it documents.

WHY: two separate failures, both of which pass a naive smoke test.

1. `src/onewayglass/` — a sibling flagship — had no `__init__.py`, so it installed as an implicit
   namespace package. The wheel imported without error while exposing **nothing**. That is the worst
   shape of failure for a published package: `import x` succeeds and every real use breaks.

2. This package was renamed from `mcpgauntlet` to `mcpgantlet` after PyPI rejected the original
   name as too similar to an unrelated `mcp-gauntlet`. A rename touches the directory,
   `pyproject.toml` `[project.name]`, the `[project.scripts]` entry point, the hatch `packages`
   list and every import. Miss any one and the failure is silent in the wrong direction — the
   editable install in CI keeps working from a stale path while the built wheel is broken.

So these tests assert the name itself, not just that something imported.
"""

from __future__ import annotations

import importlib
import pathlib
import tomllib
from typing import Any

import mcpgantlet

PYPROJECT = pathlib.Path(__file__).resolve().parents[2] / "pyproject.toml"


def _pyproject() -> dict[str, Any]:
    return tomllib.loads(PYPROJECT.read_text())


def test_it_is_a_real_package_not_a_namespace() -> None:
    """A namespace package has __file__ of None. It installs, imports, and exports nothing."""
    assert mcpgantlet.__file__ is not None, (
        "mcpgantlet installed as an implicit namespace package — src/mcpgantlet/__init__.py is "
        "missing, so the package exposes no public API"
    )


def test_the_init_file_exists_on_disk() -> None:
    root = pathlib.Path(mcpgantlet.__file__).parent
    assert (root / "__init__.py").is_file()


def test_the_import_name_matches_the_distribution_name() -> None:
    """The rename's failure mode: a distribution called one thing importing as another.

    `pip install mcpgantlet` must give `import mcpgantlet`. If `[project.name]` and the package
    directory drift apart, the wheel still builds and still imports *in the source tree*, because
    the editable install resolves the old path.
    """
    dist_name = _pyproject()["project"]["name"]
    assert dist_name == "mcpgantlet", f"distribution name is {dist_name!r}"
    assert mcpgantlet.__name__ == dist_name
    assert pathlib.Path(mcpgantlet.__file__).parent.name == dist_name


def test_hatch_builds_the_directory_that_actually_exists() -> None:
    """A stale `packages` entry produces a wheel containing nothing, and hatch does not complain."""
    configured = _pyproject()["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    for entry in configured:
        assert (PYPROJECT.parent / entry).is_dir(), (
            f"packages names {entry!r}, which does not exist"
        )


def test_the_old_name_is_gone() -> None:
    """A rename that leaves the old package importable means both shipped."""
    src = PYPROJECT.parent / "src"
    assert not (src / "mcpgauntlet").exists(), "the pre-rename package directory still exists"


def test_every_name_in_all_is_actually_importable() -> None:
    """__all__ is a promise. An entry that does not resolve breaks `from mcpgantlet import *`."""
    missing = [name for name in mcpgantlet.__all__ if not hasattr(mcpgantlet, name)]
    assert missing == [], f"__all__ names that do not resolve: {missing}"


def test_the_documented_usage_from_the_docstring_runs() -> None:
    """The example in the module docstring is the first thing anyone tries."""
    from mcpgantlet import PROTOCOL_VERSION, RULES, RULES_BY_ID, Severity

    assert RULES, "the rule set is empty — the tool would report every server conformant"
    assert all(r.clause for r in RULES), "a rule with no spec clause is an opinion"
    assert RULES_BY_ID[RULES[0].id] is RULES[0]
    assert PROTOCOL_VERSION
    assert Severity.MUST in {r.severity for r in RULES}


def test_the_console_script_points_at_a_real_callable() -> None:
    """`[project.scripts]` is a string. Nothing checks the target resolves until a user runs it."""
    scripts = _pyproject()["project"].get("scripts", {})
    assert scripts, "no console script declared — `pipx install` gives a library and no command"
    for name, target in scripts.items():
        module_path, _, attr = target.partition(":")
        module = importlib.import_module(module_path)
        assert callable(getattr(module, attr)), f"{name} -> {target} is not callable"


def test_py_typed_ships_so_consumers_get_types() -> None:
    """Without this marker mypy treats the package as untyped, whatever annotations it carries."""
    root = pathlib.Path(mcpgantlet.__file__).parent
    assert (root / "py.typed").is_file()


def test_the_version_is_not_a_placeholder() -> None:
    """0.0.0 published to PyPI is permanent — a version can never be re-uploaded."""
    version = _pyproject()["project"]["version"]
    assert version != "0.0.0", "refusing to publish a placeholder version"
    assert importlib.import_module("mcpgantlet") is mcpgantlet
