## Prompt: Refresh Chumicro planning from the current workspace state

Use this prompt when a future session needs to rebuild planning context without rediscovering what has already been implemented.

Chumicro is a mono-workspace for Python libraries that target CPython, MicroPython, and CircuitPython, as described in [Agents.md](../../Agents.md). Keep the planning model lightweight: `roadmap + workstreams + decisions + next-up + prompts`. Avoid formal epics/stories unless a workstream actually needs them.

### Current verified workspace state as of 2026-03-29

1. Planning structure exists under [plans/](../README.md), including:
   - [roadmap.md](../roadmap.md)
   - [next-up.md](../next-up.md)
   - `workstreams/`
   - [decisions/](../decisions/README.md)
   - [prompts/](./README.md)
2. Accepted decisions already recorded:
   - [0001: mono-workspace layout](../decisions/0001-mono-workspace-layout.md)
   - [0002: per-library version file strategy](../decisions/0002-per-library-version-files.md)
   - [0003: test and runtime boundaries](../decisions/0003-test-runtime-boundaries.md)
   - [0004: sample library first slice](../decisions/0004-sample-library-first-slice.md)
   - [0005: Windows host path for unix-port validation](../decisions/0005-windows-wsl2-unix-port-validation.md)
   - [0006: shared import-free compatibility smoke runner](../decisions/0006-shared-import-free-compatibility-smoke-runner.md)
3. Implemented code slices already exist:
   - `support/runtime/` for reusable runtime detection support
   - `support/test_harness/` for a tiny on-device test runner scaffold
   - `sample/` as the first publishable timing-first sample library
   - `ci/tasks.py` for shared repo-level task entrypoints
   - `ci/prepare_micropython.py` for repo-managed MicroPython runtime preparation
   - `ci/prepare_circuitpython.py` for repo-managed CircuitPython runtime preparation
   - `ci/run_sample_device_smoke.py` as the canonical runtime-switchable sample smoke script, with `ci/run_sample_device_tests.py` kept as a wrapper
   - `.github/workflows/ci.yml` for required host checks plus advisory runtime compatibility jobs
4. The sample library proves the first Option B seam:
   - `Heartbeat` logic in `sample/src/chumicro_sample/heartbeat.py`
   - cross-runtime tick helpers in `sample/src/chumicro_sample/ticks.py`
   - host-side tests in `sample/tests/`
   - a device-facing timing test in `sample/device_tests/test_heartbeat_ticks.py`
5. Verified local commands from this workspace state:
   - `python ci/tasks.py lint`
   - `python ci/tasks.py test-host`
   - `python ci/tasks.py build-sample`
   - `python ci/tasks.py prepare-micropython`
   - `python ci/tasks.py test-micropython-compat`
   - `python ci/tasks.py prepare-circuitpython`
   - `python ci/tasks.py test-circuitpython-compat`
   - `python ci/tasks.py test-runtime-matrix`

### What is already done

1. The workspace bootstrap milestone is complete.
2. The planning model is established and should be preserved.
3. `venv` remains the documented development path for now.
4. Manual-only hardware workflows are the current starting point.
5. The first sample slice is timing/ticks, with digital I/O explicitly deferred as the likely next seam.
6. `plans/prompts/` exists specifically to preserve useful prompts for rebuilding context and tracking workspace build-up history.
7. `devices.example.yml` exists as the first committed template for manual local board registration.

### What is still intentionally incomplete

1. Real board transport tooling beyond the current manual-only documentation.
2. Release automation and per-library version bump workflows.
3. IDE-facing stub packaging strategy.
4. The second sample seam after timing/ticks.
5. Whether the advisory runtime compatibility jobs should remain optional or become protected-branch requirements.

### How to use this prompt

1. Re-read [roadmap.md](../roadmap.md) and [next-up.md](../next-up.md) before changing plan state.
2. Treat existing accepted decisions as constraints unless there is a new reason to revisit them.
3. Update planning docs to reflect reality rather than aspiration.
4. Prefer small, verified steps that preserve the current workspace shape.
5. If you add or complete a significant planning-related slice, update `next-up.md`, `roadmap.md`, and any affected prompt files so future sessions inherit the current truth.


