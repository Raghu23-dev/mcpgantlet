# mcpgantlet — Technical Writeup

> **Gate:** all six sections present before the project counts as shipped.
> Hand-written prose. This document is the primary evidence of technical communication.

## 1. Problem

MCP servers are deployed with no way to know whether they conform to the protocol they
claim, survive concurrent load, or are safe — and the ground shifted under them.
Revision **2026-07-28** removed protocol-level sessions, the GET stream endpoint,
server-initiated JSON-RPC requests and `Last-Event-ID` resumability, and added mandatory
request-metadata headers with server-side header/body validation. A server built to the
previous shape doesn't just look dated; it violates several MUSTs of the current
revision, and a client that mis-detects the era negotiates down silently. Existing
conformance material has no concurrency dimension at all, and a scanner pinned to an
older SDK can't evaluate requirements that didn't exist when it was written.

I measured this against my own server first, deployed the same day at
`trigsight.vercel.app/api/mcp`, written from research notes rather than the specification
text itself:

| Rule | Severity | Observed | Verdict |
|---|---|---|---|
| `origin-403` | MUST | 403 | pass |
| `get-405` | MUST | 200 | **fail** |
| `delete-405` | MUST | 405 | pass |
| `protocol-version-header` | MUST | 200 | **fail** |
| `header-body-match` | MUST | 200 | **fail** |
| `unknown-method-404` | MUST | 200 / -32601 | **fail** |
| `no-initialize` | MUST | 200, claims 2026-07-28 | **fail** |
| `notification-202` | MUST | 200 | **fail** |

**6 MUST violations of 8.** The most instructive is `no-initialize`: my server answered
the `initialize` handshake and returned `protocolVersion: "2026-07-28"` — a revision that
*removed* that handshake. It advertised a version it did not implement. A client doing
era detection would have seen a successful `initialize`, concluded the server spoke a
pre-2026 revision, and negotiated down — with nothing ever erroring to reveal the
mistake. The root cause says more than the bug does: I'd built the server from summary
notes that were accurate about the headline change ("stateless, sessions removed") and
silent on its consequences. A summary of a specification is not a specification. That's
the argument for the tool in one line — I read the research, wrote a server, deployed
it, and was wrong in six places, and a checker reading the spec clause by clause found in
seconds what my own review hadn't.

## 2. Architecture

Two mechanically separate surfaces behind one CLI. **Conformance probing** — 11 rules, 8
MUST and 3 SHOULD, every one carrying the specification clause it enforces (`Origin` →
403, GET/DELETE → 405, `MCP-Protocol-Version` required and matched against the body →
400/-32020, unknown method → 404/-32601, `initialize` not answered, notification → 202,
content type, session-id ignored) — using only read-only requests or requests the spec
itself requires a server to reject. **Load profiling** ramps concurrency and reports
p50/p95/p99, throughput and error onset, looking for where a server stops degrading
gracefully.

The architecturally load-bearing decision sits between those two rule counts and the
report they produce: findings split into **version gaps** (a rule that's new in or
changed by 2026-07-28, so a server targeting an older revision fails it by construction)
and **real defects** (a rule unchanged across revisions, so the server's own declared
target requires it too). Only real defects fail a CI run; version gaps are reported but
never exit non-zero. Collapsing that distinction is exactly how existing scanners produce
noise — flagging ~97% of servers at under 50% precision — and it's the rejected
alternative recorded in `NON-GOALS.md`: this checks only what the specification states,
not everything a general vulnerability scanner might flag.

The load profiler carries its own architectural correction. It calibrates its own
throughput ceiling against a trivial in-process endpoint *before* profiling a target, and
reports any step within a margin of that ceiling as `harness_limited` rather than as a
server finding — a decision that exists because the first version didn't do this and
produced a finding that wasn't real (§5).

Other decisions, and what each one rejects: **no hosted auditor for arbitrary URLs** —
ruled out before any code existed, because a tool that probes whatever a stranger types
into it is a request-forgery gadget regardless of how read-only its probes are. **Load
testing requires `--i-have-permission`** and refuses outright without it — the
conformance probes are safe against any endpoint, but generating load against a server
you don't operate is abuse regardless of intent, and the tool shouldn't make that
frictionless.

## 3. Decisions

The version-gap/real-defect split is the decision most worth defending, and the
third-party audit exists specifically to prove it matters rather than just to produce a
number: five public servers, chosen for implementation diversity and reachable without
credentials, none of them implementing 2026-07-28 (they declare 2025-03-26 or
2025-06-18). A naive run — no revision check, no classification — would have reported 23
failures across five servers and called it a finding. Split by clause: **18 are version
gaps, 5 are real defects across 4 servers.** Publishing the unsplit 23 would have made
this tool the exact thing `docs/01-problem.md` criticizes existing scanners for being.

The `Origin`-validation probe itself needed a rewrite mid-audit, and the failure is
worth recording because the wrong version still produced a plausible-looking result. The
first `probe_origin` sent one request with a hostile `Origin` and failed the server on
any non-403 response — and reported four of five servers vulnerable. Correct conclusion,
worthless evidence: those servers were returning 400, a rejection on protocol grounds,
because a 2026-07-28-shaped request never reaches `Origin` evaluation on a server
targeting an older revision. The probe was measuring version mismatch and calling it a
security hole. It's now paired — the same request shape the server actually accepts, sent
once bare and once with a hostile `Origin`, with the verdict taken only from the
difference between the two. That change also downgraded Cloudflare from `pass` to
`INCONCLUSIVE` when probed with a shape it refuses, correctly, since a server shouldn't
be credited with a property that was never actually observed.

Fail-closed calibration on the load side follows the same instinct as fusegrid's ledger
decision: the harness-limited margin is 0.7, *calibrated* rather than chosen, because 0.9
produced a false positive at an observed ratio of 0.87 — the same concurrency measured
977 then 1,068 rps seconds apart with nothing changed, a 9% swing on its own. 0.7
accommodates that noise at the cost of under-reporting a genuine cliff within 30% of the
harness's own ceiling — accepted deliberately, because a false "your server has a cliff"
destroys trust in every later report, and a missed one doesn't. A known, accepted gap
follows directly from that guard: `error_onset` is currently suppressed whenever a step
is harness-limited, even though an HTTP 500 is the server's fault regardless of who the
throughput bottleneck is. Documented with a test (`test_error_onset_is_reported_even_when_harness_limited`)
rather than silently wrong.

## 4. Benchmarks

`bench/conformance/audit.py` runs the 11-rule suite against a single target — ten to
eleven read-only or deliberately-rejected requests, no credentials, each citing its
clause — and `bench/conformance/third_party.py` sweeps it across the five-server target
list used for criterion 2. `bench/load/profile.py` ramps concurrency (1/5/10/25/50/100 in
the recorded run) at 200 requests per step against a reference server, paired with an
explicit worker-count control (1 uvicorn worker vs. 4) run at matched concurrency to
separate a server-side bottleneck from a client-side one.

## 5. Results

Self-audit: 6 of 8 MUST violations found in my own production server, now 10 pass / 0
fail after fixing, reverified against the live deployment rather than a local build.
Third-party: 4 of 5 servers (Microsoft, AWS, Cognition, and an open-source maintainer)
accept an identical request carrying `Origin: https://attacker.example`; Cloudflare is
the control, returning 403 to the same probe, which is what makes the other four a
property of those servers and not an artifact of the tool. Classified by clause: **18
version gaps, 5 real defects across 4 servers** — criterion 2 required ≥3 distinct
servers with ≥1 MUST violation, and 4 clears it.

Load profiling is the criterion that didn't hold, and it's reported that way rather than
smoothed over. The first ramp against the reference server showed p99 degrading **769×**
and throughput collapsing from 2,024 rps to 284 as concurrency rose — read naively, a
textbook non-obvious cliff, criterion 4 met. The control that killed that reading:
running the identical ramp with 4 uvicorn workers instead of 1. If the server were the
constraint, quadrupling its workers should move the cliff; instead throughput moved by
**1%** at concurrency 10 and 50. The bottleneck was my own client and the loopback
interface, not the server under test. **Criterion 4: not met, and not claimed** — a p99
degradation was measured, but it can't be attributed to the server, and marking it met
would mean shipping a load tool whose headline finding is an artifact of the tool itself.

Two things came out worse than expected and are recorded rather than quietly fixed. The
`Origin` probe rewrite above (§3) is one. The other: the first attempt at the
worker-count control returned **0 rps across every step** for the 4-worker case, because
multi-worker uvicorn forks and can't pickle an app object constructed in a local closure
— so the server never actually started, and the harness was silently measuring
connection failures. Had that been reported as-is, the conclusion would have been "the
server collapses entirely under multiple workers," the opposite of the truth. Fixed by
pointing uvicorn at an importable module and polling for readiness instead of sleeping a
fixed interval. A control that fails silently is worse than no control, because it
produces a confident, wrong number.

Status against the six pre-registered criteria: 1 (spec-traceable) met — every rule
asserts a non-empty clause; 2 (≥3 servers, ≥1 violation) met — 4 servers, 5 real defects;
3 (zero false positives on a conforming reference) met; 4 (non-obvious cliff in a real
server) **not met**, for the reason above; 5 (inconclusive reported, never guessed) met;
6 (probes cannot damage a target) met — every probe is read-only or a rejected request,
asserted in tests.

## 6. Limitations

Only one server has been audited for real defects by the standard the tool holds itself
to — mine. The 4-servers-with-violations figure above answers criterion 2, but it comes
from conformance probing only; load profiling is never run against a server I don't
operate, on the same abuse-potential grounds that keep the tool from hosting an auditor
for arbitrary URLs. Load results from a single machine are harness-limited above roughly
10 concurrency, which is why criterion 4 stands unmet rather than substituted with the
harness's own ceiling relabeled as a finding — real profiling needs the client on a
separate host. `error_onset` is currently suppressed whenever a step is harness-limited,
a known and tested gap rather than a silent one, since an error is the server's
regardless of which side hit its throughput ceiling first. Conformance checks the
transport, not tool behavior: whether an MCP tool call returns a *correct* result is the
server author's domain and out of scope by design. Only revision 2026-07-28 is checked —
a tool that accepted every revision couldn't tell you which one you actually implement,
which is the question worth answering. And the 11 rules are the mechanically-checkable
subset reachable from outside with a handful of requests, not the specification in full.
