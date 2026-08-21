# 01 — The Problem

> **Gate:** contains a measurement I took myself. Harness: `bench/conformance/audit.py`.
> Raw results: `bench/conformance/results/audit.json`.

## Statement

**MCP servers are deployed with no way to know whether they conform to the protocol they
claim, survive concurrent load, or are safe.** The official conformance material has no
concurrency dimension, and the protocol changed shape in a way that silently invalidates
servers built to an earlier revision.

## Why this is urgent rather than merely true

Revision **2026-07-28** removed protocol-level sessions, the GET stream endpoint,
server-initiated JSON-RPC requests, and `Last-Event-ID` resumability. It **added**
mandatory request-metadata headers with server-side header/body validation.

Verified directly against the specification, not from secondary reporting:

- Servers **MUST** validate `Origin` and return **403** on an invalid one, explicitly to
  prevent DNS rebinding.
- Every POST **MUST** carry `MCP-Protocol-Version`; a mismatch with the body's `_meta`
  **MUST** be rejected with **400** and JSON-RPC error **-32020** (`HeaderMismatch`).
- The spec states the reason plainly: an intermediary may route on the header while the
  server executes on the body, so divergence is a security vulnerability rather than a
  formatting nit.
- An unimplemented method **MUST** return **404** with **-32601**, specifically so a
  client can distinguish a modern server from a legacy one.
- `GET`/`DELETE` **SHOULD** return **405**; `Mcp-Session-Id` and `Last-Event-ID` **SHOULD**
  be ignored.

A server built to the previous shape does not merely look dated — it violates several
MUSTs of the current revision, and a client that mis-detects the era negotiates down.

## The measured baseline

The first server audited was **my own**, deployed the same day at
`https://trigsight.vercel.app/api/mcp`, written against research notes rather than the
specification text.

| Rule | Severity | Observed | Verdict |
|---|---|---|---|
| `origin-403` | MUST | 403 | pass |
| `get-405` | MUST | **200** | **fail** |
| `delete-405` | MUST | 405 | pass |
| `protocol-version-header` | MUST | **200** | **fail** |
| `header-body-match` | MUST | **200** | **fail** |
| `unknown-method-404` | MUST | **200** / -32601 | **fail** |
| `no-initialize` | MUST | **200, claims 2026-07-28** | **fail** |
| `notification-202` | MUST | **200** | **fail** |
| `accept-both` | SHOULD | application/json | pass |
| `session-id-ignored` | SHOULD | not echoed | pass |

**6 MUST violations of 8.**

The most instructive one is `no-initialize`. My server advertises `protocolVersion:
2026-07-28` in an `initialize` response — a handshake that revision **removed**. It
claims a version it does not implement, which is precisely the failure this tool exists
to surface, and I shipped it to production without noticing.

That is the argument for the tool in one line: **I read the research, wrote a server,
deployed it, and was wrong in six places.** A checker that reads the spec clause by
clause found in seconds what review did not.

## Why existing tooling does not cover this

Two gaps, both structural rather than incidental:

1. **Conformance material has no concurrency dimension.** Whether a server answers
   correctly at one request per second says nothing about whether it survives fifty.
2. **A scanner pinned to an older SDK cannot evaluate the current revision.** The
   header-validation and 404/-32601 requirements did not exist before, so a tool that
   predates them reports a conforming server as silent and a broken one as fine.

## Reproduce

```bash
python bench/conformance/audit.py <url>
```

No credentials. Ten probes, each citing the specification clause it enforces.
