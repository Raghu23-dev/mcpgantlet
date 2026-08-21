# The cliff I found was in my own harness, not the server

Recorded because publishing the wrong interpretation would have been worse than publishing
nothing, and the correction is more useful than the original finding.

## What the ramp showed

Reference server, 200 requests per step:

| Concurrency | p50 ms | p99 ms | rps | errors |
|---|---|---|---|---|
| 1 | 0.6 | 1.3 | 1,393 | 0 |
| 5 | 2.1 | 5.8 | 2,024 | 0 |
| 10 | 8.2 | 24.8 | 999 | 0 |
| 25 | 35.3 | 228.3 | 462 | 0 |
| 50 | 109.6 | 721.5 | 284 | 0 |
| 100 | 196.6 | 991.4 | 315 | 0 |

The detector flagged a `latency_cliff` at concurrency 10 (p99 19× baseline, reaching 769×
at 100) and a `throughput_collapse` from 2,024 rps down to 284.

Read naively, that is criterion 4 met: a non-obvious cliff, well before saturation, with
zero errors to hint at it.

## The control that killed that reading

Throughput *falling* rather than plateauing is the signature of contention — but client and
server were on the same machine, so contention could be either one. So: same ramp, same
server, **4 uvicorn workers instead of 1**.

| Concurrency | 1 worker | 4 workers | Change |
|---|---|---|---|
| 1 | 1,096 rps | 1,424 rps | **+30%** |
| 10 | 945 rps | 956 rps | **+1%** |
| 50 | 346 rps | 351 rps | **+1%** |

If the server were the constraint, quadrupling its workers would move the cliff. **It moved
it by one percent.** The constraint is on the client side — my own async client and the
loopback interface — not in the server under test.

The +30% at concurrency 1 is consistent with that: with only one request in flight there is
no client-side queueing to dominate, so the extra workers show a small real gain. Once
concurrency rises, my harness becomes the bottleneck and the server's capacity stops
mattering.

## A broken control I nearly reported

The first attempt at this control returned **0 rps across every step** for the 4-worker
case. Multi-worker uvicorn forks, and cannot pickle an app constructed in a local closure,
so the server never started — the harness was measuring connection failures.

Had I reported that, the conclusion would have been "the server collapses entirely with
multiple workers", which is the opposite of the truth. Fixed by pointing uvicorn at an
importable module (`tests/fixtures/ref_app.py`) and waiting for readiness by polling rather
than by a fixed sleep.

**A control that fails silently is worse than no control**, because it produces a confident
number.

## Criterion 4 status: NOT met, and not claimed

The pre-registered criterion was "≥1 server whose p99 degrades >5× before saturation."
A p99 degradation was measured, but it cannot be attributed to the server, so the criterion
is **not** satisfied. Marking it met would mean shipping a load tool whose headline finding
is an artefact of the tool.

## What has to change

1. **Calibrate the harness ceiling first.** Profile against a trivial static endpoint to
   establish the maximum throughput the client can generate, then report every subsequent
   number against that ceiling. A server result within 10% of the harness ceiling must be
   reported as `harness-limited`, not as a server cliff.
2. **Separate client from server.** Any load result gathered with both on one machine is
   suspect at concurrency above ~10. Real profiling needs the target on another host.
3. **Add the worker-count control as a built-in check**, not a one-off script. If doubling
   server capacity does not move a cliff, the tool should say so itself rather than relying
   on the operator to think of it.

Until (1) exists, `bench/load/profile.py` reports latency honestly but must not describe a
degradation as a server property.

## Reproduce

```bash
python bench/load/profile.py http://127.0.0.1:8401/mcp --steps 1,5,10,25,50,100
```
