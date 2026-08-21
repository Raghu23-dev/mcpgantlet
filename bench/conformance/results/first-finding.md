# First finding: my own server, 6 MUST violations of 8

Date: 2026-08-21 · Target: `https://trigsight.vercel.app/api/mcp`

## Why this is the right first result

The tool's premise is that MCP servers violate the current specification without their
authors knowing. The strongest possible evidence for that is not finding a defect in
someone else's abandoned project — it is finding one in a server I had written, reviewed,
and deployed to production **the same day**, having read the research on this exact spec
revision.

I was wrong in six places.

## Before

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
| `accept-both` | SHOULD | application/json | pass |
| `session-id-ignored` | SHOULD | not echoed | pass |

**6 MUST violations.**

## After

10 pass · 0 fail · **0 MUST violations** — verified against the production deployment,
not a local build.

## The most instructive violation

`no-initialize`. The server answered the `initialize` handshake and returned
`protocolVersion: "2026-07-28"` — a revision that **removed** that handshake. It
advertised a version it did not implement.

A client doing era detection would have seen a successful `initialize`, concluded the
server spoke a pre-2026 revision, and negotiated down — while the server believed it was
current. Nothing would have errored. The failure is invisible without a checker that reads
the spec clause by clause.

## What this says about the root cause

I built the server from summary notes. The notes were accurate about the headline change
("stateless, sessions removed") and silent on the consequences: that `initialize` must
therefore not be answered, that `GET` must be 405, that header/body agreement is now
mandatory with a specific error code, and that an unknown method has a required HTTP
status.

**A summary of a specification is not a specification.** That is the reusable lesson, and
it is why every rule in `src/mcpgauntlet/spec.py` carries the clause it enforces — so a
future reader checks the spec rather than trusting my summary of it.

## Reproduce

```bash
python bench/conformance/audit.py https://trigsight.vercel.app/api/mcp
```
