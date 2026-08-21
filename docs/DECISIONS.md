# Decision Log — mcpgauntlet

Appended **as decisions happen**, never reconstructed later. Short entries, 3–6 lines.
Format: date · decision · alternatives · why · what would change it.

Cross-project decisions live in the program-level `DECISIONS.md`.

---

## 2026-08-21 — Repo scaffolded

**Decision.** python project, nine-step pipeline structure, MIT licence.
**Why.** Standard scaffold per MASTER-PLAN.md §1/§3/§4.

## 2026-08-21 — Load results must be attributed, not just measured

**Decision.** The profiler calibrates its own throughput ceiling against a trivial
in-process endpoint before profiling a target, and reports any step within
`HARNESS_LIMIT_MARGIN` of that ceiling as `harness_limited` rather than as a server cliff.

**Why.** The first ramp reported p99 degrading 769× and throughput collapsing from 2,024 to
284 rps against the reference server. A control run with 4× the server workers moved
throughput by **1%**, proving the constraint was the client. Without the guard the tool's
headline finding was an artefact of the tool.

**Margin calibrated, not chosen.** 0.9 produced a false positive at an observed ratio of
0.87. The same concurrency measured 977 then 1068 rps seconds apart with nothing changed —
a 9% swing. 0.7 accommodates that. The cost is under-reporting a genuine cliff within 30%
of the ceiling, accepted deliberately: a false "your server has a cliff" destroys trust in
every later report, a missed one does not.

**Known gap, asserted in tests rather than hidden.** The `harness_limited` branch
short-circuits, so `error_onset` is currently suppressed at a harness-limited concurrency.
Errors are the server's regardless of who the throughput bottleneck is — a harness cannot
make a server return HTTP 500 — so this should be split. Test
`test_error_onset_is_reported_even_when_harness_limited` documents the current behaviour so
the gap is visible.

**What would change it.** Running the client on a separate host removes the need for the
guard on that path, though the calibration is still worth keeping as a sanity check.
