# 05 — Benchmarks and Results

> **Gate:** no number may be claimed anywhere (README, writeup, post) unless it
> comes from `bench/` and is reproducible by a stranger with one command.

## Method

**Harness:** `bench/`
**Runs:** <!-- MULTIPLE. A single run is noise. -->
**Environment:** <!-- machine, versions -->

```bash
# one command to reproduce everything below
```

## Results

| Metric | Baseline | This system | Delta | Runs | Variance |
|---|---|---|---|---|---|
| | | | | | |

**Noise floor:** <!-- what variation appears with no change at all -->
**Minimum detectable difference:** <!-- if the comparison is close, state it -->

## Third-party audit (criterion 2)

| | |
|---|---|
| Servers audited | 5, all reachable without credentials |
| Servers implementing 2026-07-28 | **0** |
| Version gaps (rule new in this revision) | 26 |
| **Real defects** (rule unchanged across revisions) | **5, across 4 servers** |
| Servers accepting `Origin: https://attacker.example` | **4 of 5** |

```bash
python bench/conformance/third_party.py
```

Full report: `bench/conformance/results/2026-08-21-third-party.md`.

## Against the success criteria

| # | Criterion | Threshold | Result | Pass |
|---|---|---|---|---|
| 1 | | | | |

## What came out worse than expected

<!-- Publish this. A measured negative result about your own work is the single
     hardest thing for anyone else to out-credential. -->
