# Criterion 2 — four of five public MCP servers accept requests from any website

**Date:** 2026-08-21 · **Criterion:** ≥3 distinct servers with ≥1 MUST violation
**Verdict:** **met** — 4 of 5, all on the same rule, and it is the one that is exploitable

## The finding

Five public MCP servers, chosen for implementation diversity and reachable without credentials.
Each was sent an identical request twice: once with no `Origin` header, once with
`Origin: https://attacker.example`.

| Server | Operator | No Origin | Hostile Origin | |
|---|---|---|---|---|
| learn.microsoft.com/api/mcp | Microsoft | 200 | **200** | accepts |
| knowledge-mcp.global.api.aws | AWS | 200 | **200** | accepts |
| mcp.deepwiki.com/mcp | Cognition | 200 | **200** | accepts |
| gitmcp.io/docs | idosal (OSS) | 200 | **200** | accepts |
| **docs.mcp.cloudflare.com/mcp** | **Cloudflare** | **200** | **403** | **rejects** |

Cloudflare is the control. Same probe, same request shape, correct rejection — so the four
acceptances are a property of those servers and not an artifact of the tool.

**Why it matters.** `Origin` validation is the spec's defence against DNS rebinding — an attack that matters most for servers reachable on localhost or a private network, where the server trusts its network position. It has been a MUST since the Streamable HTTP transport was introduced, so this is not a version gap.

**What the finding is and is not.** These four servers do not enforce a MUST the specification places on them, and a client cannot tell a conformant server from a non-conformant one without checking. That is the conformance result and it stands.

It is **not** a claim that each of these deployments is exploitable. Three of the four are public, unauthenticated services: a page can drive them through a visitor's browser, but an attacker could equally call them from their own server, so the browser adds little beyond the visitor's IP. The rule's real bite is on servers that are reachable locally or hold credentials — and whether a given deployment is either of those is not something an external probe can determine.

```bash
python bench/conformance/third_party.py
```

## The reframing that had to happen first

Criterion 2 asked for "≥3 distinct servers with ≥1 MUST violation", on the thesis that
conformance checking finds real defects in servers whose authors believe they are correct.

Before auditing anything, every target was asked which revision it speaks:

| Server | Declares |
|---|---|
| learn.microsoft.com | 2025-06-18 |
| knowledge-mcp.global.api.aws | 2025-03-26 |
| docs.mcp.cloudflare.com | 2025-06-18 |
| mcp.deepwiki.com | 2025-06-18 |
| gitmcp.io | 2025-03-26 |

**None implements 2026-07-28.** That revision removed sessions and the GET stream and added
mandatory request-metadata headers, so a 2025-06-18 server fails most of its MUSTs by
construction while being perfectly conformant to what it targets.

A naive run would have reported **23 failures across five servers** — 18 version gaps plus 5
real defects, which is also the total fail count in `third-party.json` — every one technically
accurate and most of it misleading. That is the same "97% of servers flagged at under 50%
precision" noise `docs/01-problem.md` criticises existing scanners for. Producing it would have
made this tool the thing it was built to replace.

**Corrected 2026-08-21.** This paragraph said "roughly 40". No artifact from this run supports
40: the JSON gives 18 + 5 = 23, and summing `counts.fail` across the five reports also gives 23.
The figure reached a deck and a LinkedIn draft before being caught, because `verify_claims.py`
pools every project's numbers and fusegrid's baseline legitimately contains 40 — so a wrong
number for *this* project passed as a real number from another one. Where "40" came from is not
recoverable from the artifacts, and that is recorded rather than guessed at.

So findings are now classified:

- **version gap** — the rule is new in or changed by 2026-07-28. Reported, never counted.
- **real defect** — the rule is unchanged across revisions, so the server's *own* target
  revision requires it too.

Under that split: **18 version gaps, 5 real defects.** (Written as 26 when this report was first generated. `third-party.json` from the same run records 18, and re-running the audit against the same five servers reproduces 18 — so 18 is the number. Why the prose said 26 is not recoverable from the artifacts; the machine-readable output is authoritative, which is why the claim gate reads the JSON rather than this file.) The honest criterion-2 result is the
second number, and it is a harder test than the one originally written.

## The probe was wrong first, and reported four vulnerabilities anyway

The original `probe_origin` sent one request carrying a hostile `Origin` and failed the server on
any non-403 response. It reported four of these five servers as vulnerable.

Correct conclusion, worthless evidence. Those servers had returned **400** — a *rejection* —
because a 2026-07-28-shaped request is refused on protocol grounds before `Origin` is ever
evaluated. The probe was measuring version mismatch and calling it a security hole.

It is now **paired**: the same request with and without the hostile header, using a request shape
the server itself accepts, with the verdict taken only from the difference.

| Baseline | Hostile | Verdict |
|---|---|---|
| rejected | — | **INCONCLUSIVE** — nothing can be concluded from a request the server refuses anyway |
| accepted | rejected | pass |
| accepted | **accepted** | **FAIL**, on evidence |

That change also downgraded Cloudflare from `pass` to `INCONCLUSIVE` when probed with a shape it
refuses — correctly, since a server should not be credited with a property that was never
observed. Probed with a request it accepts, it passes.

Had the unpaired probe been published, the headline number would have been right for the wrong
reason, and the first person to check would have found the reasoning did not hold.

## Disclosure position

Every probe is read-only: one `initialize`, one `tools/list`, and requests the specification
itself requires a server to reject. Eleven requests per host, well inside any published rate
limit, sent with a descriptive user agent so any operator can identify the traffic.

Deliberately not probed: per-tenant endpoints on Wix and Shopify sites, which would mean testing
an individual site owner who never opted in; and any host whose terms bar automated testing —
Figma, Linear and Square were excluded on that basis, and GitHub's endpoint is outside its
published safe harbour.

**No exploit was attempted.** The finding is that a foreign `Origin` is accepted, which is
established entirely by the status code of a well-formed request. No rebinding attack was
constructed, and none should be read into this.

`Origin` validation is also **not the only** control available to these operators — several sit
behind authentication or a CDN that may impose its own checks. What is measured is that the
endpoint itself does not enforce the requirement the spec places on it.

This is a protocol-conformance result about publicly documented endpoints, published as a
measurement. Anyone acting on it for a server they operate should confirm it against their own
deployment first — `python bench/conformance/third_party.py` reproduces every number here.

## What criterion 2 actually established

The original thesis — "checking finds real defects in servers their authors believe are correct,
including servers written by people who have read the specification" — holds, but the defect
found is not the one expected. It is not an obscure transport detail. It is the single
security-relevant MUST in the specification, missing from four independently built servers
operated by Microsoft, AWS, Cognition and an open-source maintainer.

**Corrected 2026-08-22.** An earlier version of this report called the rule's absence "directly
exploitable from a browser" without qualification. The tool's own rule text was precise — it says
"a *local* MCP server" — but this writeup, the README and a drafted LinkedIn post all dropped the
word. For a public unauthenticated server the browser adds little an attacker could not do from
their own machine. Found while preparing a patch for one of the four; corrected in all three places
before the post went out.

And the more useful finding is the one that came from asking a question before running the tool:
**the ecosystem has not migrated to the current revision at all.** A checker that had not asked
would have buried that under forty false positives.
