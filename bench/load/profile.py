#!/usr/bin/env python3
"""Ramp concurrency against an MCP endpoint and report where it breaks.

Usage:
  python bench/load/profile.py <url> [--steps 1,5,10,25,50,100] [--requests 200]
                              [--i-have-permission]

Refuses a non-local host without --i-have-permission. Load testing an endpoint you do not
control is abuse regardless of intent, and a tool that makes it frictionless invites it.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mcpgauntlet.load import find_cliffs, run_step

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def arg(flag: str, default: str) -> str:
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


async def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(2)
    url = args[0]

    host = urlparse(url).hostname or ""
    if host not in LOCAL_HOSTS and "--i-have-permission" not in sys.argv:
        print(f"refusing to load-test {host}: pass --i-have-permission if you control it.")
        print("Load testing an endpoint you do not control is abuse regardless of intent.")
        sys.exit(3)

    steps = [int(s) for s in arg("--steps", "1,5,10,25,50,100").split(",")]
    per_step = int(arg("--requests", "200"))

    # Calibrate the harness against a trivial local endpoint FIRST. Without this the tool
    # reports its own client-side contention as a server cliff — which it did, at 769x p99
    # degradation, until a worker-count control disproved it. See
    # bench/load/results/harness-limit-2026-08-21.md.
    ceiling: dict[int, float] = {}
    if "--no-calibrate" not in sys.argv:
        print("calibrating harness ceiling against a trivial endpoint…")
        ceiling = await _calibrate(steps, per_step)
        print("  " + "  ".join(f"c{c}={r:.0f}rps" for c, r in sorted(ceiling.items())))
        print()

    print(f"{url}")
    print(f"ramp {steps}, {per_step} requests per step\n")
    print(f"{'conc':>5}{'p50':>9}{'p95':>9}{'p99':>10}{'mean':>9}{'rps':>9}{'errors':>9}")
    print("-" * 60)

    results = []
    for c in steps:
        r = await run_step(url, concurrency=c, requests=per_step)
        results.append(r)
        print(
            f"{c:>5}{r.p50:>9.1f}{r.p95:>9.1f}{r.p99:>10.1f}"
            f"{r.mean:>9.1f}{r.throughput_rps:>9.0f}{r.failed:>9}"
        )
        # Brief pause so one step's queue does not become the next step's baseline.
        await asyncio.sleep(1.0)

    cliffs = find_cliffs(results, harness_ceiling=ceiling or None)
    print()
    if cliffs:
        print("cliffs found:")
        for c in cliffs:
            print(f"  concurrency {c.concurrency}  {c.kind}")
            print(f"    {c.detail}")
    else:
        print("no cliff found across the tested range — the server degraded gracefully.")
        print("That is a real result: report it rather than escalating until something breaks.")

    out = Path(__file__).parent / "results" / "profile.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "url": url,
                "requests_per_step": per_step,
                "steps": [
                    {
                        "concurrency": r.concurrency,
                        "p50_ms": round(r.p50, 2),
                        "p95_ms": round(r.p95, 2),
                        "p99_ms": round(r.p99, 2),
                        "mean_ms": round(r.mean, 2),
                        "throughput_rps": round(r.throughput_rps, 1),
                        "succeeded": r.succeeded,
                        "failed": r.failed,
                        "errors": r.errors,
                    }
                    for r in results
                ],
                "harness_ceiling_rps": {str(k): round(v, 1) for k, v in ceiling.items()},
                "cliffs": [
                    {"concurrency": c.concurrency, "kind": c.kind, "detail": c.detail}
                    for c in cliffs
                ],
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nraw results → {out}")


async def _calibrate(steps: list[int], per_step: int) -> dict[str, float]:
    """Measure this harness's own maximum throughput.

    Serves a trivial endpoint in-process — no JSON parsing, no routing beyond a match —
    so whatever it measures is the client and the loopback, not application work.
    """
    import threading

    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI()

    @app.post("/mcp")
    async def _trivial() -> JSONResponse:
        return JSONResponse({"jsonrpc": "2.0", "id": 1, "result": {}})

    port = 8499
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(120):
        if server.started:
            break
        await asyncio.sleep(0.05)

    out: dict[int, float] = {}
    for c in steps:
        r = await run_step(f"http://127.0.0.1:{port}/mcp", concurrency=c, requests=per_step)
        out[c] = r.throughput_rps
        await asyncio.sleep(0.2)

    server.should_exit = True
    thread.join(timeout=5)
    return out


if __name__ == "__main__":
    asyncio.run(main())
