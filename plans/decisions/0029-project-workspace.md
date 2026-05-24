# Decision 0029: Project workspace shape

Status: `accepted`
Date: `2026-04-21`
Summary: Workspace template repo with local `run.py`; projects are folders under `projects/`; device identity is UID not port; deploy is import-graph-driven; `chumicro-deploy` stays workspace-agnostic.
Related: Decision 0026, Decision 0027, Decision 0028, Decision 0030, Decision 0031, Decision 0046 (supersedes §1 default layout + §7 resolution order)

## Context

Decision 0028 earmarked a future `chumicro-deploy` pip package plus a "companion project template repo" for deploying user projects.  Design conversation expanded that scope into a full project workspace: onboard a board, write app code, deploy to one or many targets, and watch the REPL.  A prior user attempt (`pythonProject3`) and an ecosystem survey (`micropy-cli`, `belay`, `PlatformIO`) confirmed the gap — no existing tool unifies CP + MP + CPython at project scope with multi-board support, shared config, and a cross-runtime test story.

This decision records the non-obvious tradeoffs that shape the workstream.  The phases, library sequencing, and acceptance criteria live in `plans/workstreams/archive/project-workspace.md`.

## Decisions

### 1. Template repo with a local `run.py`, not an installed global CLI

The workspace is a git repo (or zip) containing `run.py`, configuration files, and an empty `projects/` directory.  `run.py setup` prepares a local `.venv` with pinned tooling; every workflow command is `python run.py <cmd>`.  `run.py` is a thin shim over a published library (`chumicro-workspace`) so updates reach existing workspaces via `run.py upgrade`.

A `python run.py new <project>` scaffolding helper is allowed — it is a `cp -r projects/_template` convenience, not a code generator.

**Rejected:** a globally pip-installed `chum` CLI.  PATH burden, install wall, and version skew against the template.

### 2. Projects are folders.  No type categorization.

A "project" is a folder under `projects/`.  Creating one is `cp -r projects/_template projects/<name>` (or `python run.py new <name>`).  Projects do not declare a category at creation time; `project.yml` declares `runtimes:` and an explicit `libraries:` manifest.

**Rejected:** `--type sensor|controller|headless` flags at creation.  Premature categorization; real projects blur.

### 3. `code.py` is a checked-in delegator, not codegen

The template ships a stable `code.py`:

```python
# code.py — shipped by template; do not edit.
import workspace_runtime
workspace_runtime.boot()
```

Boot reads a tiny `active.py` written at deploy time and imports the matching `projects/<name>/app.py`.  No jinja, no regeneration.

**Rejected:** a generated `code.py` with a `chum eject` escape hatch.  Users get confused when their edits get overwritten; eject adds surface area without earning it.

### 4. Device identity is UID, not port

`devices.yml` caches `address:` but the source of truth is `hardware.uid:` (`microcontroller.cpu.uid` on CP, `machine.unique_id()` on MP).  Boards without a usable UID get a workspace-generated UUID written to `/chumicro_device.json` at onboard.  Deploy resolves UID first, then updates the cached address silently on port drift; UID mismatch fails loudly.

**Rejected:** port-keyed identity.  Unreliable on boards without a unique iSerial — macOS reassigns the same `/dev/cu.usbmodem<N>` to different boards in the same root port.

### 5. Firmware URLs are derived, not cataloged

- **CircuitPython:** list the Adafruit S3 bucket via `?prefix=bin/<board_id>/`, parse XML, pick latest stable.  Zero catalog maintained.
- **MicroPython:** scrape `micropython.org/download/` monthly, cache a small machine-string → BOARD map.  Prompt the user for a URL on cache miss and cache it in `devices.yml`.
- **Vendor forks / custom:** `hardware.firmware_source` accepts any URL or local path.

A small per-chip-family reflash table (`esp32* → esptool`, `rp2040/rp2350/nrf52840/samd51 → uf2`, `stm32 → dfu`) ships with `chumicro-workspace`.

**Rejected:** a per-board firmware catalog hosted by the project.  Unbounded maintenance burden.

### 6. Deploy is import-graph-driven

`python run.py deploy <project>` AST-parses the project's entrypoint, walks imports transitively into `shared/` (checked-in, user-authored, see Decision 0046) and `packages/` (gitignored, resolved from manifest), and copies only reachable files to `/lib/` on the device.  `project.yml`'s `libraries:` list is a sanity-check assertion against the computed graph.

**Rejected:** a blanket folder copied wholesale to every board.  Wastes flash, pollutes namespaces.

### 7. Local library overrides via `library_sources:`

`workspace.yml` accepts a `library_sources:` map of package name (or mono-repo root) to local path.  Overrides take priority over every other resolution path; the full search order is documented in [Decision 0046](0046-shared-and-lazy-libraries.md) (workspace.yml overrides → `shared/` → each `libraries/<name>/src/` → `packages/` → caller-supplied extras).  `run.py sync` does a `pip install -e <path>` into `.venv` for the CPython side (reuses the Decision 0026 editable-install pattern); device deploy reads source directly from the local path.

**Rejected:** published-only resolution.  Blocks chumicro developers from dogfooding library changes against a downstream workspace.

### 8. `chumicro-deploy` stays workspace-agnostic and plugin-shaped

The deploy package must be usable three ways: by the chumicro mono repo's existing test orchestration, by the chumicro-workspace-template, and by third parties building their own project templates that do not adopt workspace conventions.

Consequences for the API shape:

- Nothing from `workspace.yml`, `projects/`, `library_sources:`, `packages/`, or `shared/` leaks into the deploy package.  Those concepts live in `chumicro-workspace`.
- Transports, file sources, and config loaders are pluggable protocols, not hard-coded to chumicro file layouts.
- The built-in `devices.yml` schema is owned by `chumicro-deploy` and read by the built-in loader at `chumicro_deploy.config.default`, registered in the loader registry under the reserved name `"default"`.  The loader is behind an opt-in import — importing it pulls in PyYAML, so consumers who only want the top-level `Device` / `Deployer` API never pay that cost.  The schema is shared across the `chumicro` mono repo, the eventual project-workspace template repo, and any third-party consumer.
- Third parties register custom config loaders via Python entry points (`chumicro_deploy.config_loaders`), not by subclassing workspace internals.  The mono repo consumes the loader via the editable-install of `workbench/deploy` so the YAML schema has a single source of truth; see the corresponding scripts-consumption principle in Decision 0032.
- The CLI (`python -m chumicro_deploy`) is a thin wrapper over the Python API — every CLI action has a supported programmatic equivalent.

**Rejected:** tight coupling to `chumicro-workspace`.  Deploy is a reusable primitive; the workspace is one consumer among several.

### 9. `devices.yml` zones

Three commented zones: user-owned (never overwritten without `--force` or prompt, except cached `address:`), hardware-once (written on first probe, prompt before later overwrite), probed-always (fully tool-owned, regenerated freely).  The tool preserves user comments and field ordering on round-trip.

**Rejected:** a single tool-owned file.  User edits would be destroyed.  **Rejected:** two separate files (user vs tool).  Splits context unhelpfully.

## Consequences

- Six new publishable packages land across `libraries/` and `workbench/` (folder split per Decision 0032; reduced from seven after Decision 0038 collapsed `chumicro-workspace-template` into `chumicro-workspace`): `chumicro-deploy` (`workbench/`), `chumicro-repl` (`workbench/`), `chumicro-wifi` (`libraries/`), `chumicro-sockets` (`libraries/`; see Decision 0031), `chumicro-mqtt` (`libraries/`), `chumicro-workspace` (`workbench/`).  `chumicro-kvstore` (already planned; formerly `chumicro-settings`, see Decision 0030) is the seventh assumed-necessity.
- The canonical workspace template ships as a **separate Git repo** (`ChuMicro/ChuMicro-Workspace-Template`, Decision 0038), not as a `_payloads/` blob inside a workbench package.  Users `git clone` it (or click "Use this template" on GitHub) and run `python3 run.py setup`; the self-bootstrapping `run.py` creates a venv and installs `chumicro-workspace`, which then owns ongoing `init` / `update` / `deploy` / `repl` / etc. commands.  Third parties fork the repo to customize.
- `devices.yml` gains three-zone structure; existing chumicro use (device testing) remains compatible — new fields are additive.
- A monthly scrape-and-cache job is needed for MicroPython BOARD names; the reflash family table is shipped and versioned with `chumicro-workspace`.
- Decision 0028's "project template repo" is promoted from parenthetical future work to a top-line deliverable governed by this decision and its workstream.
- No code lands from this ADR.  Hard rules in `AGENTS.md` land alongside the libraries as they are built.
- Execution plan, phases, library sequencing, acceptance criteria: `plans/workstreams/archive/project-workspace.md`.
