## Prompt: Rebuild the Chumicro workspace from the current proven shape

Use this prompt when the workspace needs to be recreated or re-established from a sparse starting point.

### Goal

Rebuild the smallest Chumicro workspace that preserves the currently proven architecture:

- mono-workspace layout
- root shared tooling
- planning documents under `plans/`
- `support/runtime/`
- `support/test_harness/`
- `sample/` as the first publishable timing-first library
- CI that runs lint, tests, coverage, and a sample package build

### Required repo shape

```text
chumicro/
├── ci/
│   ├── prepare_micropython.py
│   ├── prepare_circuitpython.py
│   ├── run_sample_device_smoke.py
│   ├── run_sample_device_tests.py
│   └── tasks.py
├── .github/workflows/ci.yml
├── Agents.md
├── devices.example.yml
├── pyproject.toml
├── README.md
├── plans/
│   ├── README.md
│   ├── roadmap.md
│   ├── next-up.md
│   ├── decisions/
│   ├── prompts/
│   └── workstreams/
├── support/
│   ├── runtime/
│   └── test_harness/
└── sample/
    ├── pyproject.toml
    ├── VERSION
    ├── README.md
    ├── doc/
    ├── src/chumicro_sample/
    ├── tests/
    └── device_tests/
```

### Required decisions to preserve

1. Use a mono-workspace with individually publishable packages.
2. Use per-library checked-in `VERSION` files as the canonical published version, with PR checks enforcing required edits.
3. Treat CPython-hosted tests as the default path, with simulation/emulation preferred before real-device execution.
4. Use an Option B sample library: mostly pure logic plus one small hardware-facing seam.
5. Keep the first seam as timing/ticks; defer digital I/O until after the timing contract is proven.
6. Use WSL2 as the supported Windows path for unix-port validation.
7. Keep `ci/run_sample_device_smoke.py` as the canonical shared compatibility smoke runner in the current workspace phase.

### Required implementation slices already proven

1. `support/runtime/` exists and has CPython tests.
2. `support/test_harness/` provides a minimal `run_module()` runner for `device_tests/`.
3. `sample/` provides:
   - `Heartbeat`
   - cross-runtime `ticks_ms()` / `ticks_diff()` helpers
   - host-side tests
   - at least one device-facing timing test
4. Root CI runs:
   - shared task entrypoints in `ci/tasks.py`
   - Ruff lint
   - PyTest with coverage
   - sample package build
5. The workspace can prepare pinned repo-local MicroPython and CircuitPython unix-port runtimes via `ci/prepare_micropython.py` and `ci/prepare_circuitpython.py` and run the shared smoke test through `ci/tasks.py test-micropython-compat` and `ci/tasks.py test-circuitpython-compat`.
6. The root CI workflow keeps host checks required and runs advisory runtime compatibility jobs.

### Verification commands

```zsh
cd /path/to/chumicro
python ci/tasks.py lint
python ci/tasks.py test-host
python ci/tasks.py build-sample
python ci/tasks.py prepare-micropython
python ci/tasks.py test-micropython-compat
python ci/tasks.py prepare-circuitpython
python ci/tasks.py test-circuitpython-compat
```

### Rebuild rules

1. Keep changes minimal and match the existing workspace style.
2. Preserve the planning model instead of inventing new planning abstractions.
3. Do not skip decision records when you change a meaningful direction.
4. Update `plans/next-up.md` and `plans/roadmap.md` after major workspace changes.
5. Keep prompts in `plans/prompts/` focused on rebuild context or workspace history, not general scratch notes.

