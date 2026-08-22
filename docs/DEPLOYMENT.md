# Deployment

> **Gate:** "published to a package registry" is not deployment. A stranger must be able to hit
> a running instance.

**Live:** https://mcpgauntlet.vercel.app

Criterion 3 in one request — zero findings against a server built strictly to spec:

```bash
curl https://mcpgauntlet.vercel.app/audit/self
```

## What is deployed, and what deliberately is not

`docs/NON-GOALS.md` ruled out "a hosted service or dashboard" before any code existed, on the
grounds that the value is "a citable result in CI, not a chart". Standing up
auditor-as-a-service would reverse a pre-registered commitment the moment it became convenient,
which would make the document worthless.

It would also be irresponsible in a way the same file names. An auditor that accepts an
arbitrary URL from an anonymous visitor is a request-forgery gadget aimed at whatever a stranger
types, and "every probe is read-only" does not make sending them somewhere on someone else's
behalf acceptable.

So what is deployed is what can be deployed honestly:

| Route | What |
|---|---|
| `POST /mcp` | **The reference server**, strictly conformant to MCP 2026-07-28. A fixed public target for anyone testing an MCP client — which does not otherwise exist |
| `GET /audit/self` | All 10 probes against this instance over real HTTP. **0 violations** = criterion 3, as evidence rather than a claim |
| `GET /spec/rules` | All 11 rules, each citing its clause (criterion 1) |
| `GET /health` | Version, protocol revision, rule counts |
| `GET /docs` | OpenAPI |

Auditing arbitrary targets stays a CLI, where whoever runs it is accountable for where it points.
A test asserts no endpoint accepts a target parameter and that `/audit/self` derives its target
from `request.base_url`, so the commitment cannot drift.

## Verified in production

```
GET  /audit/self       10 probes, 0 violations, 0 inconclusive — CONFORMANT
GET  /mcp              405   (the GET stream was removed in this revision)
DELETE /mcp            405
POST /mcp  no headers  400 with JSON-RPC error -32020
POST /mcp  valid       200 {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}
POST /mcp  notification 202 with 0 bytes
GET  /spec/rules       11 rules, every one citing a clause
```

The self-audit runs against the deployment's own public URL, so probes traverse the real network
path including the platform proxy — not an in-process shortcut that could pass while the deployed
server fails.

## The auditor caught a real violation in its own deployment

On the first run, `/audit/self` reported `notification-202`: **"202 with a body"**.

The reference server returns a bodiless 202 exactly as the spec requires. The forwarding layer
wrapped every response in `JSONResponse`, turning an empty body into the four bytes `null`. The
fixture was correct and the proxy broke it — precisely the class of bug a transparent proxy
introduces: the thing being audited stopped being the thing that was written.

The auditor finding that unprompted, in its own deployment, is stronger evidence it works than
any passing test.

A second bug: `/audit/self` deadlocked and timed out against itself. `Auditor` is a synchronous
httpx client, so calling it inside an async endpoint blocks the event loop that has to serve the
probes it is issuing. A server auditing itself over its own HTTP interface is the one case where
blocking the loop is self-inflicted rather than merely slow. Now offloaded to a threadpool.

## Operational surface

| Concern | Implementation |
|---|---|
| Health check | `/health` reports version, protocol revision and rule counts. The deeper check is `/audit/self`, which asserts conformance rather than liveness. |
| Structured logs | JSON to stdout, one line per request: method, path, status, duration. |
| Metrics / traces | `X-Response-Time-Ms`, `X-Mcpgauntlet-Version`. |
| Configuration | None. No environment variables, no secrets, no database. |
| Rate limiting | 120 requests / 60 s per client host, in-memory sliding window. **Per-instance and resets on cold start** — stated rather than described as rate limiting, because on serverless that is what it is. |
| Failure / degradation mode | Unhandled exceptions collapse to one opaque `500`. The MCP endpoint's own error behaviour is the spec's: `-32020` on header/body disagreement, `404` with `-32601` for unknown methods, `403` on invalid `Origin`. |
| Statefulness | None. The reference server holds no session state — the 2026-07-28 revision removed protocol-level sessions, and a `Mcp-Session-Id` is accepted and ignored, which is itself one of the audited rules. |

The deployed server mounts `tests/fixtures/reference_server.py` verbatim rather than
reimplementing it, so the public target is exactly the fixture the test suite audits.

## Deploy

```bash
uv build --wheel        # catches packaging errors the platform would hit
pytest -q               # 26 tests, incl. 12 against the deployed app on a real socket
vercel --prod
```

`uv build --wheel` is first because two packaging faults would otherwise have failed the deploy:
`dependencies` was empty (httpx and fastapi are runtime needs, and Vercel reads
`pyproject.toml`), and hatchling could not determine what to ship since the package lives in
`src/`. Both reproduce locally in two seconds.

## Rollback

```bash
vercel rollback                                     # previous production deployment
vercel ls mcpgantlet && vercel promote <url>       # or a specific one
```

Stateless, no database, no migrations.
