"""Live instance of the mcpgauntlet reference server, plus a self-audit.

WHY THIS AND NOT A HOSTED AUDITOR

`docs/NON-GOALS.md` rules out "a hosted service or dashboard", written before any code
existed, on the grounds that the value is "a citable result in CI, not a chart". Standing up
auditor-as-a-service would contradict that commitment, and a pre-registered non-goal is not
something to quietly reverse once it becomes convenient.

It would also be irresponsible in a way the same document names: an auditor that accepts an
arbitrary URL from an anonymous visitor is a request-forgery gadget pointed at whatever a
stranger types, and "every probe is read-only" does not make sending them somewhere on
someone else's behalf acceptable.

So what is deployed is the thing that can be deployed honestly:

1. **The reference server itself**, strictly conformant to MCP 2026-07-28, at `/mcp`. Anyone
   can point their own copy of the auditor at it, or read it with curl. It is a fixed target
   for testing an MCP client, which is genuinely useful and does not exist elsewhere.

2. **A self-audit** at `/audit/self`, which runs all 10 probes against this instance over real
   HTTP and reports the result. That is criterion 3 — zero false positives against a
   conforming server — as evidence a stranger can check rather than a claim in a README.

3. **The rule set** at `/spec/rules`, each rule with the clause it cites.

The auditor is not exposed against arbitrary targets. That stays a CLI, where the person
running it is the person accountable for pointing it somewhere.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "src"))

from mcpgauntlet.conformance import Auditor, Verdict
from mcpgauntlet.spec import PROTOCOL_VERSION, RULES
from tests.fixtures.reference_server import create_reference_app

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
)
log = logging.getLogger("mcpgauntlet")

VERSION = "0.1.0"

app = FastAPI(title="mcpgauntlet reference server", version=VERSION, docs_url="/docs")

#: Mounted verbatim from tests/fixtures. The deployed server IS the fixture the test suite
#: asserts zero findings against — not a reimplementation that could drift from it.
_reference = create_reference_app()
app.mount("/ref", _reference)

_RATE_WINDOW_S = 60
_RATE_MAX = 120
_hits: dict[str, deque[float]] = {}


def _rate_limited(key: str) -> bool:
    now = time.time()
    window = _hits.setdefault(key, deque())
    while window and now - window[0] > _RATE_WINDOW_S:
        window.popleft()
    if len(window) >= _RATE_MAX:
        return True
    window.append(now)
    return False


@app.middleware("http")
async def guard(request: Request, call_next: Any) -> Any:
    start = time.perf_counter()
    who = request.client.host if request.client else "-"
    if _rate_limited(who):
        return JSONResponse({"error": "rate_limited", "limit": f"{_RATE_MAX}/60s"}, 429)
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled")
        return JSONResponse({"error": "internal_error"}, 500)
    ms = (time.perf_counter() - start) * 1000
    log.info("%s %s -> %s in %.1fms", request.method, request.url.path, response.status_code, ms)
    response.headers["X-Response-Time-Ms"] = f"{ms:.1f}"
    response.headers["X-Mcpgauntlet-Version"] = VERSION
    return response


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": VERSION,
        "protocol_version": PROTOCOL_VERSION,
        "rules": len(RULES),
        "must_rules": sum(1 for r in RULES if r.severity == "MUST"),
        "mcp_endpoint": "/mcp",
        "commit": os.environ.get("VERCEL_GIT_COMMIT_SHA", "local")[:7],
    }


@app.get("/spec/rules")
def rules() -> dict[str, Any]:
    """Every rule with the clause it cites.

    Criterion 1: a probe that cannot cite a clause is an opinion, so each rule carries the
    specification text it comes from. Published here so a reader can check the citation
    against the spec rather than take the tool's word for it.
    """
    return {
        "protocol_version": PROTOCOL_VERSION,
        "count": len(RULES),
        "rules": [
            {
                "id": r.id,
                "severity": str(r.severity),
                "description": r.description,
                "clause": r.clause,
                "rationale": r.rationale,
            }
            for r in RULES
        ],
    }


def _run_audit(target: str) -> list[Any]:
    with Auditor(target) as auditor:
        return auditor.run()


@app.get("/audit/self")
async def audit_self(request: Request) -> dict[str, Any]:
    """Run all 10 probes against this instance, over real HTTP.

    This is criterion 3 as checkable evidence: **zero findings against a strictly conforming
    server**. A conformance checker that flags a correct server is worse than no checker,
    because the first false positive teaches its user to ignore every later report.

    Runs against the deployment's own public URL, so the probes traverse the real network path
    including the platform's proxy — not an in-process shortcut that could pass while the
    deployed server fails.
    """
    base = str(request.base_url).rstrip("/")
    target = f"{base}/mcp"

    # OFFLOADED TO A THREAD, and this is not a style preference. `Auditor` is a synchronous
    # httpx client, so calling it directly inside an async endpoint blocks the event loop —
    # the same loop that has to serve the probes it is issuing. The first version deadlocked
    # and timed out against itself: a server auditing itself over its own HTTP interface is
    # the one case where blocking the loop is self-inflicted rather than merely slow.
    findings = await run_in_threadpool(_run_audit, target)

    violations = [f for f in findings if f.is_violation]
    inconclusive = [f for f in findings if f.verdict == Verdict.INCONCLUSIVE]

    return {
        "target": target,
        "protocol_version": PROTOCOL_VERSION,
        "probes_run": len(findings),
        "violations": len(violations),
        "inconclusive": len(inconclusive),
        "verdict": (
            "CONFORMANT — 0 violations, which is criterion 3: no false positives against a "
            "server built strictly to spec"
            if not violations
            else "NON-CONFORMANT — see findings"
        ),
        "findings": [
            {
                "rule": f.rule.id,
                "severity": str(f.rule.severity),
                "description": f.rule.description,
                "verdict": str(f.verdict),
                "observed": f.observed,
                "detail": f.detail,
                "clause": f.rule.clause,
            }
            for f in findings
        ],
    }


@app.post("/mcp")
async def mcp_post(request: Request) -> Any:
    """The reference server's MCP endpoint, at the conventional path.

    Delegates to the mounted fixture rather than reimplementing it, so the deployed transport
    behaviour is exactly what the test suite audits.
    """
    return await _forward(request, "POST")


@app.get("/mcp")
async def mcp_get(request: Request) -> Any:
    return await _forward(request, "GET")


@app.delete("/mcp")
async def mcp_delete(request: Request) -> Any:
    return await _forward(request, "DELETE")


async def _forward(request: Request, method: str) -> Any:
    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in ("host", "content-length")
    }

    transport = httpx.ASGITransport(app=_reference)
    async with httpx.AsyncClient(transport=transport, base_url="http://ref") as client:
        upstream = await client.request(method, "/mcp", content=body, headers=headers, timeout=15.0)

    passthrough = {
        k: v
        for k, v in upstream.headers.items()
        if k.lower() in ("mcp-protocol-version", "allow", "www-authenticate")
    }

    # AN EMPTY BODY MUST STAY EMPTY. The first version wrapped every response in JSONResponse,
    # which turned the reference server's bodiless 202 into the four bytes "null" — and the
    # self-audit immediately failed `notification-202` with "202 with a body".
    #
    # The fixture was correct and the forwarder broke it, which is exactly the class of bug a
    # transparent proxy introduces: the thing being audited was no longer the thing that had
    # been written. Worth keeping as a comment because the auditor caught a real violation in
    # its own deployment on the first run, which is the best evidence it works that exists.
    if not upstream.content:
        return Response(status_code=upstream.status_code, headers=passthrough)

    return JSONResponse(
        content=_safe(upstream),
        status_code=upstream.status_code,
        headers=passthrough,
    )


def _safe(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:400]} if response.text else None


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    must = sum(1 for r in RULES if r.severity == "MUST")
    should = len(RULES) - must
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>mcpgauntlet — a conformant MCP server to test against</title>
<style>
 :root {{ color-scheme: dark }}
 body {{ background:#0b0d10; color:#e7e9ee; font:16px/1.65 ui-monospace,SFMono-Regular,Menlo,monospace;
        margin:0; padding:2.5rem 1.25rem }}
 main {{ max-width:62rem; margin:0 auto }}
 h1 {{ font-size:1.5rem; margin:0 0 .25rem }}
 h2 {{ font-size:1.05rem; margin:2.25rem 0 .6rem; color:#8fb6ff }}
 p.sub {{ color:#788092; margin:0 0 2rem }}
 table {{ border-collapse:collapse; width:100%; margin:.5rem 0 1rem; font-size:.875rem }}
 th,td {{ text-align:left; padding:.4rem .7rem; border-bottom:1px solid #1c212b }}
 th {{ color:#788092; font-weight:400 }}
 code {{ background:#151a21; padding:.1rem .35rem; border-radius:3px; font-size:.875em }}
 pre {{ background:#151a21; padding:.85rem 1rem; border-radius:6px; overflow-x:auto;
        font-size:.8125rem; border:1px solid #1c212b }}
 a {{ color:#8fb6ff }}
 .n {{ color:#788092 }}
 .warn {{ border-left:2px solid #d4a24c; padding-left:1rem; color:#cfd3dc }}
</style></head><body><main>
<h1>mcpgauntlet</h1>
<p class="sub">A strictly conformant MCP {PROTOCOL_VERSION} server, live, to test your client
against. v{VERSION} &middot; <a href="/docs">API docs</a> &middot; <a href="/health">health</a></p>

<h2>Zero false positives, provable in one request</h2>
<pre>curl {{HOST}}/audit/self</pre>
<p>Runs all {len(RULES)} probes against this instance over real HTTP and reports the result.
Zero violations is <strong>criterion 3</strong> &mdash; a checker that flags a correct server is
worse than no checker, because the first false positive teaches its user to ignore every later
report.</p>

<h2>A fixed target for your MCP client</h2>
<pre>curl -X POST {{HOST}}/mcp \\
  -H 'content-type: application/json' \\
  -H 'accept: application/json, text/event-stream' \\
  -H 'mcp-protocol-version: {PROTOCOL_VERSION}' \\
  -H 'mcp-method: tools/list' \\
  -d '{{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{{}}}}'</pre>
<p>Try breaking the rules and watch it refuse correctly:</p>
<pre>curl -X GET {{HOST}}/mcp            <span class="n"># 405 — the GET stream is gone in {PROTOCOL_VERSION}</span>
curl -X POST {{HOST}}/mcp -d '{{}}'   <span class="n"># header/body disagreement → -32020</span></pre>

<h2>The rules, each with its clause</h2>
<pre>curl {{HOST}}/spec/rules</pre>
<p>{must} MUST and {should} SHOULD rules. Every one cites the specification text it comes from
&mdash; a probe that cannot cite a clause is an opinion.</p>

<h2 class="warn">There is deliberately no hosted auditor here</h2>
<p class="warn"><code>docs/NON-GOALS.md</code> ruled out a hosted service before any code was
written, on the grounds that the value is a citable result in CI rather than a chart. Reversing
that once it became convenient would make the document worthless. An auditor accepting a URL
from an anonymous visitor is also a request-forgery gadget aimed at whatever a stranger types,
and read-only probes do not make sending them on someone else&rsquo;s behalf acceptable.
Auditing arbitrary targets stays a CLI, where whoever runs it is accountable for where it
points.</p>

<h2>Audit your own server</h2>
<pre>pipx install git+https://github.com/Raghu23-dev/mcpgauntlet
mcpgauntlet audit http://localhost:8000/mcp</pre>
</main>
<script>document.body.innerHTML = document.body.innerHTML.replaceAll('{{HOST}}', location.origin);</script>
</body></html>"""
