"""The opt-in perf/heap ``bench`` gate (not wired into preflight)."""

from __future__ import annotations

from repo_layout import ROOT
from shared import stream_subprocess

from run_tasks.testing_crossruntime import _ensure_unix_port_binary

#: Worker the bench subcommand runs under each unix-port binary, and the
#: committed per-runtime baseline it compares against.
_BENCH_WORKER = "scripts/benches/run_bench.py"


_BENCH_BASELINE = ROOT / "scripts" / "benches" / "baseline.toml"


#: Runtimes the bench sweeps — both unix ports, same set the test lanes
#: cover.
_BENCH_RUNTIMES = ("micropython", "circuitpython")


def _bench_throughput_suffix(result: object) -> str:
    """Return a ``  <n> MB/s`` suffix for a payload bench, else ``""``."""
    payload_bytes = getattr(result, "payload_bytes", 0)
    cpu_us = getattr(result, "cpu_us", 0.0)
    if payload_bytes and cpu_us > 0:
        megabytes_per_s = payload_bytes / (cpu_us / 1e6) / 1e6
        return f"  {megabytes_per_s:.1f} MB/s"
    return ""


def _print_bench_findings(runtime: str, findings: list) -> None:
    """Render one runtime's comparison verdicts as an aligned table."""
    print(f"== bench: {runtime} ==")
    for finding in findings:
        status = finding.status.upper()
        result = finding.measured
        if result is None:
            # MISSING: in the baseline, not measured this run.
            print(
                f"  [{status:<10}] {finding.bench_id:<24} "
                f"(baseline heap {finding.baseline_heap}, "
                f"cpu {finding.baseline_cpu})",
            )
            continue
        heap_cell = f"heap {result.heap_churn_bytes:8.1f} B"
        cpu_cell = f"cpu {result.cpu_us:8.2f} us"
        if finding.baseline_heap is not None:
            heap_cell += f" (base {finding.baseline_heap:.1f})"
            ratio = result.cpu_us / finding.baseline_cpu if finding.baseline_cpu else 0.0
            cpu_cell += f" (base {finding.baseline_cpu:.2f}, x{ratio:.2f})"
        print(
            f"  [{status:<10}] {finding.bench_id:<24} {heap_cell}  "
            f"{cpu_cell}{_bench_throughput_suffix(result)}",
        )
        for reason in finding.reasons:
            if finding.is_regression:
                print(f"       -> {reason}")


def bench(
    micropython_binary: str | None = None,
    circuitpython_binary: str | None = None,
    *,
    update_baseline: bool = False,
) -> int:
    """Run every bench on both unix ports; compare against the baseline.

    Sweeps ``scripts/benches/bench_*.py`` (heap churn + CPU wall-time per
    op) under the MicroPython and CircuitPython unix-port binaries, then
    either compares the numbers against the committed
    ``scripts/benches/baseline.toml`` (default — the regression gate) or
    rewrites that file (*update_baseline*).

    Heap churn is gated exact-or-better plus a small slack; CPU is gated
    with a wide multiplicative band since laptop wall-time is noisy (see
    ``scripts/bench_baseline.py`` for the exact tolerances).  Returns 0
    when every metric is within tolerance on both runtimes, 1 on any
    regression, a worker crash, or a missing baseline.
    """
    from bench_baseline import (
        BenchOutputError,
        compare_runtime,
        parse_bench_output,
        serialize_baseline,
    )
    from prepare_circuitpython import prepare_circuitpython
    from prepare_micropython import prepare_micropython
    from shared import (
        resolve_circuitpython_binary,
        resolve_micropython_binary,
    )

    resolvers = {
        "micropython": (
            micropython_binary, resolve_micropython_binary, prepare_micropython,
        ),
        "circuitpython": (
            circuitpython_binary, resolve_circuitpython_binary,
            prepare_circuitpython,
        ),
    }

    measured_by_runtime: dict[str, dict] = {}
    for runtime in _BENCH_RUNTIMES:
        override, resolve, prepare = resolvers[runtime]
        prep_result = _ensure_unix_port_binary(
            runtime, override, lambda resolve=resolve, override=override: resolve(override),
            prepare, None,
        )
        if prep_result != 0:
            return prep_result
        binary = override or resolve(override)
        print(f"-> benching {runtime}: {binary}")
        exit_code, captured = stream_subprocess(
            [binary, _BENCH_WORKER], cwd=ROOT,
        )
        try:
            measured = parse_bench_output(captured)
        except BenchOutputError as error:
            print(f"bench worker failed on {runtime}: {error}")
            print(captured)
            return 1
        if not measured:
            print(
                f"bench worker on {runtime} produced no results "
                f"(exit {exit_code}).",
            )
            print(captured)
            return 1
        measured_by_runtime[runtime] = measured

    if update_baseline:
        from datetime import date
        text = serialize_baseline(measured_by_runtime, date.today().isoformat())
        _BENCH_BASELINE.write_text(text)
        print(f"Wrote baseline: {_BENCH_BASELINE.relative_to(ROOT)}")
        for runtime in _BENCH_RUNTIMES:
            findings = compare_runtime(measured_by_runtime[runtime], {})
            _print_bench_findings(runtime, findings)
        return 0

    if not _BENCH_BASELINE.exists():
        print(
            f"No baseline at {_BENCH_BASELINE.relative_to(ROOT)}.  "
            f"Record one with: python scripts/run.py bench --update-baseline",
        )
        return 1

    from repo_layout import load_tomllib
    baseline_doc = load_tomllib().loads(_BENCH_BASELINE.read_text())

    regressed = False
    for runtime in _BENCH_RUNTIMES:
        findings = compare_runtime(
            measured_by_runtime[runtime], baseline_doc.get(runtime, {}),
        )
        _print_bench_findings(runtime, findings)
        if any(finding.is_regression for finding in findings):
            regressed = True

    if regressed:
        print(
            "\nbench: REGRESSION — a metric crossed its tolerance band.  "
            "If the change is intended, re-record with: "
            "python scripts/run.py bench --update-baseline",
        )
        return 1
    print("\nbench: OK — every metric within tolerance on both runtimes.")
    return 0


def register(subparsers, parents):
    """Register the bench subcommand."""
    binary = parents["binary"]
    bench_parser = subparsers.add_parser(
        "bench", parents=[binary],
        help=(
            "run perf/heap benches on both unix ports and compare against "
            "the committed baseline (opt-in local gate; not in preflight)"
        ),
    )
    bench_parser.add_argument(
        "--update-baseline", action="store_true",
        help="rewrite scripts/benches/baseline.toml from this run instead of comparing",
    )
