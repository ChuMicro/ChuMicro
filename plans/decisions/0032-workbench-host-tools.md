# Decision 0032: Workbench — top-level folder for host-only publishable packages

Status: `accepted`
Date: `2026-04-22`
Summary: Add a third top-level folder `workbench/` for publishable CPython-only host packages; `libraries/` is cross-runtime + bundles, `workbench/` is PyPI-only, `support/` is internal.
Related: 0029 (project workspace), 0030 (config and state), 0031 (chumicro-sockets)

## Context

The workspace currently has two top-level package folders:

- `libraries/` — publishable, and (implicitly) compatible with all three
  runtimes (CircuitPython, MicroPython, CPython).  Released via the
  bundle pipeline (`.mpy` compilation, mip install) and to PyPI.
- `support/` — internal, never published.

The project-workspace workstream (Decision 0029) introduces seven new
packages.  Three of them are **host-only** — they run on the developer's
laptop and will never run on a microcontroller:

- `chumicro-deploy` — pushes code to devices (pyserial, pyyaml)
- `chumicro-repl` — interactive TUI for device REPL (pyserial)
- `chumicro-workspace` — host CLI + a companion *device-side*
  boot module (hybrid)

These packages don't fit either existing bucket.  They are publishable,
so `support/` is wrong.  They are CPython-only and must not go through
cross-runtime testing, `.mpy` compilation, or the CircuitPython
bundle — so treating them as ordinary entries in `libraries/` would
fold host-tool maintenance into the device-library release pipeline
and mislead readers who open `libraries/` expecting "runs on your
board."

`chumicro-workspace` illustrates a subtlety.  It ships a small
on-device boot module alongside the host CLI.  An early draft placed
hybrids in `libraries/` and used `[tool.chumicro].platforms` to mark
the host-only parts — but `platforms` describes runtime support for
the *package as installed*, not file-level "ships on device" tagging.
Forcing a host-CLI package into `libraries/` just because it carries a
few lines of on-device payload would saddle it with cross-runtime
tests, `.mpy` compilation, and bundle staging that none of the host
code can satisfy.

## Decision

Add a third top-level folder, `workbench/`, for publishable host-only
CPython packages.  The three folders now have clean, independent axes:

| Folder | Publishable | Runtime target |
|---|---|---|
| `libraries/` | yes — to PyPI and to the CircuitPython bundle | CP + MP + CPython |
| `workbench/` | yes — to PyPI only | CPython only |
| `support/` | no | CPython only |

### Rules

1. **The destination of the installer decides the folder.**  A package
   lives in `libraries/` when its installer (`pip install` on CPython,
   `circup install`, `mip install`) places the installed code onto a
   microcontroller.  A package lives in `workbench/` when its
   installer (`pip install`) places the installed code onto a laptop.
   Files a package ships as *payload* — data files the host CLI
   writes onto a device at deploy time, for instance — do not shift
   the package's folder.  Payload is not an installable package.
2. When a workbench package needs to deliver code onto a device as
   part of its operation (e.g. `chumicro-workspace`'s on-device
   boot module), that code ships as a data file inside the workbench
   package and the host CLI deploys it.  Only split into a separate
   `libraries/` entry if a real third-party demand emerges for
   installing the device-side piece independently.
3. Workbench packages are **not** included in the CircuitPython bundle,
   are **not** `.mpy`-compiled, and are **not** run through the
   cross-runtime test matrix.  They publish to PyPI as wheels.
4. **Workbench packages follow the same release lifecycle as
   libraries.**  Each has a `VERSION` file (SemVer), goes through the
   experimental → stable promotion flow, and publishes to PyPI under
   both a stable name (`chumicro-deploy`) and an experimental name
   (`chumicro-deploy-experimental`).  The `check-version`,
   `check-api`, lint, and 94 % coverage gates all apply.  The only
   release-pipeline difference vs libraries is the absence of bundle
   staging and `.mpy` compilation — which are CircuitPython / MicroPython
   concerns that do not apply to host-only packages.
5. Workbench packages follow the same per-package conventions as
   libraries otherwise: `pyproject.toml`, `VERSION`, `src/`, `tests/`,
   94 % coverage gate, f-strings, Decision 0021 annotation rules,
   Decision 0022 naming rules, constructor injection (Decision 0010
   still applies where relevant).
6. Workbench packages freely depend on CPython-only third-party
   libraries (`pyserial`, `pyyaml`, `rich`, etc.).  This is not a
   relaxation of anything — `libraries/` never had a hard anti-dep
   rule, just an implicit constraint: CPython-only deps cannot be
   imported on a device, so multi-runtime libraries avoid them.
   Workbench does not target devices, so the constraint does not
   apply.  Dependency declarations never flow through the bundle
   (circup and mpremote copy source files per manifest; they do not
   resolve `pyproject.toml` deps), so a workbench package's deps have
   zero effect on device-side installation.
7. Workbench packages may ship a `functional_tests/` slot for
   host-side tests that drive connected boards through the
   package's public API.  Unlike library functional tests, these
   are *not* routed through the on-device test harness — the
   workbench tool is the thing driving the device from the host,
   not code running on a device.  `scripts/run.py test-workbench-functional`
   is the counterpart to `test-libraries-functional`: it iterates every
   `workbench/<name>/functional_tests/` directory and runs plain
   pytest against each, and each suite's own `conftest.py` owns
   device selection (typically by reading `devices.yml` defaults).
8. **Scripts consume workbench packages, not the other way around.**
   When a mono-repo `scripts/` file re-implements functionality that a
   workbench package owns (YAML schema parsing, transport construction,
   device probing, firmware flashing, recovery coaching, etc.), the
   `scripts/` version migrates to import from the workbench package via
   its editable install.  Rationale: the workbench package is the
   published source of truth — if the mono repo keeps a parallel
   implementation it will drift from what external consumers see, and
   the eventual project-workspace template repo would have to choose
   between the two.  Migrations can happen in stages (schema parsing
   first, richer orchestration later); each stage moves the
   mono-repo-only surface area (test-orchestration hints, IDE-specific
   defaults) into a thin wrapper on top of the workbench package rather
   than a reimplementation of it.  As more workbench packages land
   (`chumicro-workspace`, others), the `scripts/` shrinks and
   the workbench shelf carries progressively more of the developer
   surface area.  Any `scripts/` file that could live in a workbench
   package instead belongs on the migration backlog in
   `plans/next-up.md`.

### Alternatives considered

- **Publish from `support/`** (relax "support is internal").  Rejected: "support" stops meaning anything concrete and the runtime-target separation stays invisible to readers.
- **Single `libraries/` with `pyproject.toml` classifiers or tier labels.**  Rejected: every script scanning `libraries/` has to learn to filter, and readers lose the visual separation at browse time.
- **Separate repo per host tool.**  Rejected: heavy release/CI/versioning overhead for tools that share the chumicro dev workflow and benefit from mono-repo testing.
- **Names `tools/` / `host/` / `dock/` / `bridge/` / `console/`.**  `workbench/` best captures "where the developer works *on* the project," pairs with the existing "workspace" terminology (workspace = user's project, workbench = tool shelf), and scales to future host tools.

## Consequences

- Discovery + editable-install + VERSION/API/coverage gates apply to workbench packages identically to libraries (`scripts/repo_layout.py`, `scripts/shared.py::install_editable()`, `check_version.py`, `check_api.py`).  Bundle staging and the cross-runtime test matrix stay scoped to `libraries/` only.
- Release pipeline parity minus bundle mechanics: `release.yml` publishes `-experimental` wheels on every VERSION bump; `promote.yml` publishes stable names on tag.  Neither workflow touches `mpy-cross`, bundle repos, or device deploys for workbench packages.
- Docs ship via the same Zensical + mkdocstrings + mike pipeline as libraries, on the same `https://chumicro.com/ChuMicro/<package>/` URL space.
- Scaffolding: `python scripts/run.py new-library` stays device-library-shaped; a future `new-workbench` will mirror it.  Until then, `workbench/deploy/` is the reference layout.
- `AGENTS.md`'s "File routing" table and workspace-structure section name the third folder and its rule.
