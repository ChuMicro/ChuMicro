"""Cross-runtime micro-benchmark framework for the ChuMicro libraries.

Runs *inside* the MicroPython / CircuitPython unix-port binary (spawned
by ``scripts/benches/run_bench.py``), so it must stay importable on both
ports: no host-only stdlib, no f-string-only tricks the ports lack.

Each bench case measures one repeatable operation two ways:

* **heap churn** — bytes allocated per operation, measured with the
  collector *disabled* (``gc.disable()``) across a batch, so refcount- or
  GC-freeable transients still show up.  This is the "churn" method from
  ``plans/patterns.md`` ("`tracemalloc` catches leaks, `gc.mem_alloc`
  catches churn"): a post-collect snapshot would report zero for a hot
  path that allocates-and-drops every iteration.  ``gc.mem_alloc`` is an
  MP / CP API with no CPython equivalent, so heap churn is a port-only
  number (``-1`` sentinel when unavailable).

* **CPU wall-time** — microseconds per operation, timed over a batch with
  the collector *enabled* (production-realistic auto-GC), repeated N times
  so the caller reports a median and the min/max spread.  Laptop wall-time
  is noisy; the median plus spread is what the gate reasons about, not a
  single sample.

A bench module registers cases at import via :func:`register`; the worker
imports every ``bench_*.py`` then calls :func:`run_all`, which prints one
machine-readable ``BENCH ...`` line per case for ``run.py bench`` to parse.
"""

import gc
import time

# ---------------------------------------------------------------------------
# Cross-runtime microsecond clock.
#
# Both unix ports (and real boards) expose ``time.ticks_us`` — integer
# microseconds, wrap-safe via ``time.ticks_diff``.  ``monotonic_ns`` /
# ``monotonic`` are host (CPython) fallbacks so the harness stays smoke-
# testable off-port; the ports never reach them.
# ---------------------------------------------------------------------------

if hasattr(time, "ticks_us"):
    _sample = time.ticks_us

    def _elapsed_us(start, end):
        """Microseconds between two ``ticks_us`` samples, wrap-safe."""
        return time.ticks_diff(end, start)
elif hasattr(time, "monotonic_ns"):  # pragma: no cover - host fallback
    _sample = time.monotonic_ns

    def _elapsed_us(start, end):
        return (end - start) / 1000.0
else:  # pragma: no cover - host fallback
    _sample = time.monotonic

    def _elapsed_us(start, end):
        return (end - start) * 1e6


_HEAP_AVAILABLE = hasattr(gc, "mem_alloc")

#: Iterations run untimed before each measurement so first-call lazy
#: imports, buffer growth, and poll-adapter construction don't land in
#: the numbers.
_WARMUP = 20


class _Bench:
    """One registered bench case.

    ``setup()`` returns an opaque state object; ``op(state)`` performs
    exactly one measured operation and must be safe to call repeatedly on
    the same state (the reactor tick, a feed+reset frame cycle).
    """

    def __init__(self, bench_id, setup, op, heap_batch, cpu_batch,
                 repeats, payload_bytes, note):
        self.bench_id = bench_id
        self.setup = setup
        self.op = op
        self.heap_batch = heap_batch
        self.cpu_batch = cpu_batch
        self.repeats = repeats
        self.payload_bytes = payload_bytes
        self.note = note


_REGISTRY = []


def register(bench_id, setup, op, heap_batch=256, cpu_batch=2000,
             repeats=7, payload_bytes=0, note=""):
    """Register a bench case.

    Args:
        bench_id: Stable identifier, a TOML bare key (``[A-Za-z0-9_]``);
            the baseline is keyed on it, so renaming resets its history.
        setup: Zero-arg callable returning the state passed to *op*.
        op: One-arg callable ``op(state)`` performing one operation.
        heap_batch: Operations per heap-churn measurement.  Kept modest:
            with the collector disabled every allocation accumulates, so
            ``heap_batch * bytes_per_op`` must fit the port's native heap.
        cpu_batch: Operations per timed CPU sample (amortizes clock
            resolution).
        repeats: CPU samples taken; the reporter emits their median and
            min/max spread.
        payload_bytes: Bytes processed per op, for a throughput (bytes/s)
            display.  ``0`` means "not a throughput bench".
        note: Short human description surfaced in the worker's comments.
    """
    _REGISTRY.append(
        _Bench(bench_id, setup, op, heap_batch, cpu_batch, repeats,
               payload_bytes, note),
    )


def _measure_heap_churn(bench, state):
    """Return bytes allocated per op with the collector disabled.

    ``-1`` when ``gc.mem_alloc`` is unavailable (host CPython).
    """
    if not _HEAP_AVAILABLE:
        return -1.0
    op = bench.op
    batch = bench.heap_batch
    gc.collect()
    gc.disable()
    before = gc.mem_alloc()
    for _ in range(batch):
        op(state)
    total = gc.mem_alloc() - before
    gc.enable()
    gc.collect()
    return total / batch


def _measure_cpu_us(bench, state):
    """Return ``(median, minimum, maximum)`` microseconds per op."""
    op = bench.op
    batch = bench.cpu_batch
    samples = []
    for _ in range(bench.repeats):
        start = _sample()
        for _ in range(batch):
            op(state)
        end = _sample()
        samples.append(_elapsed_us(start, end) / batch)
    samples.sort()
    return samples[len(samples) // 2], samples[0], samples[-1]


def _run_one(bench):
    """Measure one case and return its ``BENCH`` output line."""
    state = bench.setup()
    op = bench.op
    for _ in range(_WARMUP):
        op(state)
    heap_churn = _measure_heap_churn(bench, state)
    cpu_median, cpu_min, cpu_max = _measure_cpu_us(bench, state)
    return (
        f"BENCH id={bench.bench_id} heap_churn_bytes={heap_churn:.1f} "
        f"cpu_us={cpu_median:.4f} cpu_us_min={cpu_min:.4f} "
        f"cpu_us_max={cpu_max:.4f} repeats={bench.repeats} "
        f"cpu_batch={bench.cpu_batch} heap_batch={bench.heap_batch} "
        f"payload_bytes={bench.payload_bytes}"
    )


def run_all():
    """Run every registered case, printing one ``BENCH`` line apiece.

    A case that raises is reported as ``BENCH-ERROR`` and does not abort
    the others, so one broken bench fails the gate without hiding the
    rest.  Returns a shell exit code: 0 when every case measured, 1 when
    any case raised.
    """
    import sys

    print(f"# runtime={sys.implementation.name} benches={len(_REGISTRY)}")
    failed = 0
    for bench in _REGISTRY:
        if bench.note:
            print(f"# {bench.bench_id}: {bench.note}")
        try:
            print(_run_one(bench))
        except Exception as error:  # noqa: BLE001 - report, don't abort the sweep
            failed += 1
            print(f"BENCH-ERROR id={bench.bench_id} msg={error}")
    print(f"BENCH-DONE count={len(_REGISTRY)} failed={failed}")
    return 1 if failed else 0
