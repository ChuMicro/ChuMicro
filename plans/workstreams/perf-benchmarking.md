# Workstream: performance + resource benchmarking

Status: **MVP shipped (2026-07-04).** Local opt-in gate live; CI attachment deferred by design.

Heap + CPU per-library-op benchmarking with a committed baseline and a regression gate. First
consumers: the runner reactor loop and the websockets frame parser (the 2026-06 deep-review
residual re-verify). CI is disabled repo-wide, so the MVP is a **local** gate; it is built so a
future scheduled-CI lane attaches with no reshaping.

## What shipped

- **Bench harness** (`scripts/benches/`): a cross-runtime framework that measures, per operation,
  (a) **heap churn** — bytes allocated per op, `gc.disable()`-bracketed over a batch (the "churn"
  method from `plans/patterns.md`: a post-collect snapshot misses refcount/GC-freeable transients),
  and (b) **CPU** — median per-op wall-time over N timed batches, with the min/max spread reported.
  Both metrics run on **both unix ports**.
- **Two real benches:**
  - `bench_runner.py` — the reactor `tick()`+`wait()` cycle at 3/10/30 registered no-op services
    (the ≤5 ms tick-discipline number).
  - `bench_websockets.py` — the `FrameParser` decode cycle (feed a complete client-masked binary
    frame, snapshot `.payload`, `reset()`) at small (64 B, tier-1 steady buffer) and medium
    (1024 B, tier-2 one-shot bytearray) payload sizes, with per-frame alloc and a derived bytes/sec.
- **Committed baseline** (`scripts/benches/baseline.toml`): dated, per-runtime, auto-generated.
- **`run.py bench` subcommand:** runs every bench on both ports and compares against the baseline;
  `--update-baseline` rewrites it. Comparison + serialization live in `scripts/bench_baseline.py`
  (pure, unit-tested in `scripts/tests/test_bench_baseline.py`). **Not wired into preflight** —
  opt-in gate (see the CI hook below).

### Files

| File | Role |
|------|------|
| `scripts/benches/_harness.py` | measurement framework (clock, heap-churn, CPU median/spread, registry, `BENCH` output) |
| `scripts/benches/bench_runner.py` | reactor tick+wait benches (3/10/30 services) |
| `scripts/benches/bench_websockets.py` | frame-parser decode benches (small/medium) |
| `scripts/benches/run_bench.py` | worker entry: `sys.path` bootstrap + run all benches on one port |
| `scripts/benches/baseline.toml` | committed dated per-runtime baseline |
| `scripts/bench_baseline.py` | parse / compare / serialize (the tolerance policy) |
| `scripts/tests/test_bench_baseline.py` | unit tests for the parse + gate logic |
| `scripts/run.py` | `bench` subcommand + task function |

## Scope decisions (and why)

### Layout: central `scripts/benches/`, not per-library `libraries/<lib>/benches/`

Both were offered. Central won:

1. **No packaging leakage.** Per-library `benches/` would sit inside the published package tree and
   need sdist-exclusion plumbing (`scripts/sdist_content.py`) to stay out of PyPI artifacts.
   Central benches are never packaged.
2. **Zero test-lane interference.** The unix test lanes glob `libraries/*/tests`; a central location
   is off every existing sweep with no config, and carries no `target-runtimes.toml [heap.overrides]`
   entry (the benches run under the port's native heap, not a board-shaped budget — see below).
3. **Co-location with the gate.** Benches, baseline, and the `run.py bench` subcommand live together,
   mirroring how `scripts/tests/` holds infra tests centrally rather than per-library.

The bench modules import library sources via the same `sys.path` bootstrap the cross-runtime test
worker uses (`chumicro_test_harness.discovery.setup_source_paths` → every `libraries/*/src`), so the
central location costs nothing in import reach.

### Measurement idioms (reused house patterns)

- **Runtime invocation** mirrors `support/test_harness/run_cross_runtime.py`: a worker script the
  unix-port binary runs, resolved via `.tools/{micropython,circuitpython}.path` and
  `_ensure_unix_port_binary` — the same machinery `test-micropython` / `test-circuitpython` use.
- **Heap** is `gc.mem_alloc()` deltas — but with the collector **disabled** across the batch (churn),
  not `gc.collect()`-bracketed net-retained. The reactor's `tick()` is genuinely zero-churn; a
  net-retained measure would report 0 for a hot path that allocates-and-drops, which is exactly the
  trap `plans/patterns.md` records. (The re-pose report's `gc.collect()`-bracketed idiom measures
  *retained instance cost* — the right tool for "how big is this object", the wrong one for "does
  this hot loop churn".)
- **Clock** is `time.ticks_us` (present on both unix ports) via `time.ticks_diff` (wrap-safe), with
  `monotonic_ns` / `monotonic` host fallbacks so the harness stays smoke-testable off-port.

### Benches run under the port's **native** heap, not a board-shaped `-X heapsize` budget

The heap *budget* lanes (`target-runtimes.toml [heap]`) exist to catch OOM on a Pico-W-shaped heap.
The bench deliberately does the opposite: it disables the collector and accumulates a whole batch of
allocations to measure churn, which needs multi-MB headroom. So `run.py bench` invokes the binary
with no `-X heapsize`. Heap *budget* regressions stay the test lanes' job; heap *churn* is the bench's.

### Tolerance bands

- **Heap: exact-or-better + 16 B slack.** Churn is deterministic on the ports (byte-identical
  run-to-run and across runtimes — see the numbers below), so the gate is strict:
  `measured > baseline + 16 B` fails. 16 B absorbs a ~16-byte-block allocator boundary flicker
  without masking a real per-op allocation (the smallest meaningful object is dozens of bytes).
- **CPU: wide multiplicative band + absolute floor.** `measured > max(baseline × 2.0, baseline + 5 µs)`
  fails. Laptop wall-time swings 30–50 % run-to-run (background load, no JIT/warmup control), and the
  reactor ops are single-digit microseconds where a 5 µs floor is generous. The band flags
  order-of-magnitude regressions — the kind that breaks the ≤5 ms tick discipline — not noise.
  Constants live in `scripts/bench_baseline.py` (`HEAP_SLACK_BYTES`, `CPU_TOLERANCE_FACTOR`,
  `CPU_TOLERANCE_FLOOR_US`).

## Measured baseline (2026-07-04, this laptop)

| Bench | Runtime | heap churn/op | CPU median | throughput |
|-------|---------|--------------:|-----------:|-----------:|
| reactor_tick_3svc | MP / CP | 0 B / 0 B | 3.1 µs / 3.5 µs | — |
| reactor_tick_10svc | MP / CP | 0 B / 0 B | 6.3 µs / 7.3 µs | — |
| reactor_tick_30svc | MP / CP | 0 B / 0 B | 15.4 µs / 16.5 µs | — |
| ws_frame_decode_small (64 B) | MP / CP | 448 B / 448 B | 9.2 µs / 9.9 µs | ~6.9 / 6.5 MB/s |
| ws_frame_decode_medium (1024 B) | MP / CP | 2624 B / 2624 B | 72 µs / 80 µs | ~14 / 13 MB/s |

Sanity: reactor tick+wait at 3 services is **~3 µs** — three orders of magnitude under the 1 ms
laptop expectation and the ≤5 ms discipline. Heap churn is byte-identical across both runtimes,
confirming the exact-plus-slack gate is well-founded.

### Finding surfaced by the first run (not fixed here — bench infra only)

The reactor's **`tick()` is zero-churn** (0 B/1000 ticks); the entire **64 B/cycle** came from
**`wait()`** even when no service exposes a socket or a deadline (measured by attribution: tick-only
0 B, wait-only 64 B/call). Small and per-cycle, but the churn guard in `plans/patterns.md` asserts
`<= 64 B` per *1000* `tick()` calls — the reactor met that for `tick()`, and the socket-less
`wait()` allocation was a tracked baseline number. Flagging it is the bench doing its job.

- **Fixed in place (runner 0.18.2).** Bisected the 64 B to `_sync_poll_set`'s stale-socket-drop
  tail: the `stale = [sid for sid in registered if registered[sid][3] != generation]` comprehension
  closes over `registered` / `generation`, and MicroPython boxes those free vars into heap cells at
  their assignment — *unconditionally, ahead of the `if len(registered) > wanted_count:` guard* — so
  the cell churned on every call even when nothing was stale (the socket-less steady state). Rewrote
  it as an explicit `append` loop (no closure, no cells). Reactor heap/op is now **0 B** on both
  ports at all three service counts, with an incidental ~1.3–2.3× CPU speedup (the cell alloc + its
  GC was a real slice of the cycle). Baseline re-recorded to 0.

## Deliberately excluded from the MVP

- **On-board benching.** Host unix-port only. Real-board timing (mpremote RPC latency, flash-mode
  exec) is a different harness; the numbers here are relative-regression signals, not board truth.
- **Flash-size / footprint tracking.** Deploy-weight (stripped bytes via the real minifier) is
  already covered by the re-pose reports and `audit-embedded`; not folded in here.
- **CI schedule.** CI is disabled repo-wide. No workflow, no cron. The gate is local + opt-in.
- **Auto-baseline-on-drift.** The baseline only moves on an explicit `--update-baseline`. No
  self-healing — a regression must be acknowledged by re-recording.

## Next steps

1. **CI attachment (when CI returns).** Add a scheduled lane that runs `run.py bench` and, on a
   host with pinned CPU governor, treats a CPU regression as a hard fail. The subcommand already
   returns non-zero on regression; the only new piece is a workflow with the two prepared binaries.
   Keep it **off** the per-PR preflight (wall-time on shared CI runners is noisier than a laptop).
2. **More consumers.** The mqtt `PacketDecoder` and the sockets connector state machine are the
   natural next benches (same `register(...)` shape). Add a `bench_<lib>.py` and a line in
   `run_bench.py`.
3. **Re-baseline cadence.** Re-record when a runtime pin bumps (`target-runtimes.toml`) or after a
   deliberate hot-path change; the baseline carries its own date.
4. ~~**Investigate the `wait()` 64 B/cycle**~~ — done (runner 0.18.2): the closure-boxed cell in
   `_sync_poll_set`'s stale-drop comprehension; rewritten as an explicit loop, baseline dropped to 0.
   See the finding above.

## Validation history

- 2026-07-04: MVP shipped. Both benches green on both unix ports; `run.py bench` compare + update
  paths exercised; `scripts/tests/test_bench_baseline.py` (13 cases) green; lint + test-scripts clean.
