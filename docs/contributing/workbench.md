# Workbench — host-only tools

Companion to `libraries/`.  Where `libraries/` holds code that runs **on a microcontroller** (across CircuitPython, MicroPython, and CPython), `workbench/` holds code that runs **on the developer's laptop** to manage microcontroller projects — deploy tools, REPL clients, onboarding helpers.

> **Too long; just tell me where my project goes**
>
> The folder is decided by *where the installer puts the code*, not by which files the package ships.
>
> - Third parties install it and the code ends up on a microcontroller (via `circup install`, `mip install`, or `pip install` on a CPython-capable board)? → `libraries/<name>/`
> - Third parties install it and the code ends up on a laptop (`pip install` only)? → `workbench/<name>/`
> - Internal-only helper used by the mono-repo itself, not published? → `support/<name>/`
>
> A workbench package can ship on-device Python as a *data file* that its CLI deploys — that payload doesn't change the package's home.

## Why workbench exists

The `libraries/` folder means two things at once: "publishable" and "runs on all three runtimes."  That worked while every publishable package was multi-runtime.  It broke once host-only tools (deploy, repl, firmware flashers) showed up — they are publishable to PyPI, but cannot run on a device and must not go through `.mpy` compilation, cross-runtime testing, or the CircuitPython bundle.

`workbench/` cleanly separates "runs on a board" from "runs on your laptop" without forcing every reader to learn which entry in `libraries/` is secretly host-only.

Full rationale in [Decision 0032](../../plans/decisions/0032-workbench-host-tools.md).

## Three folders, three axes

| Folder | Published? | Runtime target |
|---|---|---|
| `libraries/` | PyPI **and** CircuitPython bundle | CircuitPython + MicroPython + CPython |
| `workbench/` | PyPI only | CPython only |
| `support/` | never | CPython only |

`support/` is the "mono-repo internal" escape hatch — projects like `support/test_harness/` that we share across packages but nobody outside the repo consumes.

## If you're using a workbench tool

You install it the normal Python way:

```bash
pip install chumicro-deploy chumicro-repl
```

No bundle registration, no `circup`, no `mpremote mip install`.  Workbench tools run on your laptop, not on your board.

Each workbench tool ships a CLI entry point (`python -m chumicro_deploy …` or a console script) and a matching Python API — anything you can do from the CLI you can also do programmatically, which is what lets third-party project templates build on top.

The shipped tools today:

- **`chumicro-deploy`** ([`workbench/deploy/`](../../workbench/deploy/)) — push code onto a board, probe a connected device, flash firmware (UF2 or esptool), classify failures and walk the user through fixes.
- **`chumicro-repl`** ([`workbench/repl/`](../../workbench/repl/)) — interactive serial REPL with traceback highlighting, an `mpremote`-compatible TUI, a `tail()` follow-mode for deploy orchestration, and a programmatic `ReplSession` for headless test fixtures.
- **`chumicro-workspace`** ([`workbench/workspace/`](../../workbench/workspace/)) — one-stop host CLI + Python API for ChuMicro project workspaces.  `init` clones a starter (defaults to [`ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template), Decision 0038), `setup` creates the venv and materializes the workbench-owned starters (`devices.yml` / `workspace.yml` / `secrets.toml`), and the rest of the surface owns `devices.yml` three-zone round-trip editing, single-project / `--all-devices` / `--all-projects` deploys, `repl <project>` (deploy-then-tail one-shot), `status` / `doctor` workspace-health snapshots, `new --library` / `new --from` scaffolding, path-aware `rename`, firmware URL derivation, import-graph deploys, and the deploy-time config-merge pipeline that produces `/runtime_config.msgpack` (Decision 0035).  `update` re-flows tool-owned files from the canonical upstream so template evolutions reach existing workspaces without clobbering user code.
- **`chumicro-pytest-device`** ([`workbench/pytest-device/`](../../workbench/pytest-device/)) — pytest plugin that intercepts collection under `functional_tests/`, stages your library + test source onto a connected CP / MP board via `chumicro-deploy`, runs the test in the device runtime, and surfaces the on-device outcome to host-side pytest.  Auto-registers via the `pytest11` entry point — no `pytest_plugins = […]` line needed.  Reads device targets from `devices.yml`.

All four consume the same `devices.yml` schema (owned by `chumicro_deploy.config.default.load_devices_yml`) so a single workspace file points every tool at the same boards.

## If you're adding a workbench tool

Workbench packages share the per-library conventions with `libraries/`:

- `pyproject.toml` + `VERSION` (SemVer)
- `src/<package_name>/` source layout
- `tests/` with the 94 % coverage gate (Decision 0025)
- f-strings, PEP 604/585 annotations (Decision 0021), descriptive names (Decision 0022)
- Constructor injection for injected dependencies (Decision 0010) where relevant
- Lint via `python scripts/run.py lint`, tests via `python scripts/run.py test --libraries <name>`

### Release lifecycle — same as libraries

Workbench packages go through the same release flow as libraries, minus the bundle steps:

- Every change that touches a workbench package bumps its `VERSION` (SemVer).  `check-version` catches forgotten bumps.
- `check-api` gates API-breakage the same way it does for libraries.
- On every VERSION bump on `main`, the workbench package publishes to PyPI under its **experimental** name (e.g. `chumicro-deploy-experimental`).
- Promotion to **stable** publishes the base name (`chumicro-deploy`) — same `promote.yml` flow libraries use, same stable/experimental channel discipline.
- No bundle staging, no `.mpy` compilation, no `ChuMicro-Bundle` publishing.  Those exist for CircuitPython / MicroPython consumers; workbench tools don't have those consumers.

### Docs — same as libraries

Workbench packages ship the same `mkdocs.yml` + `docs/` layout as device libraries (Zensical + mkdocstrings + mike-versioned pages at `https://chumicro.github.io/ChuMicro/<package>/`).  Build locally with `python scripts/run.py docs --libraries <name>` — the `discover_doc_dirs` helper picks up workbench packages the same way it picks up libraries, and griffe + 94 % coverage gates apply identically.

### Differences from libraries at a glance

- **Host-side `functional_tests/`, not on-device** — workbench tools are the project *driving* devices from the host, not code running on a device.  A workbench package can still ship a `functional_tests/` directory for host-side tests that happen to touch hardware (e.g. [`workbench/deploy/functional_tests/`](../../workbench/deploy/functional_tests/) covers the deploy happy paths against a real board through the public `chumicro_deploy` API).  The root `conftest.py` excludes these from default host collection the same way it does for library functional tests; run them with `python scripts/run.py test-workbench-functional` (the workbench counterpart to `test-libraries-functional`).  Each suite's own `conftest.py` owns device selection — typically by reading `devices.yml` defaults — so the runner itself needs no runtime/device flags.
- **No cross-runtime tests** — you don't run `test-micropython` or `test-circuitpython`.  Workbench packages target only CPython.
- **No `.mpy` compilation, no bundle staging** — workbench packages do not appear in `ChuMicro-Bundle` or `ChuMicro-Bundle-Experimental`.
- **Third-party CPython dependencies are fine** — `pyserial`, `pyyaml`, `rich`, whatever you need.  `libraries/` avoids them because a CPython-only dep can't be `import`ed on a device; workbench doesn't target devices, so the constraint never applied.  Dependency declarations never flow through `circup` or `mpremote` regardless — both bundle tools copy source files per manifest, they do not resolve `pyproject.toml` deps.

## What if my package has both host code and a tiny device shim?

Ship the device shim as a **data file** inside your workbench package and have the host CLI deploy it.  The shim is payload, not an installable package — nobody `pip install`s or `circup install`s it on its own.  So the workbench folder is still the right home.

Example: `chumicro-workspace` ships a host CLI plus a small on-device `workspace_runtime` boot module.  The boot module lives inside the workbench package as a data file; `chumicro-workspace deploy` writes it onto the board at deploy time.  One PyPI package, one VERSION, no bundle entry — and no file-level "platforms" marker trying to do work it wasn't designed for.

Only split into a separate `libraries/` entry if a real third-party demand appears for installing the on-device piece independently of the host CLI.  That demand is speculative for every case we know of today.

See the workspace package sequencing in [`plans/workstreams/project-workspace.md`](../../plans/workstreams/project-workspace.md) for the worked example.

## See also

- [Decision 0032](../../plans/decisions/0032-workbench-host-tools.md) — full rationale and alternatives
- [`docs/contributing/new-library.md`](new-library.md) — scaffolding a device-capable library
- [`AGENTS.md`](../../AGENTS.md) — workspace structure rule, file routing table
