# mcpgauntlet

**Conformance and load checks for MCP servers on spec `2026-07-28`.**

The first server it audited was my own. It failed **6 of 8 MUST requirements**.

## Why this exists

Revision `2026-07-28` changed the shape of MCP's HTTP transport. It removed protocol-level
sessions, the GET stream endpoint, server-initiated requests and `Last-Event-ID`
resumability — and added mandatory request-metadata headers with server-side header/body
validation.

A server built to the previous shape does not merely look dated. It violates several MUSTs
of the current revision, and a client that mis-detects the era silently negotiates down.

I had read the research on this exact revision, written a server, reviewed it, and deployed
it to production. Then I pointed this tool at it:

| Rule | Severity | Observed | Verdict |
|---|---|---|---|
| `origin-403` | MUST | 403 | pass |
| `get-405` | MUST | 200 | **fail** |
| `delete-405` | MUST | 405 | pass |
| `protocol-version-header` | MUST | 200 | **fail** |
| `header-body-match` | MUST | 200 | **fail** |
| `unknown-method-404` | MUST | 200 | **fail** |
| `no-initialize` | MUST | 200, claims 2026-07-28 | **fail** |
| `notification-202` | MUST | 200 | **fail** |

The instructive one is `no-initialize`. The server answered the `initialize` handshake and
returned `protocolVersion: "2026-07-28"` — a revision that **removed** that handshake. A
client doing era detection would have seen a successful `initialize`, concluded the server
spoke a pre-2026 revision, and negotiated down. **Nothing would have errored.**

Now 10 pass, 0 fail, verified against the production deployment.
Full writeup: [`bench/conformance/results/first-finding.md`](bench/conformance/results/first-finding.md)

## Quickstart

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]" fastapi uvicorn

python bench/conformance/audit.py https://your-server.example/mcp
```

No credentials. Ten probes, each citing the spec clause it enforces — so you can check the
rule rather than trust my reading of it.

## What it checks

**Conformance** — 11 rules, 8 MUST and 3 SHOULD, every one traceable to a clause:
`Origin` → 403 · GET/DELETE → 405 · `MCP-Protocol-Version` required · header/body agreement
→ 400 with `-32020` · unknown method → 404 with `-32601` · `initialize` not answered ·
notification → 202 · content type · session-id ignored.

**Load** — a concurrency ramp reporting p50/p95/p99, throughput and error onset, looking for
where a server stops degrading gracefully.

## Load results are attributed, not just measured

This is the part I got wrong first, and the fix is the interesting bit.

The initial ramp against a reference server reported **p99 degrading 769×** and throughput
collapsing from 2,024 to 284 rps with zero errors. Textbook cliff.

Then I ran a control with **4× the server workers**:

| Concurrency | 1 worker | 4 workers | Change |
|---|---|---|---|
| 1 | 1,096 rps | 1,424 rps | +30% |
| 10 | 945 rps | 956 rps | **+1%** |
| 50 | 346 rps | 351 rps | **+1%** |

If the server were the constraint, quadrupling its workers would move the cliff. It moved it
by one percent. **The bottleneck was my own client**, with both processes on one machine.

So the profiler now calibrates its own ceiling against a trivial in-process endpoint before
profiling anything, and reports a step near that ceiling as `harness_limited` rather than as
a server finding:

```
concurrency 50  harness_limited
  throughput 349 rps is at this harness's own ceiling of 367 rps. Degradation at or
  above this concurrency cannot be attributed to the server — move the client to a
  separate host to measure it.
```

A false "your server has a cliff" is worse than a missed one: it sends someone optimising a
server that was fine, and the first false positive destroys trust in every later report.

Full writeup: [`bench/load/results/harness-limit-2026-08-21.md`](bench/load/results/harness-limit-2026-08-21.md)

## Status against pre-registered criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Every rule cites a spec clause | **met** — asserted in tests |
| 2 | Real defects in ≥3 real servers | **partial** — 1 server (mine), 6 MUST violations |
| 3 | Zero false positives on a conformant server | **met** — 0 failures against the reference |
| 4 | Load profiling finds a non-obvious cliff | **NOT met** — the cliff found was the harness's |
| 5 | Inconclusive reported, never guessed | **met** |
| 6 | Probes cannot damage a target | **met** — read-only or rejected requests only |

Criterion 4 is open and stated as open. A p99 degradation was measured but cannot be
attributed to the server, so claiming it would mean shipping a load tool whose headline
finding is an artefact of the tool.

## It will not load-test a host you do not control

```
$ python bench/load/profile.py https://someone-elses-server.example/mcp
refusing to load-test someone-elses-server.example: pass --i-have-permission if you control it.
Load testing an endpoint you do not control is abuse regardless of intent.
```

Conformance probes are read-only or deliberately-rejected requests and are safe against any
endpoint. Load generation is not, and the tool should not make it frictionless.

## Limitations

- **Load results from a single machine are harness-limited above ~10 concurrency.** Real
  profiling needs the client on a separate host. The tool now says so instead of pretending
  otherwise.
- **Only one server has been audited** — mine. Criterion 2 needs three, and third-party
  audits are conformance-only (read-only probes, no load).
- **`error_onset` is currently suppressed at a harness-limited concurrency.** Errors are the
  server's regardless of who the throughput bottleneck is, so this should be split. Asserted
  in a test so the gap is visible rather than silently wrong.
- **Conformance covers the transport, not tool behaviour.** Whether a tool returns correct
  results is the server author's domain.
- **Only revision `2026-07-28`.** A checker that accepts every revision cannot tell you
  which one you implement, which is the question worth answering.
- **The 11 rules are not the whole spec.** They are the ones mechanically checkable from
  outside with a handful of requests.

## Licence

MIT — see [LICENSE](LICENSE).
