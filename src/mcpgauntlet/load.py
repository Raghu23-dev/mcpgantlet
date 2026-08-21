"""Load profiling for MCP servers.

Ramps concurrency and reports latency percentiles per step, looking for the point where a
server stops degrading gracefully and starts falling over.

WHY PERCENTILES AND NOT AVERAGES

A mean hides the failure. A server that answers 95 requests in 20 ms and 5 requests in
4 seconds has a mean of 220 ms, which looks fine and is not. p99 is where a server's
problems actually live, so the mean is reported only as context.

WHY A RAMP AND NOT A FIXED LOAD

The interesting number is not throughput at some arbitrary concurrency — it is the
concurrency at which behaviour changes. A fixed load tells you whether a server survives
that load. A ramp tells you where its cliff is, which is the thing you need before
deploying.

WHAT THIS DELIBERATELY WILL NOT DO

It refuses to run against a host it was not explicitly told to target, and the CLI
requires an acknowledgement flag for any non-local host. Load testing someone else's
endpoint without consent is abuse regardless of intent, and a tool that makes it
convenient is a tool that invites it.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from .spec import PROTOCOL_VERSION


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolated percentile.

    Interpolated rather than nearest-rank because at 200 samples the difference between
    the 198th and 199th value is real, and rounding to one of them reports a number that
    was never measured.
    """
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


@dataclass(slots=True)
class StepResult:
    concurrency: int
    requests: int
    succeeded: int
    failed: int
    latencies_ms: list[float] = field(default_factory=list)
    errors: dict[str, int] = field(default_factory=dict)

    @property
    def p50(self) -> float:
        return percentile(self.latencies_ms, 0.50)

    @property
    def p95(self) -> float:
        return percentile(self.latencies_ms, 0.95)

    @property
    def p99(self) -> float:
        return percentile(self.latencies_ms, 0.99)

    @property
    def mean(self) -> float:
        return statistics.fmean(self.latencies_ms) if self.latencies_ms else 0.0

    @property
    def error_rate(self) -> float:
        return self.failed / self.requests if self.requests else 0.0

    @property
    def throughput_rps(self) -> float:
        """Successful requests per second, derived from observed latency.

        Deliberately computed from measured latency rather than wall-clock over the whole
        step: wall-clock includes ramp-up and teardown, which understates throughput at
        low concurrency and flatters it at high.
        """
        if not self.latencies_ms:
            return 0.0
        mean_s = self.mean / 1000.0
        return self.concurrency / mean_s if mean_s > 0 else 0.0


def _request_body(method: str = "tools/list") -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                "io.modelcontextprotocol/clientInfo": {"name": "mcpgauntlet", "version": "0.1.0"},
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        },
    }


def _headers(method: str = "tools/list") -> dict[str, str]:
    return {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": PROTOCOL_VERSION,
        "mcp-method": method,
    }


async def _one(client: httpx.AsyncClient, url: str, method: str, result: StepResult) -> None:
    start = time.perf_counter()
    try:
        response = await client.post(url, headers=_headers(method), json=_request_body(method))
        elapsed = (time.perf_counter() - start) * 1000.0
        if response.status_code < 400:
            result.succeeded += 1
            # Only successful requests contribute latency. A 500 that returns in 2 ms
            # would otherwise flatter the percentiles — a fast failure is not fast.
            result.latencies_ms.append(elapsed)
        else:
            result.failed += 1
            key = f"http_{response.status_code}"
            result.errors[key] = result.errors.get(key, 0) + 1
    except httpx.HTTPError as exc:
        result.failed += 1
        key = type(exc).__name__
        result.errors[key] = result.errors.get(key, 0) + 1


async def run_step(
    url: str,
    concurrency: int,
    requests: int,
    method: str = "tools/list",
    timeout: float = 30.0,
) -> StepResult:
    """Fire `requests` requests with at most `concurrency` in flight."""
    result = StepResult(concurrency=concurrency, requests=requests, succeeded=0, failed=0)
    gate = asyncio.Semaphore(concurrency)

    limits = httpx.Limits(max_connections=concurrency + 10, max_keepalive_connections=concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:

        async def guarded() -> None:
            async with gate:
                await _one(client, url, method, result)

        await asyncio.gather(*(guarded() for _ in range(requests)))

    return result


# A target throughput within this fraction of the harness ceiling cannot be attributed to
# the server: the client is the constraint.
#
# CALIBRATED, not chosen. At 0.9 a measured run sat at ratio 0.87 against its own ceiling
# and was reported as a server cliff — a false positive, since 13% is well inside the
# run-to-run spread observed between the calibration pass and the target pass (the two
# runs are seconds apart on a shared machine, and the same concurrency measured 977 rps
# then 1068 rps, a 9% swing with nothing changed).
#
# 0.7 accommodates that spread. The cost is under-reporting a genuine server cliff whose
# throughput lands within 30% of the harness ceiling — accepted deliberately, because for
# this tool a false "your server has a cliff" is far more damaging than a missed one: the
# first destroys trust in every later report.
HARNESS_LIMIT_MARGIN = 0.7


@dataclass(slots=True)
class Cliff:
    """A point where behaviour changed qualitatively, not just gradually."""

    concurrency: int
    kind: str
    detail: str


def find_cliffs(
    steps: list[StepResult],
    degradation_factor: float = 5.0,
    harness_ceiling: dict[int, float] | None = None,
) -> list[Cliff]:
    """Identify where a server stops degrading gracefully.

    Three distinct kinds, because they have different causes and different fixes:

    - `latency_cliff`: p99 jumps by more than `degradation_factor` against the baseline
      step. Usually queueing — the server is accepting work it cannot service.
    - `error_onset`: the first step to return errors at all. More serious than slow,
      because a caller gets nothing rather than something late.
    - `throughput_collapse`: throughput falls while concurrency rises. The signature of
      contention: adding load makes the server slower in aggregate, not just per request.
    """
    cliffs: list[Cliff] = []
    if not steps:
        return cliffs

    baseline = steps[0]

    def harness_limited(step: StepResult) -> bool:
        """True when this step's throughput is at the harness's own ceiling.

        Without this check the tool reports its own client-side contention as a server
        cliff — which it did, at 769x p99 degradation, until a worker-count control
        disproved it.
        """
        if harness_ceiling is None:
            return False
        ceiling = harness_ceiling.get(step.concurrency)
        if ceiling is None or ceiling <= 0:
            return False
        return step.throughput_rps >= ceiling * HARNESS_LIMIT_MARGIN

    base_p99 = baseline.p99 or 1e-9
    seen_error = False
    prev_throughput = 0.0

    for step in steps:
        if harness_limited(step):
            cliffs.append(
                Cliff(
                    step.concurrency,
                    "harness_limited",
                    f"throughput {step.throughput_rps:.0f} rps is at this harness's own "
                    f"ceiling of {(harness_ceiling or {}).get(step.concurrency, 0.0):.0f} rps. "
                    "Degradation at or above this concurrency cannot be attributed to the "
                    "server — move the client to a separate host to measure it.",
                )
            )
            # Attributing anything further to the server would be unsound.
            continue

        if step.p99 > base_p99 * degradation_factor:
            cliffs.append(
                Cliff(
                    step.concurrency,
                    "latency_cliff",
                    f"p99 {step.p99:.1f} ms is {step.p99 / base_p99:.1f}x the "
                    f"concurrency-{baseline.concurrency} baseline ({base_p99:.1f} ms)",
                )
            )
        if step.failed > 0 and not seen_error:
            seen_error = True
            errs = ", ".join(f"{k}={v}" for k, v in sorted(step.errors.items()))
            cliffs.append(
                Cliff(
                    step.concurrency,
                    "error_onset",
                    f"{step.failed}/{step.requests} failed ({step.error_rate:.1%}): {errs}",
                )
            )
        if prev_throughput > 0 and step.throughput_rps < prev_throughput * 0.8:
            cliffs.append(
                Cliff(
                    step.concurrency,
                    "throughput_collapse",
                    f"throughput fell to {step.throughput_rps:.0f} rps from "
                    f"{prev_throughput:.0f} rps while concurrency rose",
                )
            )
        prev_throughput = max(prev_throughput, step.throughput_rps)

    # One cliff per concurrency per kind; a repeated report adds noise, not information.
    seen: set[tuple[int, str]] = set()
    unique: list[Cliff] = []
    for c in cliffs:
        key = (c.concurrency, c.kind)
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique
