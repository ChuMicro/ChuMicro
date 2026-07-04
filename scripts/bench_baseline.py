"""Parse, compare, and serialize perf/heap bench results for ``run.py bench``.

Pure functions (no subprocess, no I/O beyond an explicit path read) so the
tolerance policy and the baseline round-trip are unit-testable without a
unix-port binary.  ``run.py`` owns the subprocess orchestration; this
module owns the numbers.

Two metrics per bench, two tolerance policies:

* **heap churn** — deterministic on the ports (identical run-to-run), so
  the gate is exact-or-better plus a small absolute slack
  (:data:`HEAP_SLACK_BYTES`).  The ports allocate in ~16-byte blocks, so a
  16-byte slack absorbs a boundary flicker without masking a real
  per-op allocation (the smallest meaningful object is dozens of bytes).

* **CPU wall-time** — noisy on a laptop (background load, no JIT warmup
  control), so the gate is a generous multiplicative band
  (:data:`CPU_TOLERANCE_FACTOR`) with an absolute floor
  (:data:`CPU_TOLERANCE_FLOOR_US`) so a sub-microsecond op isn't failed by
  jitter.  The band flags order-of-magnitude regressions — the kind that
  breaks the ≤5 ms tick discipline — not run-to-run noise.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Absolute per-op heap slack, in bytes, added to the baseline before a
#: heap number counts as a regression.
HEAP_SLACK_BYTES = 16.0

#: A CPU median above ``baseline * FACTOR`` (and above the floor below) is
#: a regression.
CPU_TOLERANCE_FACTOR = 2.0

#: Absolute CPU floor, in microseconds: regressions must also exceed
#: ``baseline + FLOOR`` so tiny ops aren't failed by timer jitter.
CPU_TOLERANCE_FLOOR_US = 5.0


class BenchOutputError(Exception):
    """The worker's stdout was malformed or reported a bench failure."""


@dataclass
class BenchResult:
    """One bench's measured numbers, parsed from a ``BENCH`` line."""

    bench_id: str
    heap_churn_bytes: float
    cpu_us: float
    cpu_us_min: float
    cpu_us_max: float
    payload_bytes: int


@dataclass
class BenchFinding:
    """A per-bench comparison verdict for one runtime.

    ``status`` is one of ``"ok"``, ``"regression"``, ``"new"`` (measured
    but absent from the baseline), or ``"missing"`` (in the baseline but
    not measured).  Only ``"regression"`` fails the gate.
    """

    bench_id: str
    status: str
    measured: BenchResult | None
    baseline_heap: float | None
    baseline_cpu: float | None
    reasons: list[str]

    @property
    def is_regression(self) -> bool:
        return self.status == "regression"


def _parse_fields(rest: str) -> dict[str, str]:
    """Split a ``key=value key=value`` tail into a dict."""
    fields: dict[str, str] = {}
    for token in rest.split():
        key, sep, value = token.partition("=")
        if sep:
            fields[key] = value
    return fields


def parse_bench_output(text: str) -> dict[str, BenchResult]:
    """Parse a worker's stdout into ``{bench_id: BenchResult}``.

    Recognizes ``BENCH ...`` result lines and ignores ``#`` comments.
    Raises :class:`BenchOutputError` on a ``BENCH-ERROR`` line, a
    ``BENCH-DONE`` reporting failures, or no ``BENCH-DONE`` at all (the
    worker crashed mid-run).
    """
    results: dict[str, BenchResult] = {}
    saw_done = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("BENCH-ERROR"):
            fields = _parse_fields(line[len("BENCH-ERROR"):])
            raise BenchOutputError(
                f"bench {fields.get('id', '?')} raised: "
                f"{fields.get('msg', 'unknown')}",
            )
        if line.startswith("BENCH-DONE"):
            saw_done = True
            fields = _parse_fields(line[len("BENCH-DONE"):])
            if int(fields.get("failed", "0")) != 0:
                raise BenchOutputError(
                    f"worker reported {fields['failed']} failed bench(es)",
                )
            continue
        if not line.startswith("BENCH "):
            continue
        fields = _parse_fields(line[len("BENCH "):])
        bench_id = fields["id"]
        results[bench_id] = BenchResult(
            bench_id=bench_id,
            heap_churn_bytes=float(fields["heap_churn_bytes"]),
            cpu_us=float(fields["cpu_us"]),
            cpu_us_min=float(fields.get("cpu_us_min", fields["cpu_us"])),
            cpu_us_max=float(fields.get("cpu_us_max", fields["cpu_us"])),
            payload_bytes=int(fields.get("payload_bytes", "0")),
        )
    if not saw_done:
        raise BenchOutputError(
            "worker produced no BENCH-DONE line (crashed mid-run):\n" + text,
        )
    return results


def _cpu_ceiling(baseline_cpu: float) -> float:
    """Return the CPU median above which a result is a regression."""
    return max(
        baseline_cpu * CPU_TOLERANCE_FACTOR,
        baseline_cpu + CPU_TOLERANCE_FLOOR_US,
    )


def compare_runtime(
    measured: dict[str, BenchResult],
    baseline: dict[str, dict],
) -> list[BenchFinding]:
    """Compare one runtime's measured results against its baseline table.

    *baseline* is the ``{bench_id: {heap_churn_bytes, cpu_us, ...}}`` table
    for this runtime (from the parsed baseline TOML).  Returns one
    :class:`BenchFinding` per bench id seen in either map, sorted by id.
    """
    findings: list[BenchFinding] = []
    for bench_id in sorted(set(measured) | set(baseline)):
        result = measured.get(bench_id)
        base = baseline.get(bench_id)
        if result is None:
            findings.append(
                BenchFinding(bench_id, "missing", None,
                             base and base.get("heap_churn_bytes"),
                             base and base.get("cpu_us"),
                             ["in baseline but not measured this run"]),
            )
            continue
        if base is None:
            findings.append(
                BenchFinding(bench_id, "new", result, None, None,
                             ["no baseline entry (run --update-baseline)"]),
            )
            continue
        base_heap = float(base["heap_churn_bytes"])
        base_cpu = float(base["cpu_us"])
        reasons: list[str] = []
        if result.heap_churn_bytes > base_heap + HEAP_SLACK_BYTES:
            reasons.append(
                f"heap {result.heap_churn_bytes:.1f} B > baseline "
                f"{base_heap:.1f} + {HEAP_SLACK_BYTES:.0f} slack",
            )
        ceiling = _cpu_ceiling(base_cpu)
        if result.cpu_us > ceiling:
            reasons.append(
                f"cpu {result.cpu_us:.2f} us > ceiling {ceiling:.2f} "
                f"(baseline {base_cpu:.2f})",
            )
        findings.append(
            BenchFinding(
                bench_id,
                "regression" if reasons else "ok",
                result, base_heap, base_cpu, reasons,
            ),
        )
    return findings


def _format_float(value: float) -> str:
    """Render a float without trailing-zero noise but stable for TOML."""
    text = f"{value:.4f}"
    text = text.rstrip("0").rstrip(".") if "." in text else text
    return text or "0"


def serialize_baseline(
    results_by_runtime: dict[str, dict[str, BenchResult]],
    updated: str,
) -> str:
    """Render the committed baseline TOML from measured results.

    *results_by_runtime* is ``{runtime: {bench_id: BenchResult}}``;
    *updated* is the ISO date stamped into ``[meta]``.  Output is
    deterministic (runtimes and bench ids sorted) so a re-measure with the
    same numbers produces a byte-identical file — a no-op diff.
    """
    lines = [
        "# Perf/heap regression baseline for `python scripts/run.py bench`.",
        "# Auto-generated by `run.py bench --update-baseline`; do not",
        "# hand-edit.  Per unix-port runtime.  heap_churn_bytes is per-op",
        "# allocation churn (gc-disabled, deterministic); cpu_us is the",
        "# median per-op wall-time (laptop-noisy — gated with a wide band).",
        "",
        "[meta]",
        f'updated = "{updated}"',
        "",
    ]
    for runtime in sorted(results_by_runtime):
        for bench_id in sorted(results_by_runtime[runtime]):
            result = results_by_runtime[runtime][bench_id]
            lines.append(f"[{runtime}.{bench_id}]")
            lines.append(
                f"heap_churn_bytes = {_format_float(result.heap_churn_bytes)}",
            )
            lines.append(f"cpu_us = {_format_float(result.cpu_us)}")
            lines.append(f"payload_bytes = {result.payload_bytes}")
            lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
