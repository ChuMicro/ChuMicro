"""Parse structured output from the lightweight test harness.

The test harness emits one line per event — ``PASS``, ``FAIL``, ``SKIP``,
``SUMMARY``, and ``HEAP`` — with a fixed format.  This module turns raw
captured output into typed result objects that the device orchestration
layer can inspect programmatically.

This is host-side only (CPython).  It is never deployed to a device.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class TestResult:
    """Result of a single test function execution on device."""

    name: str
    status: str  # "PASS", "FAIL", or "SKIP"
    duration: float | None = None
    heap_delta: int | None = None
    message: str = ""


@dataclass
class HeapResult:
    """Module-level heap summary from the harness."""

    bytes_free: int
    delta: int


@dataclass
class SummaryResult:
    """Aggregate summary line from the harness."""

    total: int
    failed: int
    duration: float


@dataclass
class RunResult:
    """Complete parsed output from a single harness run."""

    tests: list[TestResult] = field(default_factory=list)
    heap: HeapResult | None = None
    summary: SummaryResult | None = None
    raw_output: str = ""


# Patterns for each structured line type.
_PASS_FAIL_PATTERN = re.compile(
    r"^(PASS|FAIL)\s+(\S+)\s+\((\d+\.\d+)s"
    r"(?:,\s*heap\s*([+-]?\d+))?\)"
)
_SKIP_PATTERN = re.compile(r"^SKIP\s+(\S+)(?:\s+\((.+)\))?")
_SUMMARY_PATTERN = re.compile(
    r"^SUMMARY\s+total=(\d+)\s+failed=(\d+)\s+time=(\d+\.\d+)s"
)
_HEAP_PATTERN = re.compile(
    r"^HEAP\s+(\d+)\s+bytes\s+free\s+\(delta\s+([+-]?\d+)\s+bytes\)"
)


def parse_output(raw_output: str) -> RunResult:
    """Parse raw harness output into a structured ``RunResult``.

    Lines that do not match any known pattern are silently ignored —
    device output often includes boot messages, print-debugging, or
    other noise that should not break parsing.

    Args:
        raw_output: Complete captured stdout from a harness run.

    Returns:
        Populated ``RunResult`` with tests, heap, and summary fields.
    """
    result = RunResult(raw_output=raw_output)

    for line in raw_output.splitlines():
        stripped = line.strip()

        match = _PASS_FAIL_PATTERN.match(stripped)
        if match:
            heap_delta = (
                int(match.group(4)) if match.group(4) is not None else None
            )
            result.tests.append(TestResult(
                name=match.group(2),
                status=match.group(1),
                duration=float(match.group(3)),
                heap_delta=heap_delta,
            ))
            continue

        match = _SKIP_PATTERN.match(stripped)
        if match:
            result.tests.append(TestResult(
                name=match.group(1),
                status="SKIP",
                message=match.group(2) or "",
            ))
            continue

        match = _SUMMARY_PATTERN.match(stripped)
        if match:
            result.summary = SummaryResult(
                total=int(match.group(1)),
                failed=int(match.group(2)),
                duration=float(match.group(3)),
            )
            continue

        match = _HEAP_PATTERN.match(stripped)
        if match:
            result.heap = HeapResult(
                bytes_free=int(match.group(1)),
                delta=int(match.group(2)),
            )

    return result

