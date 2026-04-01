## Prompt: Resume Chumicro after restart

Use this prompt at the start of a new session when you need to rehydrate the workspace quickly without re-discovering the repo from scratch.

### Read these first

1. [workstream-planning.prompt.md](./workstream-planning.prompt.md)
2. [workspace-history.prompt.md](./workspace-history.prompt.md)
3. [plans/next-up.md](../next-up.md)
4. [plans/roadmap.md](../roadmap.md)
5. Accepted decisions:
   - [0001: mono-workspace layout](../decisions/0001-mono-workspace-layout.md)
   - [0002: per-library version file strategy](../decisions/0002-per-library-version-files.md)
   - [0003: test and runtime boundaries](../decisions/0003-test-runtime-boundaries.md)
   - [0004: sample library first slice](../decisions/0004-sample-library-first-slice.md)
   - [0005: Windows host path for unix-port validation](../decisions/0005-windows-wsl2-unix-port-validation.md)
   - [0006: shared import-free compatibility smoke runner](../decisions/0006-shared-import-free-compatibility-smoke-runner.md)

### Key code anchors to inspect if implementation context is needed

- `Heartbeat` in `sample/src/chumicro_sample/heartbeat.py`
- `ticks_ms()` and `ticks_diff()` in `sample/src/chumicro_sample/ticks.py`
- `runtime_name()` in `support/runtime/src/chumicro_runtime/platform.py`
- `run_module()` in `support/test_harness/src/chumicro_test_harness/runner.py`
- `main()` in `ci/tasks.py`
- `prepare_micropython()` in `ci/prepare_micropython.py`
- `prepare_circuitpython()` in `ci/prepare_circuitpython.py`
- `ci/run_sample_device_smoke.py`
- `.github/workflows/ci.yml` for the required host lane plus advisory runtime jobs

### What to produce at the start of the session

Create a short restart brief that states:

1. Current milestone status from `plans/roadmap.md`
2. Active queue from `plans/next-up.md`
3. Implemented workspace slices that already exist
4. Known intentionally incomplete areas
5. Any planning docs that must stay in sync if the next slice changes state

### Constraints to preserve

1. Keep the planning model lightweight: `roadmap + workstreams + decisions + next-up + prompts`.
2. Treat CPython-hosted tests as the default path.
3. Preserve the current first sample seam as timing/ticks unless a new decision changes it.
4. Do not claim new runtime or release capabilities unless verified from code, tests, or docs in the repo.
5. Update `plans/next-up.md`, `plans/roadmap.md`, and affected prompt files after significant planning or workspace changes.

### Current known open areas

- release automation and per-library version bump workflows
- IDE stub packaging strategy
- the second sample seam after timing/ticks
- whether the advisory MicroPython and CircuitPython CI lanes should stay optional or become protected-branch requirements
- whether the canonical import-free compatibility smoke runner should remain shared across all interpreters or split later

