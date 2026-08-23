# Changelog

Generated from Conventional Commits. Notable changes per release.

## [0.5.0] — 2026-08-23

### Changed
- **Version bumped to 0.5.0 rather than publishing 0.4.0.** A `v0.4.0` tag already existed from
  before the rename, and that tagged tree declares `name = "mcpgauntlet"` — the name PyPI refused.
  The workflow's tag-vs-version guard would have passed it, because 0.4.0 does equal 0.4.0; only
  the name was wrong. A new version is the honest way to publish a renamed package, since a
  rename is a breaking change for anyone importing it.
- **Renamed from `mcpgauntlet` to `mcpgantlet`.** PyPI refused the original name: it collapses
  separators and folds `l`/`i` to `1` and `o` to `0` before comparing, so `mcpgauntlet` and the
  unrelated `mcp-gauntlet` — published 2026-07-24, a month before this project — normalise to the
  same string and cannot coexist. `gantlet` is the older spelling of the ordeal; `gauntlet` (the
  armoured glove) is a long-standing confusion with it, so the correct spelling was also the
  available one.
  - The import path, console script and repo are all `mcpgantlet`. GitHub redirects the old repo
    URL.
  - **The deployment now answers on both `mcpgantlet.vercel.app` (canonical) and
    `mcpgauntlet.vercel.app`.** The first plan was to leave the Vercel project alone, on the
    assumption that a `.vercel.app` subdomain is bound to the project name and renaming would
    kill the old URL — which appears in a vulnerability report already sent to a third-party
    maintainer. That assumption was wrong: Vercel lets a second `.vercel.app` subdomain be
    attached to the same project, and both survive a project rename. So the canonical URL moved
    and the old one keeps working, instead of trading one against the other.
  - Docstrings in `cli.py` and `tests/correctness/test_cli.py` still quote the old command name.
    That is deliberate: they record what the sent report said, and rewriting them would falsify
    the history they exist to preserve.

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
