# Decision 0032: Workbench — top-level folder for host-only publishable packages

Status: `accepted`
Date: `2026-04-22`
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
- `chumicro-workspace-runtime` — host CLI + a companion *device-side*
  boot module (hybrid)

These packages don't fit either existing bucket.  They are publishable,
so `support/` is wrong.  They are CPython-only and must not go through
cross-runtime testing, `.mpy` compilation, or the CircuitPython
bundle — so treating them as ordinary entries in `libraries/` would
fold host-tool maintenance into the device-library release pipeline
and mislead readers who open `libraries/` expecting "runs on your
board."

`chumicro-workspace-runtime` illustrates a subtlety.  It ships a small
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
   part of its operation (e.g. `chumicro-workspace-runtime`'s on-device
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
7. Workbench packages do not have a `functional_tests/` slot — they
   either drive devices (in which case the device is under test, not
   the workbench tool in isolation) or they are pure host tools.
   Device-driving workbench packages may ship host-side tests that
   gate on `devices.yml` the same way `scripts/pytest_device.py`
   does today.
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
   (`chumicro-workspace-runtime`, others), the `scripts/` shrinks and
   the workbench shelf carries progressively more of the developer
   surface area.  Any `scripts/` file that could live in a workbench
   package instead belongs on the migration backlog in
   `plans/next-up.md`.

### Alternatives considered

- **Publish from `support/`** (relax the "support is internal" rule).
  Smallest structural diff.  Rejected — "support" as a word then stops
  meaning anything concrete, and the runtime-target separation
  readers care about stays invisible.
- **Single `libraries/` with classifiers or tier labels in
  `pyproject.toml`.** Minimal tree churn.  Rejected — readers lose
  the visual separation at browse time, and every script that scans
  `libraries/` has to learn to filter.  The separation is worth a
  folder boundary, not a metadata field.
- **Separate repo per host tool.** Strongest isolation.  Rejected —
  heavy release/CI/versioning overhead for a handful of tools that
  share the chumicro dev workflow and benefit from mono-repo testing.
- **Top-level name `tools/`, `host/`, `dock/`, `bridge/`, `console/`.**
  `tools/` is generic-safe but boring; `host/` is correct but jargon;
  `dock/` is evocative but narrower than the workspace-runtime case;
  `bridge/` and `console/` are overloaded.  `workbench/` best captures
  "where the developer works *on* the project," pairs with the
  already-used "workspace" terminology (workspace = user's project;
  workbench = tool shelf) without colliding, and scales to future host
  tools beyond the initial three.

## Consequences

- `scripts/workspace.py` discovery grows a third source folder:
  `discover_package_dirs()` must scan `workbench/` alongside
  `libraries/` and `support/`.  `discover_library_dirs()` stays
  libraries-only (used by bundle/docs/cross-runtime gates, which
  remain device-library concerns).  A new helper exposes the set of
  workbench packages when the distinction matters.
- `scripts/shared.py::install_editable()` installs workbench packages
  in editable mode the same way it already installs libraries and
  support packages.
- `scripts/check_version.py`, `check_api.py`, and lint/coverage
  checks treat workbench packages as publishable — VERSION gate,
  API-breakage gate, coverage gate all apply.
- Bundle staging (`scripts/bundle_manager.py`) and the cross-runtime
  test matrix remain scoped to `libraries/` only — workbench packages
  are skipped.
- Release pipeline has full parity minus bundle mechanics.
  `release.yml` gains a parallel workbench-wheel job that publishes
  to PyPI under `-experimental` names on every VERSION bump on
  `main`; `promote.yml` gains a parallel job that publishes the
  stable names (`chumicro-deploy`, etc.) when a workbench VERSION is
  tagged for release.  `check-version` and `check-api` gate workbench
  packages the same way they gate libraries.  Neither workflow
  touches `mpy-cross`, bundle repos, or docs deploys for workbench
  packages.
- Docs: workbench packages ship the same `mkdocs.yml` + `docs/`
  layout as device libraries (Zensical + mkdocstrings + mike for
  versioning).  `scripts/run.py docs --libraries <name>` discovers
  and builds them via the existing `discover_doc_dirs` helper; the
  versioned-docs deploy pipeline routes workbench packages the same
  way it routes libraries, onto the same `https://chumicro.github.io/
  ChuMicro/<package>/` URL space.  This matches the
  release-lifecycle parity rule (Rule 4) — workbench packages
  ship to PyPI and the docs site, just not the bundle.
- Scaffolding: `python scripts/run.py new-library <name>` stays
  device-library-shaped.  A sibling command (likely
  `new-workbench <name>`) scaffolds the host-tool variant.  Scope
  of the sibling scaffolder is TBD in the Phase 1 implementation
  slice that actually needs it — until then, the first workbench
  package (`chumicro-deploy`) can be created by hand from the
  existing lift-and-shift material under `support/device_transport/`.
- `AGENTS.md` "File routing" table and workspace-structure section
  update to name the third folder and its rule.
