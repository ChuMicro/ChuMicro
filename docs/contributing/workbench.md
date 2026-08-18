# Adding a Workbench Package

<img src="../../support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Workbench packages are host-only CPython tools that ship to PyPI but never reach the device: `chumicro-deploy`, `chumicro-repl`, `chumicro-workspace`, `chumicro-pytest-device`, `chumicro-checks`.  This page documents how to add a new one and how the lifecycle differs from a [device library](new-library.md).

<br clear="left">

For what workbench is and which tools currently ship, see [`workbench/`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/).  For the design rationale behind splitting workbench from `libraries/`, see [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md).

## Conventions shared with libraries

Workbench packages follow the same per-library conventions as code under `libraries/`:

- `pyproject.toml` + `VERSION` (SemVer)
- `src/<package_name>/` source layout
- `tests/` meeting the coverage gate: the 85 % pyproject baseline, raised to 94 % on agent invocations ([Decision 0025](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0025-dual-coverage-thresholds.md))
- f-strings, PEP 604/585 annotations ([Decision 0021](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0021-docstring-type-policy.md)), descriptive names ([Decision 0022](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0022-naming-conventions.md))
- Constructor injection for injected dependencies ([Decision 0010](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0010-library-testability.md)) where relevant
- Tests via `pytest workbench/<name>/tests/` for iteration, `python scripts/run.py test --libraries <name>` for the gated run; lint via `python scripts/run.py lint`

## Scaffolding

`python scripts/run.py new-library --workbench <name>` scaffolds a workbench package from inside the mono-repo: same primitive as the library form (calls `scaffold_library` with `package_kind="workbench"`), routed to `workbench/<name>/` instead of `libraries/<name>/`, then editable-installs the package and regenerates IDE configs.  `chumicro-workspace new --workbench <name>` is the equivalent for a workspace project outside the mono-repo.

## Release lifecycle

Same as libraries, minus the bundle steps:

- Every change that touches a workbench package bumps its `VERSION` (SemVer); `check-version` catches forgotten bumps.
- `check-api` gates API-breakage the same way it does for libraries.
- On every VERSION bump on `main`, the workbench package publishes to PyPI under its **experimental** name (e.g. `chumicro-deploy-experimental`).
- Promotion to **stable** publishes the base name (`chumicro-deploy`), the same `promote.yml` flow libraries use.
- No `.mpy` compilation, no `ChuMicro-Bundle` publishing.  Those exist for CircuitPython / MicroPython consumers; workbench tools don't have those consumers.

## Docs

Same `mkdocs.yml` + `docs/` layout as device libraries (Zensical + mkdocstrings + mike-versioned pages at `https://chumicro.com/ChuMicro/<package>/`).  Build locally with `python scripts/run.py docs --libraries <name>`.  The `discover_doc_dirs` helper picks up workbench packages the same way it picks up libraries, and griffe and the coverage gate (85 % baseline, raised to 94 % on agent invocations) apply identically.

## Differences from libraries

- **Host-side `functional_tests/`, not on-device.**  Workbench tools drive devices from the host rather than running on the device.  A workbench package can still ship a `functional_tests/` directory for host-side tests that touch hardware (see [`workbench/deploy/functional_tests/`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/deploy/functional_tests/) for the deploy happy paths against a real board through the public `chumicro_deploy` API).  The root `conftest.py` excludes these from default host collection the same way it does for library functional tests; run them with `python scripts/run.py test-workbench-functional` (the workbench counterpart to `test-libraries-functional`).  Each suite's own `conftest.py` owns device selection.
- **No cross-runtime tests.**  Workbench packages target only CPython, so `test-micropython` and `test-circuitpython` don't apply.
- **No `.mpy` compilation, no bundle staging.**  Workbench packages do not appear in `ChuMicro-Bundle` or `ChuMicro-Bundle-Experimental`.
- **Third-party CPython dependencies are fine.**  `pyserial`, `ruamel.yaml`, `rich`, anything that ships on PyPI.  `libraries/` avoids them because a CPython-only dep can't be `import`ed on a device; workbench doesn't target devices, so the constraint never applied.

## Host code + a tiny device shim?

Ship the device shim as a **data file** inside the workbench package and have the host CLI deploy it.  The shim is payload, not an installable package: nobody `pip install`s or `circup install`s it on its own.  So the workbench folder is still the right home.

Example: `chumicro-workspace` ships a host CLI plus a small on-device `workspace_runtime` boot module.  The boot module lives inside the workbench package as a data file; `chumicro-workspace deploy` writes it onto the board at deploy time.  One PyPI package, one VERSION, no bundle entry, and no file-level "platforms" marker trying to do work it wasn't designed for.

Only split into a separate `libraries/` entry if a real third-party demand appears for installing the on-device piece independently of the host CLI.

## See also

- [`workbench/`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/): what workbench is, current tool list, install commands
- [Decision 0032](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0032-workbench-host-tools.md): full rationale and alternatives
- [Adding a New Library](new-library.md): the parallel guide for device libraries
- [`AGENTS.md`](https://github.com/ChuMicro/ChuMicro/blob/main/AGENTS.md): workspace structure rule, file routing table
