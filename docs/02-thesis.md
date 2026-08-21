# 02 — Thesis and Success Criteria

> **Gate:** committed **before the first feature commit** beyond the conformance probe
> that produced the baseline in `01-problem.md`.

## Thesis

**Conformance to MCP 2026-07-28 and behaviour under concurrent load are both mechanically
checkable, and checking them finds real defects in servers their authors believe are
correct — including servers written by people who have read the specification.**

The evidence for the second half already exists: the first server audited was my own, and
it had **6 MUST violations of 8**.

Falsifiable two ways. If the checker only ever finds defects in obviously abandoned
servers, it is a linter for dead code and not worth shipping. If load profiling surfaces
no cliff in any real server, the concurrency half of the premise is wrong and I say so.

## Success criteria

| # | Criterion | Threshold | How measured |
|---|---|---|---|
| 1 | **Conformance probes are spec-traceable** | 100% of rules cite a clause | Every `Rule` carries `clause`; a test asserts none is empty |
| 2 | **Real defects found in real servers** | ≥3 distinct servers with ≥1 MUST violation | `bench/conformance/audit.py` over a target list |
| 3 | **No false positives on a conforming server** | 0 failures against a reference server built strictly to spec | `bench/conformance/` runs against `tests/fixtures/reference_server.py` |
| 4 | **Load profiling finds a non-obvious cliff** | ≥1 server whose p99 degrades >5× before saturation | `bench/load/` ramping concurrency, percentiles over ≥3 runs |
| 5 | **Inconclusive is reported, never guessed** | ambiguous response → `INCONCLUSIVE` | Adversarial suite feeds malformed and hostile responses |
| 6 | **Adversarial probes cannot damage a target** | 0 writes, 0 state mutation | Every probe is read-only or a rejected request; asserted in tests |

Criterion 3 is the one that makes the tool trustworthy. A checker that flags a correct
server is worse than no checker, because the first false positive teaches its user to
ignore it.

## Kill conditions

- **If the reference server cannot pass every rule**, my reading of the spec is wrong, not
  the servers'. Fix the rules and publish the correction.
- **If load profiling finds no cliff in any real server**, drop the load half and publish
  the negative result: "MCP servers at realistic concurrency are not the bottleneck" is
  useful and would save others the work.
- **If every audited server passes**, the ecosystem has already migrated and this tool is
  unnecessary. Publish that too — it is a more interesting finding than the alternative.

## Explicitly not claimed

- Not claiming other servers are badly built. The first failing server is mine, and the
  writeup leads with that.
- Not a security scanner. It checks the protocol's own stated security requirements
  (`Origin` validation, header/body agreement) and nothing beyond them.
- Not claiming the spec is unreasonable. Every rule here is a MUST or SHOULD written
  down by the specification, quoted with its clause.

## Out of scope

See `NON-GOALS.md`.
