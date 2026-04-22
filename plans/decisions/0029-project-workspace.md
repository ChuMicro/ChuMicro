# Decision 0029: Project workspace shape

Status: `proposed`
Date: `2026-04-21`
Related: Decision 0026, Decision 0027, Decision 0028

## Context

Decision 0028 earmarked a future `chumicro-deploy` pip package plus a "companion project template repo" for deploying user projects.  Design conversation expanded that scope into a full project workspace: onboard a board, write app code, deploy to one or many targets, and watch the REPL.  A prior user attempt (`pythonProject3`) and an ecosystem survey (`micropy-cli`, `belay`, `PlatformIO`) confirmed the gap — no existing tool unifies CP + MP + CPython at project scope with multi-board support, shared config, and a cross-runtime test story.

This decision records the non-obvious tradeoffs that shape the workstream.  The phases, library sequencing, and acceptance criteria live in `plans/workstreams/project-workspace.md`.

## Decisions

### 1. Template repo with a local `run.py`, not an installed global CLI

The workspace is a git repo (or zip) containing `run.py`, configuration files, and an empty `things/` directory.  `run.py setup` prepares a local `.venv` with pinned tooling; every workflow command is `python run.py <cmd>`.  `run.py` is a thin shim over a published library (`chumicro-workspace-runtime`) so updates reach existing workspaces via `run.py upgrade`.

A `python run.py new <thing>` scaffolding helper is allowed — it is a `cp -r things/_template` convenience, not a code generator.

**Rejected:** a globally pip-installed `chum` CLI.  PATH burden, install wall, and version skew against the template.

### 2. Things are folders.  No type categorization.

A "thing" is a folder under `things/`.  Creating one is `cp -r things/_template things/<name>` (or `python run.py new <name>`).  Things do not declare a category at creation time; `thing.yml` declares `runtimes:` and an explicit `libraries:` manifest.

**Rejected:** `--type sensor|controller|headless` flags at creation.  Premature categorization; real things blur.

### 3. `code.py` is a checked-in delegator, not codegen

The template ships a stable `code.py`:

```python
# code.py — shipped by template; do not edit.
import workspace_runtime
workspace_runtime.boot()
```

Boot reads a tiny `active.py` written at deploy time and imports the matching `things/<name>/app.py`.  No jinja, no regeneration.

**Rejected:** a generated `code.py` with a `chum eject` escape hatch.  Users get confused when their edits get overwritten; eject adds surface area without earning it.

### 4. Device identity is UID, not port

`devices.yml` caches `address:` but the source of truth is `hardware.uid:` (`microcontroller.cpu.uid` on CP, `machine.unique_id()` on MP).  Boards without a usable UID get a workspace-generated UUID written to `/chumicro_device.json` at onboard.  Deploy resolves UID first, then updates the cached address silently on port drift; UID mismatch fails loudly.

**Rejected:** port-keyed identity.  Unreliable on boards without a unique iSerial — macOS reassigns the same `/dev/cu.usbmodem<N>` to different boards in the same root port.

### 5. Firmware URLs are derived, not cataloged

- **CircuitPython:** list the Adafruit S3 bucket via `?prefix=bin/<board_id>/`, parse XML, pick latest stable.  Zero catalog maintained.
- **MicroPython:** scrape `micropython.org/download/` monthly, cache a small machine-string → BOARD map.  Prompt the user for a URL on cache miss and cache it in `devices.yml`.
- **Vendor forks / custom:** `hardware.firmware_source` accepts any URL or local path.

A small per-chip-family reflash table (`esp32* → esptool`, `rp2040/rp2350/nrf52840/samd51 → uf2`, `stm32 → dfu`) ships with `chumicro-workspace-runtime`.

**Rejected:** a per-board firmware catalog hosted by the project.  Unbounded maintenance burden.

### 6. Deploy is import-graph-driven

`python run.py deploy <thing>` AST-parses the thing's entrypoint, walks imports transitively into `libs/` (checked-in, user-authored) and `packages/` (gitignored, resolved from manifest), and copies only reachable files to `/lib/` on the device.  `thing.yml`'s `libraries:` list is a sanity-check assertion against the computed graph.

**Rejected:** a blanket `shared/` folder copied to every board.  Wastes flash, pollutes namespaces.

### 7. Local library overrides via `library_sources:`

`workspace.yml` accepts a `library_sources:` map of package name (or mono-repo root) to local path.  Resolution order: explicit single-package override → mono-repo auto-discovery → published source → error.  `run.py sync` does a `pip install -e <path>` into `.venv` for the CPython side (reuses the Decision 0026 editable-install pattern); device deploy reads source directly from the local path.

**Rejected:** published-only resolution.  Blocks chumicro developers from dogfooding library changes against a downstream workspace.

### 8. `chumicro-deploy` stays workspace-agnostic and plugin-shaped

The deploy package must be usable three ways: by the chumicro mono repo's existing test orchestration, by the chumicro-workspace-template, and by third parties building their own project templates that do not adopt workspace conventions.

Consequences for the API shape:

- Nothing from `workspace.yml`, `things/`, `library_sources:`, `packages/`, or `libs/` leaks into the deploy package.  Those concepts live in `chumicro-workspace-runtime`.
- Transports, file sources, and config loaders are pluggable protocols, not hard-coded to chumicro file layouts.
- Convenience readers for the chumicro-shaped `devices.yml` live behind an opt-in import (`chumicro_deploy.config.chumicro`), never at the top level.
- Third parties register custom config loaders via Python entry points (`chumicro_deploy.config_loaders`), not by subclassing workspace internals.
- The CLI (`python -m chumicro_deploy`) is a thin wrapper over the Python API — every CLI action has a supported programmatic equivalent.

**Rejected:** tight coupling to `chumicro-workspace-runtime`.  Deploy is a reusable primitive; the workspace is one consumer among several.

### 9. `devices.yml` zones

Three commented zones: user-owned (never overwritten without `--force` or prompt, except cached `address:`), hardware-once (written on first probe, prompt before later overwrite), probed-always (fully tool-owned, regenerated freely).  The tool preserves user comments and field ordering on round-trip.

**Rejected:** a single tool-owned file.  User edits would be destroyed.  **Rejected:** two separate files (user vs tool).  Splits context unhelpfully.

## Consequences

- Five new libraries land in this repo: `chumicro-deploy`, `chumicro-repl`, `chumicro-wifi`, `chumicro-mqtt`, `chumicro-workspace-runtime`.  `chumicro-settings` (already planned) is the sixth assumed-necessity.
- `chumicro-workspace-template` is a new companion repo.
- `devices.yml` gains three-zone structure; existing chumicro use (device testing) remains compatible — new fields are additive.
- A monthly scrape-and-cache job is needed for MicroPython BOARD names; the reflash family table is shipped and versioned with `chumicro-workspace-runtime`.
- Decision 0028's "project template repo" is promoted from parenthetical future work to a top-line deliverable governed by this decision and its workstream.
- No code lands from this ADR.  Hard rules in `AGENTS.md` land alongside the libraries as they are built.
- Execution plan, phases, library sequencing, acceptance criteria: `plans/workstreams/project-workspace.md`.
