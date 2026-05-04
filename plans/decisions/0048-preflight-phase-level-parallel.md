# Decision 0048: Phase-level parallelism for `preflight`

Status: `accepted`
Date: `2026-05-03`
Related: Decision 0025 (coverage threshold), commit `ffe50bc`
(Bucket 3 — per-package fan-out for `build` and `docs`),
commit `cb4efa9` (older 2-thread MP/CP fan-out inside `test_all_runtimes`)

## Context

`scripts/run.py preflight` is the local mirror of the CI matrix —
agents and humans run it before every commit.  It currently runs
**11 phases serially** in this fixed order:

```
lint → build → docs → test (cpython) → test-scripts →
verify-examples → check-dep-graph → check-version → check-api →
test-micropython → test-circuitpython
```

After Bucket 3 (commit `ffe50bc`) parallelized per-package fan-out
*within* `build` and `docs`, the wall-time floor on a clean Apple
Silicon laptop sits at about 30 s.  The biggest contributors are
`test (cpython)` (~22 s), `test-circuitpython` (~25 s including the
unix-port warm-up), `test-micropython` (~15 s), and `test-scripts`
(~3 s).  Those four phases are the long pole — every other phase
finishes in under 3 s.

The phases are already independent of each other in terms of
filesystem state: each writes to its own scoped output (`dist/`,
`site/`, coverage cache, runtime-specific test runners) and reads
from the same source tree.  The ordering is purely a UX choice —
"lint first because that's the fastest signal" — not a correctness
requirement.

This ADR makes the phase loop run concurrently while preserving
the on-screen log shape (lint output appears first, etc.).

## Decision

### 1. Phase DAG: every phase runs in parallel

All 11 phases are independent and can fan out concurrently.
There is no DAG between them — each is a self-contained subprocess
re-invocation of `python scripts/run.py <subcommand>`.

The `--with-functional` extension (`test-libraries-functional` and
`test-workbench-functional`) **stays serial after the parallel
block**.  Both phases drive the same physical hardware via
`devices.yml` defaults; running them concurrently would deadlock
on board access.

### 2. Submission order = log replay order

Phases are submitted in the same order the existing serial
`preflight` runs them, and `_run_capture_phases_in_parallel`
(commit `ffe50bc`) replays each phase's captured output in
**submission order** under its `== <phase> ==` header once all
phases complete.  The on-screen log reads as if the loop had run
serially, so a user scanning for "lint" or "test-circuitpython"
finds them in the expected slots.

This preserves the "lint-first signal" UX even though, in
wall-clock terms, lint may have finished while test-circuitpython
was still warming up.

### 3. Mechanism: subprocess re-invocation

Each phase runs as `subprocess.run([PYTHON, "scripts/run.py", <subcommand>, *flags], capture_output=True, text=True)`.  Subprocess (rather than in-thread `redirect_stdout`) because most phase output comes from child processes that write to the parent's stdout fd directly, which `redirect_stdout` cannot intercept; subprocess re-invocation gives each phase its own pipe-backed stdout that the helper can collect deterministically.

Subprocess re-invocation requires every phase to be reachable as a top-level CLI subcommand.  `check-dep-graph` was registered as a phase callable but not as a CLI subcommand; this ADR's implementation adds the missing subparser.  The `test` subcommand also gains a `--elevated-packages NAMES` CSV flag so preflight can preserve its "elevated-coverage-only-on-changed-libraries" behavior across the subprocess boundary — internal flag, preflight is the only caller.

### 4. Cancel-on-first-failure: not in this ADR

The default is **run-everything-and-collect-failures**.  When a
phase fails, the parallel block keeps running the remaining
phases; the final exit code is the first non-zero phase in
submission order (matching `_run_capture_phases_in_parallel`'s
existing behavior).

This is more useful than fail-fast in the local-preflight case:
CI runs every phase regardless, and the agent / human running
preflight wants to see all the things that need fixing before
committing — not just the first one.

`--fail-fast` is **deferred to a future ADR**, not included here.
Reasons:

- `concurrent.futures.ThreadPoolExecutor` does not cleanly cancel
  running futures — the only effect of `Future.cancel()` is to
  remove not-yet-started futures from the queue.
- Most phases shell out to subprocesses we'd need to actively
  terminate, complicating the helper.
- The marginal value (kill 25 s of remaining work after lint
  fails) is dwarfed by the value of finishing everything.

If a user really wants fail-fast semantics, the existing serial
loop is one revert away.

### 5. Concurrency cap: 4 workers default, CLI-flag override

Default cap: **4 concurrent phases**.

Reasoning: each phase already fans out internally —

- `build` runs 4-way per-package fan-out (Bucket 3,
  `_DEFAULT_PACKAGE_PARALLEL_WORKERS = 4`)
- `docs` runs 4-way per-package fan-out
- `test (cpython)` invokes pytest, which can use multiple cores
  internally
- `test-micropython` / `test-circuitpython` shell out to the
  unix-port binaries

11 phases × 4 internal workers = up to 44 concurrent subprocesses
without a phase-level cap.  4 phase-level workers keeps the laptop
responsive at ~16 concurrent subprocesses peak.

Override via CLI flags:

```
python scripts/run.py preflight --phase-workers 8 --package-workers 8
```

`--phase-workers` caps concurrent phases.  `--package-workers`
caps the per-package fan-out *inside* phases that fan out by
package (`build`, `docs`, `test`); `preflight` forwards it as
`--package-workers` to those subcommands and as `--max-workers`
to `check-api`.  A 16-core CI runner can crank both up; a 4-core
laptop can drop both to 2.  Both flags also exist on the
individual subcommands when invoked directly
(`python scripts/run.py build --package-workers 8`,
`python scripts/check_api.py --max-workers 8`).

### 6. Helper reuse

Reuse the Bucket 3 helper `_run_capture_phases_in_parallel` (commit `ffe50bc`) as-is — it already implements submission-order replay of captured output.  The older 2-thread `_run_phases_in_parallel` stays where it is (used by `test_all_runtimes`); deprecation is out of scope.

## Consequences

### Positive

- Wall time drops from ~31 s to roughly the longest single phase.
  Measured on a clean 12-core Apple Silicon laptop with
  `--coverage-threshold 94`: **31.2 s → 20.7 s, a 34 % reduction**.
  The longest phase is `test-circuitpython` (the unix-port
  cross-runtime suite, ~20 s); everything else completes inside
  that window.
- The log shape stays familiar — phase headers in the same order,
  output appearing under each header.
- One internal CLI surface addition (`--elevated-packages` on
  `test`, `check-dep-graph` as a top-level subcommand); no changes
  to the `preflight` external surface.
- The implementation is small: replace a `for` loop with a list
  of `(label, subcommand_args)` specs that get wrapped by a
  subprocess factory, then dispatched through
  `_run_capture_phases_in_parallel`.

### Negative / tradeoffs

- Subprocess re-invocation adds Python-startup overhead (~0.1-0.2 s)
  per phase.  At 11 phases that's ~1-2 s of overhead.  Net win
  is still large because the concurrency saves far more than
  startup costs.
- A failing phase no longer aborts the run early — the user waits
  for the slowest phase to finish before seeing the failure
  banner.  This is intentional (see §4) but is a UX change.
- Existing tests that monkeypatch Python-level phase callables
  (e.g. `monkeypatch.setattr(run, "lint", lambda: 0)`) no longer
  short-circuit — subprocess re-invocation runs the real phase.
  The one affected test
  (`test_preflight_with_functional_appends_functional_phases`)
  is updated to monkeypatch the new
  `_preflight_run_parallel_phases` helper instead.

### Neutral

- `check-version` / `check-api` still skip when `origin/main` is
  unreachable — the skip happens in the parent before the phase
  is added to the list, so the parallel block never sees them.
- The `--with-functional` tail is unchanged: still serial, still
  one-after-the-other.  Hardware contention rules out
  parallelizing those two.

## Alternatives considered

- **Thread-local `sys.stdout` proxy.** Rejected: most phase output comes from child subprocesses that write to the actual fd, not `sys.stdout` — the proxy would catch only a tiny fraction.
- **Capture inside `run_command`.** Rejected: invasive change to a helper used by dozens of paths, many of which depend on streaming output to the user (e.g. `docs --serve`).
- **`multiprocessing.Pool`.** Rejected: heavier than threads for work that's already subprocess-bound at the phase level.
- **CI YAML matrix change.** Out of scope — this ADR is about the local `preflight` command.
