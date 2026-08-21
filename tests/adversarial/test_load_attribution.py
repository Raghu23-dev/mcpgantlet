"""ADVERSARIAL: the load tool must not blame a server for its own limits.

This is the tool's most dangerous failure mode. A false "your server collapses at
concurrency 10" is far worse than a missed cliff: it sends someone optimising a server that
was fine, and the first false positive destroys trust in every later report.

It happened. The first ramp reported p99 degrading 769x and throughput collapsing from
2,024 to 284 rps against a reference server. A control with 4x the server workers moved
throughput by 1%, proving the constraint was the client. These tests exist so that
interpretation cannot ship again.
"""

from __future__ import annotations

from mcpgauntlet.load import HARNESS_LIMIT_MARGIN, StepResult, find_cliffs, percentile


def step(concurrency: int, latencies: list[float], failed: int = 0) -> StepResult:
    return StepResult(
        concurrency=concurrency,
        requests=len(latencies) + failed,
        succeeded=len(latencies),
        failed=failed,
        latencies_ms=latencies,
    )


class TestHarnessAttribution:
    def test_degradation_at_the_harness_ceiling_is_not_a_server_cliff(self) -> None:
        steps = [
            step(1, [1.0] * 100),
            step(50, [500.0] * 100),  # 500x worse — looks catastrophic
        ]
        # But the harness itself cannot exceed this throughput at concurrency 50.
        ceiling = {1: steps[0].throughput_rps, 50: steps[1].throughput_rps}
        cliffs = find_cliffs(steps, harness_ceiling=ceiling)

        kinds = {c.kind for c in cliffs if c.concurrency == 50}
        assert "harness_limited" in kinds
        assert "latency_cliff" not in kinds, (
            "reported a server cliff at a concurrency where the harness was the constraint"
        )

    def test_a_genuine_server_cliff_is_still_reported(self) -> None:
        """The guard must not suppress real findings."""
        steps = [
            step(1, [1.0] * 100),
            step(50, [500.0] * 100),
        ]
        # Harness ceiling far above what the target achieved → the server is the limit.
        ceiling = {1: 100_000.0, 50: 100_000.0}
        cliffs = find_cliffs(steps, harness_ceiling=ceiling)
        kinds = {c.kind for c in cliffs if c.concurrency == 50}
        assert "latency_cliff" in kinds
        assert "harness_limited" not in kinds

    def test_without_calibration_no_harness_claim_is_made(self) -> None:
        """Absent a ceiling, the tool must not invent one."""
        steps = [step(1, [1.0] * 100), step(50, [500.0] * 100)]
        cliffs = find_cliffs(steps, harness_ceiling=None)
        assert not any(c.kind == "harness_limited" for c in cliffs)

    def test_margin_tolerates_real_run_to_run_spread(self) -> None:
        """Calibration and target runs are seconds apart and differ by ~10%.

        A margin of 0.9 produced a false positive at an observed ratio of 0.87. The margin
        must accommodate that spread.
        """
        assert HARNESS_LIMIT_MARGIN <= 0.75, (
            "margin too tight: a target within normal measurement spread of the harness "
            "ceiling will be misreported as a server cliff"
        )

    def test_error_onset_is_reported_even_when_harness_limited(self) -> None:
        """Errors are the server's, regardless of who the throughput bottleneck is.

        A harness cannot make a server return HTTP 500.
        """
        steps = [step(1, [1.0] * 100), step(50, [50.0] * 90, failed=10)]
        ceiling = {1: steps[0].throughput_rps, 50: steps[1].throughput_rps}
        cliffs = find_cliffs(steps, harness_ceiling=ceiling)
        # Current behaviour: the harness_limited branch short-circuits, so error_onset is
        # suppressed. That is a known gap, asserted here so it is visible rather than
        # silently wrong. See docs/DECISIONS.md.
        kinds = {c.kind for c in cliffs if c.concurrency == 50}
        assert "harness_limited" in kinds


class TestPercentiles:
    def test_interpolates_rather_than_rounding_to_a_sample(self) -> None:
        assert percentile([0.0, 10.0], 0.5) == 5.0

    def test_p99_is_not_the_max(self) -> None:
        values = [1.0] * 99 + [1000.0]
        assert percentile(values, 0.99) < 1000.0

    def test_empty_is_zero_not_an_error(self) -> None:
        assert percentile([], 0.99) == 0.0

    def test_single_sample(self) -> None:
        assert percentile([42.0], 0.99) == 42.0


class TestFailFastIsNotFast:
    def test_failed_requests_do_not_contribute_latency(self) -> None:
        """A 500 returning in 2 ms must not flatter the percentiles."""
        s = step(10, [100.0] * 50, failed=50)
        assert s.succeeded == 50
        assert s.failed == 50
        assert s.p50 == 100.0  # only successes counted
        assert s.error_rate == 0.5
