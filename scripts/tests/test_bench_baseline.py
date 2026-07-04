"""Tests for bench_baseline.py — the perf/heap bench parse + gate logic.

Exercises the pure functions ``run.py bench`` orchestrates: parsing a
worker's stdout, applying the heap/CPU tolerance policy, and serializing
a baseline that round-trips through ``tomllib``.  No unix-port binary is
spawned — the worker's output is synthesized as text.
"""

import tomllib

import pytest
from bench_baseline import (
    CPU_TOLERANCE_FLOOR_US,
    HEAP_SLACK_BYTES,
    BenchOutputError,
    BenchResult,
    compare_runtime,
    parse_bench_output,
    serialize_baseline,
)


def _worker_output(*bench_lines: str, failed: int = 0) -> str:
    """Wrap synthetic ``BENCH`` lines with the worker's framing."""
    body = "\n".join(("# runtime=micropython benches=1", *bench_lines))
    return f"{body}\nBENCH-DONE count={len(bench_lines)} failed={failed}"


_ONE_BENCH = (
    "BENCH id=x heap_churn_bytes=100.0 cpu_us=50.0 cpu_us_min=48 "
    "cpu_us_max=52 repeats=7 cpu_batch=2000 heap_batch=256 payload_bytes=64"
)


class TestParseBenchOutput:
    def test_parses_fields_and_ignores_comments(self):
        results = parse_bench_output(_worker_output(_ONE_BENCH))
        assert set(results) == {"x"}
        result = results["x"]
        assert result.heap_churn_bytes == 100.0
        assert result.cpu_us == 50.0
        assert result.payload_bytes == 64

    def test_bench_error_line_raises(self):
        text = "BENCH-ERROR id=y msg=boom\nBENCH-DONE count=1 failed=1"
        with pytest.raises(BenchOutputError, match="boom"):
            parse_bench_output(text)

    def test_done_reporting_failures_raises(self):
        with pytest.raises(BenchOutputError, match="failed"):
            parse_bench_output(_worker_output(_ONE_BENCH, failed=2))

    def test_missing_done_line_raises(self):
        # A crash mid-run leaves BENCH lines but no BENCH-DONE.
        with pytest.raises(BenchOutputError, match="no BENCH-DONE"):
            parse_bench_output(_ONE_BENCH)


class TestCompareRuntime:
    def test_within_band_is_ok(self):
        measured = parse_bench_output(_worker_output(_ONE_BENCH))
        findings = compare_runtime(
            measured, {"x": {"heap_churn_bytes": 90.0, "cpu_us": 40.0}},
        )
        assert findings[0].status == "ok"
        assert not findings[0].is_regression

    def test_heap_over_slack_is_regression(self):
        measured = parse_bench_output(_worker_output(_ONE_BENCH))
        # measured heap 100 vs baseline 64: 100 > 64 + 16 slack.
        findings = compare_runtime(
            measured,
            {"x": {"heap_churn_bytes": 64.0, "cpu_us": 50.0}},
        )
        assert findings[0].is_regression
        assert "heap" in findings[0].reasons[0]

    def test_heap_exactly_at_slack_edge_is_ok(self):
        measured = parse_bench_output(_worker_output(_ONE_BENCH))
        # baseline + slack == measured exactly: not a regression (> is strict).
        base_heap = 100.0 - HEAP_SLACK_BYTES
        findings = compare_runtime(
            measured, {"x": {"heap_churn_bytes": base_heap, "cpu_us": 50.0}},
        )
        assert findings[0].status == "ok"

    def test_cpu_over_band_is_regression(self):
        measured = parse_bench_output(_worker_output(_ONE_BENCH))
        # measured cpu 50 vs baseline 10: ceiling max(20, 15) = 20.
        findings = compare_runtime(
            measured, {"x": {"heap_churn_bytes": 100.0, "cpu_us": 10.0}},
        )
        assert findings[0].is_regression
        assert "cpu" in findings[0].reasons[-1]

    def test_tiny_cpu_jitter_within_floor_is_ok(self):
        # A sub-microsecond op that doubles is still within the absolute
        # floor, so the multiplicative band alone doesn't fail it.
        line = _ONE_BENCH.replace("cpu_us=50.0", "cpu_us=1.0")
        measured = parse_bench_output(_worker_output(line))
        findings = compare_runtime(
            measured, {"x": {"heap_churn_bytes": 100.0, "cpu_us": 0.4}},
        )
        assert findings[0].status == "ok"
        assert 1.0 <= 0.4 + CPU_TOLERANCE_FLOOR_US

    def test_measured_without_baseline_is_new(self):
        measured = parse_bench_output(_worker_output(_ONE_BENCH))
        findings = compare_runtime(measured, {})
        assert findings[0].status == "new"
        assert not findings[0].is_regression

    def test_baseline_without_measurement_is_missing(self):
        findings = compare_runtime(
            {}, {"gone": {"heap_churn_bytes": 1.0, "cpu_us": 1.0}},
        )
        assert findings[0].status == "missing"
        assert findings[0].measured is None
        assert not findings[0].is_regression


class TestSerializeBaseline:
    def test_round_trips_through_tomllib(self):
        results = {
            "micropython": {
                "x": BenchResult("x", 64.0, 7.0, 6.0, 8.0, 0),
                "y": BenchResult("y", 448.0, 9.5, 9.0, 10.0, 64),
            },
        }
        text = serialize_baseline(results, "2026-07-04")
        doc = tomllib.loads(text)
        assert doc["meta"]["updated"] == "2026-07-04"
        assert doc["micropython"]["x"]["heap_churn_bytes"] == 64
        assert doc["micropython"]["y"]["payload_bytes"] == 64

    def test_output_is_deterministic(self):
        results = {"micropython": {"x": BenchResult("x", 1.0, 2.0, 1.0, 3.0, 0)}}
        first = serialize_baseline(results, "2026-07-04")
        second = serialize_baseline(results, "2026-07-04")
        assert first == second
