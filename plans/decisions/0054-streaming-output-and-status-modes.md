# Decision 0054: Streaming output + status modes for parallel tasks

Status: `accepted`
Date: `2026-05-04`
Summary: `stream_subprocess` line-streams child output; phase callables are `(sink) -> int`; four dispatchers (quiet/interleave/status/raw); auto-detected by TTY + `CHUMICRO_RAW_OUTPUT` env.
Related: [Decision 0048](0048-preflight-phase-level-parallel.md)
(supersedes §3 — "Mechanism: subprocess re-invocation" — and refines §1 — output capture)

## Context

Decision 0048 parallelized the `preflight` phase loop and the per-package fan-out inside `build` / `docs` / `test`.  The chosen mechanism was `subprocess.run(capture_output=True)` for every parallel phase: each child's full stdout + stderr was buffered until the child exited, then printed verbatim under a `== <label> ==` header in submission order.

This produced the right *final* log shape but a poor user experience while running:

- **No real-time feedback.**  A `preflight` run took 20 seconds, and during those 20 seconds the user saw nothing — then the whole log dumped at once when the slowest phase exited.  `docs`, `build`, and `test` (when fanned out) had the same shape.
- **No way to tell a hung run from a slow one.**  Without per-phase events the user had to either wait or interrupt.
- **Manual workaround visible in `.scratch/`.**  The user was redirecting `python scripts/run.py preflight > .scratch/preflight.log` to capture the output, then `tail -f`'ing it from another terminal.  That's a UX failure.
- **No mode for AI / log-capture contexts.**  Even when the dump-at-end shape was preferable (CI artifact, non-interactive agent), there was no way to opt back into it for the long-running interactive case.
- **Hardcoded worker counts.**  `_DEFAULT_PACKAGE_PARALLEL_WORKERS = 4` and `_DEFAULT_PREFLIGHT_PHASE_PARALLEL_WORKERS = 4` ignored host capability — under-using a 12-core laptop and oversubscribing a 4-core one.

Decision 0048 §3 chose subprocess re-invocation explicitly *because* `subprocess.run(capture_output=True)` was the only way to capture child output it considered.  The "Alternatives considered" section listed three options (thread-local stdout proxy, capture inside `run_command`, multiprocessing.Pool) but never considered `Popen` with a line-reader thread.  This ADR takes that path.

## Decision

### 1. Streaming subprocess helper

A new helper `shared.stream_subprocess(command, *, cwd, environment, on_line)` runs the child with `subprocess.Popen` (`stdout=PIPE`, `stderr=STDOUT`, `bufsize=1`, `text=True`), drains the merged stream line-by-line, and:

- delivers each line to `on_line` the moment it arrives (or skips the callback when `on_line is None`)
- accumulates the full transcript into the returned buffer

Stderr is merged into stdout so the line stream preserves the order the child emitted output.  The single griffe-warning consumer that previously inspected `completed.stderr` directly (`_build_one_library_docs_factory`) now scans the combined captured transcript — griffe lines are content-identifiable (`"griffe" in line.lower()`), so the filter still works.

### 2. Sink + dispatcher abstraction

Phase callables change shape from `() -> (exit_code, output)` to `(sink: _Sink) -> int`:

- `_Sink` records every line into a per-phase buffer *and* forwards it to the dispatcher
- the dispatcher decides what to do with each line (buffer, prefix-and-print, suppress)
- the runner (`_run_parallel_phases`) wires sinks to phases and invokes dispatcher lifecycle methods (`start` / `phase_started` / `phase_done` / `finish`)

This consolidates the two pre-existing helpers (`_run_phases_in_parallel` and `_run_capture_phases_in_parallel`) into a single `_run_parallel_phases(phases, *, dispatcher, max_workers)`.  The older `redirect_stdout`-based helper is removed (its only caller was `test_all_runtimes`, which now uses the unified runner).

### 3. Three output modes + auto-detection

Four dispatchers exist; three are user-visible modes and the fourth is an internal-only "I am a child of another dispatcher" mode:

- **`_QuietDispatcher`** — buffer per phase, replay at finish() under `== <label> ==` headers in submission order.  This is the original Decision 0048 shape, preserved for `--quiet`, agent / log-capture contexts, and any consumer that needs deterministic per-phase blocks.
- **`_InterleaveDispatcher`** — print phase events live (`-> lint`, `[OK] lint (1.2s)`) and prefix every output line with `[label]`.  Default for non-TTY contexts (CI logs, redirected stdout).  Lines from different phases interleave but each is grep-able by phase label.
- **`_StatusDispatcher`** — print phase events live with elapsed time but suppress per-line output during the run.  At finish(), dump the full transcript of any failed phase under a `== <label> (failed) ==` header.  Default for TTY contexts — the "Gradle-style status, tail on error" the user asked for.
- **`_RawDispatcher`** — internal only.  Used inside the child of a subprocess re-invocation (when `CHUMICRO_RAW_OUTPUT=1` is set in the env).  Lines print raw to the child's stdout; the parent's `stream_subprocess` reader picks them up and routes them through *its* dispatcher.  No phase events, no headers.

Selection happens in `_pick_dispatcher(quiet)`:

1. `CHUMICRO_RAW_OUTPUT` env var → raw
2. `--quiet` flag → quiet
3. `sys.stdout.isatty()` → status
4. otherwise → interleave

### 4. Subprocess re-invocation persists, but for a different reason

Decision 0048 §3 chose subprocess re-invocation *because* it was the only way to capture child output cleanly.  After this ADR, that justification is gone — `stream_subprocess` captures fd-level output directly.  Re-invocation persists for a different (smaller) reason: per-phase resource isolation.  Each phase gets its own Python process, its own working set, its own tracebacks.  An OOM or import-time crash in one phase doesn't take down the whole preflight.

The renamed `_subcommand_phase_factory` now sets `CHUMICRO_RAW_OUTPUT=1` in the child's environment so the child's own dispatcher resolves to `_RawDispatcher` (raw passthrough); without this, the child would build its own dispatcher and the parent would see nested `[label] [inner-label] line` framing.  Decision 0092 removed the previous alias `_preflight_phase_subprocess_factory`.  Every caller now uses `_subcommand_phase_factory`.

`test_all_runtimes` is the one place that *moved away* from subprocess re-invocation: its parallel mp/cp phases now call `test_micropython` / `test_circuitpython` in-process, threading a `sink` keyword argument through `_test_runtime_compat` so subprocess output (the actual unix-port test runs) flows through the sink via `stream_subprocess`.  This avoids re-translating Path-typed `package_dirs` into a `--libraries` CLI flag.

### 5. Host-aware default worker counts

`_DEFAULT_PHASE_WORKERS` and `_DEFAULT_PACKAGE_WORKERS` are now computed by `_default_workers()`:

- `phase = max(2, min(11, round(cores ** 0.5)))`
- `package = max(1, min(4, cores // phase))`

The product (`phase × package`) approximates `cpu_count()` — never oversubscribing — while reserving headroom for the OS / parent process.  The `min(11, …)` cap matches the preflight phase count; the `min(4, …)` cap reflects diminishing returns past 4 (each per-package job is a few seconds).

Worked examples:

| cores | phase | package | total |
|------:|------:|--------:|------:|
|     4 |     2 |       2 |     4 |
|     8 |     3 |       2 |     6 |
|    12 |     3 |       4 |    12 |
|    16 |     4 |       4 |    16 |
|    24 |     5 |       4 |    20 |

CLI flags `--phase-workers` and `--package-workers` continue to override.

### 6. `--quiet` flag on the user-facing parallel commands

`build`, `docs`, `test`, and `preflight` gain a `--quiet` flag that forces `_QuietDispatcher` regardless of TTY.  Useful when a human wants the dump-at-end log shape (e.g. piping into a viewer that doesn't render `\r` redraws), or when an agent wants the deterministic per-phase block layout.

## Consequences

### Positive

- **Real-time output.**  The user sees phase events (`-> lint`, `[OK] lint (1.2s)`) as they happen.  No more 20-second wait staring at a blank terminal.
- **Failure-only log dump in TTY mode.**  Successful phases produce a single status line each; the failing phase's full transcript prints at the end.  Less log noise during normal preflight runs.
- **Auto-sized workers.**  A 12-core laptop now uses 12 concurrent subprocesses by default instead of 16 (oversubscribed) or 4 (under-used).
- **No more `.scratch/preflight.log` redirect workaround** — live output makes it unnecessary.
- **Phase callable shape is uniform.**  `(sink) -> int` replaces both `() -> (exit, output)` and `() -> int`; the two parallel runners collapse into one.

### Negative / tradeoffs

- **Streaming through Python is slower than direct fd writes.**  The cost is per-line Python overhead — for typical pytest / zensical / mike / ruff output (tens to hundreds of lines per phase) this is unmeasurably small (sub-millisecond), but a child that printed millions of lines would feel it.  None of our phases do.
- **Stderr/stdout interleaving order is now chronological** rather than "all stdout, then all stderr".  This is what most users expect (it matches what they'd see at a terminal), but a test that depended on the prior split-then-concat order would need updating.
- **The status-mode failure dump arrives after every parallel phase finishes**, not at the moment the failure happens.  Users who want fail-fast can use `--quiet` (which still finishes the run) or invoke the failing subcommand directly.

### Neutral

- The `--with-functional` tail of preflight is unchanged — still serial, still one-after-the-other.  Hardware contention rules out parallelizing those two.
- `docs-preview` is still serial across libraries — every `mike deploy` commits to the same `_docs-preview` git branch and would race on the index lock.  An inline comment in `docs_preview()` records the constraint.

## Alternatives considered

- **Multi-line ANSI status block (gradle-style spinner with `\r` redraws).**  Deferred — single-line "phase event" output uses no cursor escapes, so it works in tmux / screen / VS Code's integrated terminal, and gives the user enough information.  If a future ADR adds a multi-line block, the dispatcher abstraction supports it as a new implementation.
- **Periodic "still running" heartbeat lines.**  Considered for status mode (`  ⏳ test (python 3.13) [running 30s]` every 10s), deferred as YAGNI.  The phase_started / phase_done deltas already tell users something is alive.
- **`--stream` flag forcing interleave mode regardless of TTY.**  Considered, deferred.  The TTY-vs-not selection covers the natural cases; if someone wants prefixed lines in a TTY, redirecting stdout to a pipe achieves it.
- **Dropping subprocess re-invocation entirely** (calling Python-level phase functions in threads).  Considered, rejected.  Per-phase process isolation has independent value (OOM containment, import-time crash isolation) that this ADR preserves.  `test_all_runtimes` is the one carve-out where in-process + sink threading was simpler than the subprocess path.
