# Changelog

Generated from Conventional Commits. Notable changes per release.

## [Unreleased]

### Fixed
- **CI had failed on every run, including all three release tags.** `tests/correctness` imports
  `uvicorn`, which no dependency group declared, so the module failed to *collect* — criterion 3
  ("no false positives against a conforming server") had therefore never run in CI. Declared as
  a dev dependency.
- Added the missing `src/mcpgauntlet/__init__.py`: the package used relative imports without
  one, which caused mypy to resolve each module twice and produced 24 of 27 errors. Added
  `py.typed` so consumers get types.
- `bench/load/profile.py` bound a `Cliff` to `c`, already used as the int concurrency in the
  ramp loop above; `_calibrate` was annotated `dict[str, float]` while keying by int.
