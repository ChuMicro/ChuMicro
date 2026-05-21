"""Tests for result_parser: structured harness output parsing."""

from __future__ import annotations

from chumicro_pytest_device import result_parser
from chumicro_pytest_device.result_parser import parse_output


class TestParsePassFail:
    """Tests for PASS and FAIL line parsing."""

    def test_pass_line(self) -> None:
        """A PASS line should produce a TestResult with status='PASS'."""
        result = parse_output("PASS test_one (0.003s)")
        assert len(result.tests) == 1
        assert result.tests[0] == result_parser.TestResult(
            name="test_one", status="PASS", duration=0.003
        )

    def test_fail_line(self) -> None:
        """A FAIL line should produce a TestResult with status='FAIL'."""
        result = parse_output("FAIL test_broken (0.012s)")
        assert len(result.tests) == 1
        assert result.tests[0].status == "FAIL"
        assert result.tests[0].name == "test_broken"
        assert result.tests[0].duration == 0.012

    def test_pass_with_heap_delta(self) -> None:
        """A PASS line with heap info should populate heap_delta."""
        result = parse_output("PASS test_alloc (0.005s, heap +128)")
        assert result.tests[0].heap_delta == 128

    def test_fail_with_negative_heap_delta(self) -> None:
        """A FAIL line with negative heap delta should parse correctly."""
        result = parse_output("FAIL test_leak (0.010s, heap -256)")
        assert result.tests[0].heap_delta == -256

    def test_pass_without_heap(self) -> None:
        """A PASS line without heap data should leave heap_delta as None."""
        result = parse_output("PASS test_simple (0.001s)")
        assert result.tests[0].heap_delta is None


class TestParseSkip:
    """Tests for SKIP line parsing."""

    def test_skip_with_reason(self) -> None:
        """A SKIP line with a reason should populate the message field."""
        result = parse_output("SKIP test_wifi (no network)")
        assert len(result.tests) == 1
        assert result.tests[0] == result_parser.TestResult(
            name="test_wifi", status="SKIP", message="no network"
        )

    def test_skip_without_reason(self) -> None:
        """A SKIP line without a reason should leave message empty."""
        result = parse_output("SKIP test_optional")
        assert result.tests[0].status == "SKIP"
        assert result.tests[0].message == ""


class TestParseSummary:
    """Tests for SUMMARY line parsing."""

    def test_summary_line(self) -> None:
        """A well-formed SUMMARY line should populate the summary field."""
        result = parse_output("SUMMARY total=5 failed=1 time=0.123s")
        assert result.summary == result_parser.SummaryResult(total=5, failed=1, duration=0.123)

    def test_summary_all_pass(self) -> None:
        """A SUMMARY with zero failures should parse correctly."""
        result = parse_output("SUMMARY total=3 failed=0 time=0.042s")
        assert result.summary is not None
        assert result.summary.failed == 0


class TestParseHeap:
    """Tests for HEAP line parsing."""

    def test_heap_line_positive_delta(self) -> None:
        """A HEAP line with positive delta should parse correctly."""
        result = parse_output("HEAP 50000 bytes free (delta +0 bytes)")
        assert result.heap == result_parser.HeapResult(bytes_free=50000, delta=0)

    def test_heap_line_negative_delta(self) -> None:
        """A HEAP line with negative delta should parse correctly."""
        result = parse_output("HEAP 48000 bytes free (delta -2000 bytes)")
        assert result.heap == result_parser.HeapResult(bytes_free=48000, delta=-2000)


class TestParseMixedOutput:
    """Tests for realistic mixed output containing noise and harness lines."""

    def test_full_harness_output(self) -> None:
        """A complete harness run with multiple tests should parse fully."""
        raw = (
            "== libraries/timing/functional_tests/test_heartbeat_ticks.py ==\n"
            "PASS test_ticks_progress (0.064s, heap +0)\n"
            "PASS test_ticks_diff (0.002s, heap +32)\n"
            "HEAP 50000 bytes free (delta +32 bytes)\n"
            "SUMMARY total=2 failed=0 time=0.066s\n"
        )
        result = parse_output(raw)
        assert len(result.tests) == 2
        assert result.tests[0].status == "PASS"
        assert result.tests[1].name == "test_ticks_diff"
        assert result.heap is not None
        assert result.heap.bytes_free == 50000
        assert result.summary is not None
        assert result.summary.total == 2

    def test_noise_lines_are_ignored(self) -> None:
        """Non-harness lines (boot messages, prints) should be silently skipped."""
        raw = (
            "MicroPython v1.28.0\n"
            ">>> \n"
            "PASS test_ok (0.001s)\n"
            "some debug output\n"
            "SUMMARY total=1 failed=0 time=0.001s\n"
        )
        result = parse_output(raw)
        assert len(result.tests) == 1
        assert result.summary is not None

    def test_empty_output(self) -> None:
        """Empty output should return an empty RunResult."""
        result = parse_output("")
        assert result.tests == []
        assert result.heap is None
        assert result.summary is None

    def test_raw_output_preserved(self) -> None:
        """The raw_output field should contain the original string."""
        raw = "PASS test_ok (0.001s)\n"
        result = parse_output(raw)
        assert result.raw_output == raw

    def test_output_with_failure_and_traceback(self) -> None:
        """FAIL followed by traceback lines should parse the FAIL and ignore the rest."""
        raw = (
            "FAIL test_boom (0.005s)\n"
            "RuntimeError: boom\n"
            "  File \"test_example.py\", line 10\n"
            "SUMMARY total=1 failed=1 time=0.005s\n"
        )
        result = parse_output(raw)
        assert len(result.tests) == 1
        assert result.tests[0].status == "FAIL"
        assert result.summary is not None
        assert result.summary.failed == 1
