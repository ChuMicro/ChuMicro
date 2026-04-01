# Next Up

## Now

- [ ] Draft the first release workflow for per-library `VERSION` file enforcement and per-library artifacts.
- [ ] Add `VERSION` ↔ `pyproject.toml` sync validation (and `__version__` in `chumicro_runtime`) to CI or release automation.
- [ ] Document contributor prerequisites by platform (macOS, Linux, Windows/WSL2) in the README.

## Next

- [ ] Define shared mocks for CPython-hosted tests.
- [ ] Define how IDE-facing stubs are packaged and published.
- [ ] Decide whether the advisory MicroPython unix-port CI job should stay optional or become part of the protected-branch policy.
- [ ] Decide whether the advisory CircuitPython unix-port CI job should stay optional or become part of the protected-branch policy.
- [ ] Decide whether CircuitPython CI should stop at the unix-port validation path for now or add import-path mocks as a second signal.
- [ ] Decide whether to keep the pinned CircuitPython `10.1.4` unix-port path as the default local runner or broaden host/runtime coverage before promoting it further.
- [ ] Decide whether to add a second, runtime-specific import smoke layer on top of the canonical shared runner from [Decision 0006](./decisions/0006-shared-import-free-compatibility-smoke-runner.md).
- [ ] Add the first real board transport tooling once a manual device execution path needs to move beyond direct local runs.
- [ ] Decide whether the next sample iteration should prove digital I/O immediately after the timing slice.
- [ ] Close stale "Feedback requested" sections in workstreams that have been answered by subsequent decisions.

## Blocked / waiting

- [ ] Choose the exact distribution path for CircuitPython packages (`circup`-compatible index/repo details).
- [ ] Confirm how MicroPython distribution should be staged in the first release iteration.
- [ ] Decide when manual-only home testbed workflows should be promoted to scheduled or protected-branch checks.

## Current host-path note

- [x] Accept `native CPython + WSL2 for unix-port validation` as the current Windows host model.
- [x] Unix ports are the standard local simulation path. Docker containers are not needed at this scale. Revisit if CI build times or contributor onboarding friction justify it.

## Done

- [x] Choose `workstreams + decisions + next-up + roadmap` as the planning model.
- [x] Save the planning prompt for later refinement.
- [x] Bootstrap the repo with root tooling, planning docs, a runtime support package, and a first CI workflow.
- [x] Keep `venv` as the current workspace path and defer `uv` until later.
- [x] Choose Option B for the sample library, with timing/ticks as the first seam.
- [x] Choose manual-only hardware workflows for the initial phase.
- [x] Implement the first `sample/` package as a timing-first Option B proof.
- [x] Add the first lightweight `support/test_harness/` scaffold for device tests.
- [x] Add repo-level CI coverage for the runtime package, test harness, and sample package.
- [x] Add `plans/prompts/` for saved planning prompts and workspace build-up history.
- [x] Expand `plans/prompts/` with current-state, rebuild, and history prompts.
- [x] Add a restart-time resume prompt under `plans/prompts/`.
- [x] Add shared repo-level task entrypoints for `lint`, `test-host`, `build-sample`, `test-micropython-compat`, `test-circuitpython-compat`, and `test-device`.
- [x] Add the first compatibility runner scaffold for the `sample/` package using `ci/run_sample_device_tests.py`.
- [x] Add `devices.example.yml` and document the first manual device-run workflow.
- [x] Add a repo-managed `prepare-micropython` path that builds a pinned MicroPython unix-port runtime under `.tools/`.
- [x] Exercise the checked-in `test-micropython-compat` path successfully with the prepared local MicroPython unix-port binary.
- [x] Add a single `test-runtime-matrix` entrypoint for the currently proven CPython + MicroPython path.
- [x] Add a repo-managed `prepare-circuitpython` path and replace the CircuitPython placeholder with a real local build-and-run compatibility entrypoint.
- [x] Add advisory CI jobs for `test-micropython-compat` and `test-circuitpython-compat`.
- [x] Choose `ci/run_sample_device_smoke.py` as the canonical shared compatibility smoke runner and keep `ci/run_sample_device_tests.py` as a compatibility wrapper.
- [x] Evaluate CircuitPython `ports/unix/` as a concrete local build/import path without treating it as committed CI scope yet.
- [x] Fix CI compat jobs to actually prepare unix-port binaries before running smoke tests.
- [x] Fix `test-micropython-compat` to auto-prepare like `test-circuitpython-compat`.
- [x] Expand `test-runtime-matrix` to include CircuitPython (CPython + MicroPython + CircuitPython).
- [x] Add `setup` and `preflight` tasks to `ci/tasks.py`.
- [x] Add `VERSION` files for `support/runtime/` and `support/test_harness/`.

