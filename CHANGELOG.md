# Changelog

Generated from Conventional Commits. Notable changes per release.

## [Unreleased]

## [0.3.2] — 2026-08-21

### Fixed
- The landing page and `/health` advertised `0.1.0` across every release, so a viewer comparing
  the version against the repo's releases saw an abandoned deployment. Found by viewing the live
  instance as a visitor.

## [0.3.1] — 2026-08-21

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
