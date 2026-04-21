# Decision 0029: Project workspace shape — template repo, UID identity, zero-install CLI

Status: `proposed`
Date: `2026-04-21`
Related: Decision 0026, Decision 0027, Decision 0028

## Context

Decision 0028 earmarked a future `chumicro-deploy` pip package and a "companion project template repo" for deploying user projects.  Design conversation then expanded that scope: users who build many sensors and controllers across many boards need more than a library installer.  They need a full project workspace — onboard a board, write app code, deploy to one or many targets, and watch the REPL — with as few barriers between "plugged in the board" and "running code" as possible.

A prior user attempt at this same idea (`pythonProject3`, overlay-rsync to CIRCUITPY) failed on several axes: no stable `code.py`, no codegen, no multi-device mapping, no test story, blanket file copy, abandoned async experiments.  Ecosystem survey found no existing tool unifies CP + MP + CPython at project scope with multi-board support and shared config (`micropy-cli` is MP-only and dormant; `belay` is a decorator-based "device as library" model; `PlatformIO` is firmware-focused).  The gap is real.

Three design reversals during discussion shape this decision:

1. **No pip-installed global CLI** — PATH burden and install wall.  Entrypoint is `run.py` checked into the template (same pattern as chumicro itself).
2. **No `--type sensor|controller` flag at project creation** — premature categorization users don't want to make up front.
3. **No generated `code.py`** — template ships a small delegator that boots into the workspace runtime, not a jinja-rendered artifact the tool rewrites.

## Decision

### Template repo + local `run.py`, not pip CLI

The workspace is a git repo (or downloadable zip) containing `run.py`, configuration files, and an empty `things/` directory.  Users clone or unzip it and run `python run.py setup` once to prepare a `.venv` with pinned tooling.  Every subsequent workflow command (`deploy`, `probe`, `add-device`, `repl`, `sim`, `test`) is `python run.py <cmd>`.  There is no globally installed `chum` CLI.

`run.py` itself is a thin shim that delegates to a published library (`chumicro-workspace-runtime`).  New CLI features ship to existing workspaces via `python run.py upgrade`.

### Repo layout

```
my-workspace/
  run.py                         # thin shim, calls chumicro-workspace-runtime
  workspace.yml                  # environments, deployments, quality knobs
  devices.yml                    # device registry (see below)
  secrets.yml                    # gitignored, env-keyed creds
  AGENTS.md                      # baseline LLM guidance for user workspace
  pyproject.toml                 # dev deps, lint knobs, coverage knobs
  .pre-commit-config.yaml
  things/
    <thing-name>/
      thing.yml                  # runtimes + libraries manifest
      app.py                     # user entrypoint, exposes run()
      settings.yml               # thing-local config
      tests/                     # CPython pytest + chumicro fakes
      functional_tests/          # on-device, chumicro harness
    _template/                   # empty stub — cp -r to start
  packages/                      # gitignored, resolved from manifests
  libs/                          # checked in, user-authored local modules
  .venv/                         # gitignored
```

### Thing = folder.  No type flag.  No generator.

Creating a new thing is `cp -r things/_template things/my-new-thing`.  There is no `run.py new` command.  Things don't have categorical types.  `thing.yml` declares `runtimes: [circuitpython, micropython]` (default both) and `libraries: [...]` (explicit manifest, verified against import-graph on deploy).

### `code.py` ownership — delegator, not codegen

The template ships a stable, checked-in `code.py` that never changes:

```python
# code.py — shipped by template; do not edit.
import workspace_runtime
workspace_runtime.boot()
```

`workspace_runtime.boot()` reads a tiny `active.py` written at deploy time (one line: `THING = "back-porch"`), imports the matching `things/<name>/app.py`, and calls `run()`.  No jinja, no regeneration.  User never touches `code.py`.

### Device identity is UID, not port

macOS `/dev/cu.usbmodem<N>` paths are unstable when the same USB VID/PID boards move between ports or have no unique iSerial.  `devices.yml` caches the last-known `address:` but the source of truth for identity is `hardware.uid:` (`microcontroller.cpu.uid` on CP, `machine.unique_id()` on MP).  Boards without a usable UID get a workspace-generated UUID written to `/chumicro_device.json` at onboard time.

Deploy lookup: try cached address, probe UID, fall back to port scan + UID match across all responsive ports.  The cached address is updated silently on drift; a UID mismatch fails loudly.

### `devices.yml` zones

Three zones, clearly commented in the template:

1. **User zone** (`id`, `description`, `environment`, `address`, `runtime`, `deploy_mode`, `circuitpy_drive_path`, `serial_baudrate`) — only overwritten with an explicit `--force` flag or interactive prompt; `address:` is the one silent auto-update because port drift is routine.
2. **Hardware zone** (`hardware.uid`, `hardware.board_id`, `hardware.family`, `hardware.reflash`, `hardware.firmware_source`) — written on first probe, prompt before overwriting on subsequent probes.
3. **Probed zone** (`probed.*`) — fully tool-owned, regenerated freely on `run.py probe`.

YAML round-trips via `ruamel.yaml` so comments and ordering survive.

### Probe-on-onboard with blank-board flash

`run.py add-device` handles three board states:

- **REPL responsive** — normal path: probe, fill hardware zone, auto-generate an id like `esp32s3-a1b2c3` (family + first 6 of UID) and a placeholder description the user can rename freely.
- **REPL silent + chip detectable** (e.g. `esptool` chip_id succeeds) — prompt for CP vs MP, prompt for board_id (or paste a firmware URL), flash initial firmware, re-probe, then continue onboarding.
- **UF2 bootloader mounted** — detect drive, copy selected UF2, wait for re-enumeration.

### Firmware URL derivation — derive, don't catalog

Maintaining a per-board firmware catalog is a nightmare.  Instead:

- **CircuitPython**: list the Adafruit S3 bucket via query string (`https://adafruit-circuit-python.s3.amazonaws.com/?prefix=bin/<board_id>/&list-type=2`), parse XML, pick latest stable.  `board_id` comes directly from `board.board_id`.  No catalog maintained.
- **MicroPython**: scrape `https://micropython.org/download/` once per month, cache a small machine-string → BOARD-name map locally.  On cache miss, prompt the user for a URL and cache it in `devices.yml`.
- **Vendor forks / custom firmware**: `hardware.firmware_source` accepts any URL or local file path.  Deploy follows it.  Not our problem to catalog.

### Reflash table — small, by chip family, shipped

A per-chip-family reflash map (`esp32* → esptool`, `rp2040/rp2350/nrf52840/samd51 → uf2`, `stm32 → dfu`) ships with `chumicro-workspace-runtime`.  Small (~15 entries), grows slowly, maintainable.

### Self-upgrade with handholding

`run.py upgrade-firmware <id> [--to <version>] [--prerelease]` guides the user through bootloader entry (double-tap reset + watch for mount, or BOOT+RESET + esptool sync), flashes the selected firmware, and re-probes.

Flashing a board with user code on it requires `--approve-board-storage-reset` (explicit opt-in) to avoid accidental wipes.  Where the runtime supports it (e.g. CircuitPython `microcontroller.on_next_reset(RunMode.UF2)`), bootloader entry is triggered programmatically to eliminate the "press buttons" step.

### Deploy is import-graph-driven

`run.py deploy <thing>` AST-parses `things/<name>/app.py`, walks imports transitively into `libs/`, `packages/`, and thing-local modules, and copies only reachable files to `/lib/` on the device.  `thing.yml`'s `libraries:` list is treated as an assertion — drift against the computed graph prompts the user to update it.

Conditional cross-runtime imports (`try: import wifi; except ImportError: ...`) are captured from both branches.  Dynamic imports (`importlib.import_module(name)`) require an `extra_modules:` list in `thing.yml`.

Two lib folders, no blanket-copy `shared/`: `packages/` (gitignored, external, resolved from manifest) and `libs/` (checked in, user-authored).

### Local library overrides (dogfooding)

Chumicro developers need to iterate on a library *and* the downstream workspace at the same time — push a change to `chumicro-timing` locally, redeploy a thing, observe the effect without a publish cycle.  Workspaces also need the same hook for users who fork a library or pin to a local clone.

`workspace.yml` takes a `library_sources:` section that maps a package name (or a whole mono-repo root) to a local path:

```yaml
library_sources:
  # Mono-repo mode: point at a chumicro clone, all libraries/<name>/ auto-discovered.
  chumicro: /Users/you/circuitpython/chumicro
  # Single-package override: takes precedence over mono-repo or published source.
  chumicro-mqtt: /Users/you/forks/chumicro-mqtt-experiment
```

Resolution order for any `chumicro_*` (or other) library:

1. **Explicit `library_sources` entry** — a single-package override wins outright.
2. **Mono-repo `library_sources` entry** — auto-discover `libraries/<name>/` inside the referenced root; match by pyproject `name`.
3. **Published source** — pypi / bundle / mip into `packages/`, as usual.
4. **Missing** — deploy fails fast with a prompt to add a source.

`run.py sync` does two things per entry:

- `pip install -e <path>` into `.venv` so CPython tests and sim pick up live edits (reuses the editable-install pattern from Decision 0026).
- Record the path for device deploy so the import-graph walker reads source directly from the local clone — no file copy into `packages/`, no symlink brittleness.  The device-side file tree is built by following that path at deploy time.

Device deploy is unaffected at the wire level — files land on the board the same way; only the host-side source location differs.  Version compatibility is the user's problem when they override: if a local `chumicro-timing` clone introduces a breaking API change, downstream things that depend on the published shape will fail at deploy or runtime.

`run.py devices` / `run.py deploy` both show a clear "using local source" banner when a library is being taken from `library_sources:` rather than `packages/`, so the user never forgets they are on a fork.

### Deployments and environments

`workspace.yml`:

```yaml
environments:
  home:      { wifi_ssid: HomeNet, wifi_password: !secret home_wifi, ... }
  workshop:  { wifi_ssid: WorkshopMesh, wifi_password: !secret workshop_wifi, ... }
active_environment: home
deployments:
  "back porch": back-porch-thing
  "greenhouse": humidity-thing
default: back-porch-thing
quality:
  lint: ruff               # "ruff" | "off"
  coverage_threshold: 70   # 0–100, 0 = off
  agent_strictness: relaxed
```

`!secret name` resolves from `secrets.yml` (gitignored) at deploy time and is baked into the target-specific settings artifact (`settings.toml` for CP, a preboot module for MP, env vars for CPython sim).  Never committed.

### `chumicro-repl` — dedicated serial TUI

Existing generic terminal apps (`screen`, `mpremote`, `ampy`) are not CP/MP-aware and mishandle UTF-8, emojis, and hard-fault traceback highlighting.  A new library `chumicro-repl` wraps `pyserial` with:

- UTF-8 + emoji safe rendering
- Traceback / Safe mode / hard-fault pattern detection with color highlighting
- Key bindings matching `mpremote` (Ctrl-C stop, Ctrl-D soft reset, Ctrl-X disconnect, Ctrl-E paste mode)
- Programmatic `tail(seconds, fail_on_traceback)` API used by `run.py deploy` to stream post-deploy output and fail CI on an immediate traceback
- Useful standalone outside the workspace

### New libraries landing in this workstream

- `chumicro-workspace-runtime` — host CLI implementation + on-device `workspace_runtime` module
- `chumicro-deploy` — transport extraction (already planned in Decision 0028)
- `chumicro-repl` — serial TUI, new
- `chumicro-wifi` — non-blocking connection manager, new (assumed-necessity for sensor/controller things)
- `chumicro-mqtt` — refactor from pythonProject3's 1043-line hand-rolled client into a runner-shaped service, new
- `chumicro-settings` — already planned in next-up

### Alternatives considered and rejected

- **Global pip-installed `chum` CLI** — PATH burden, install wall, version-skew against template.  Rejected.
- **`--type sensor|controller` scaffold flags** — premature categorization; real things blur.  Rejected.
- **Generated `code.py`** — users get confused when their edits get overwritten; escape hatches (`chum eject`) add surface area.  Rejected in favor of a stable delegator.
- **Port-keyed device identity** — unreliable on boards without unique iSerial.  Replaced by UID.
- **Per-board firmware catalog maintained by us** — unbounded maintenance burden.  Replaced by live derivation from upstream sources.
- **Blanket `shared/` copy** — wastes flash and pollutes namespaces.  Replaced by import-graph deploy.
- **Published-only library resolution (no local overrides)** — blocks chumicro developers from dogfooding library changes against a workspace.  Replaced by `library_sources:` with mono-repo and single-package overrides, reusing the Decision 0026 editable-install pattern for the `.venv` side.

## Consequences

- `chumicro-workspace-template` is a new companion repo; the template is the product.
- Four new libraries land in this mono repo: `chumicro-workspace-runtime`, `chumicro-repl`, `chumicro-wifi`, `chumicro-mqtt`.  `chumicro-deploy` is the fifth, already planned.
- `devices.yml` gains three-zone structure (`user` / `hardware` / `probed`).  Existing chumicro use of `devices.yml` (for functional tests) remains compatible — the new fields are additive.
- `ruamel.yaml` becomes a dev dependency for round-trip YAML editing of `devices.yml`.
- The MP BOARD-name map requires a monthly scrape-and-cache job; the reflash family table is shipped and versioned with `chumicro-workspace-runtime`.
- No catalog of per-board firmware is hosted by the project.  Users of unsupported or custom boards paste a URL once, cached in `devices.yml`.
- Decision 0028's "project template repo" is promoted from parenthetical future work to a top-line deliverable governed by this decision.
- `plans/open-questions.md` — the first open question ("When should the transport layer be extracted into `chumicro-deploy`?") is partially resolved: the envisioned public API is `run.py deploy` (workspace) + a Python API (library surface), dependency resolution is import-graph-driven, `chumicro-project-template` exists, `.mpy` compilation remains opt-in where mpy-cross is available.  Remaining sub-questions move to this workstream's execution plan.
- `AGENTS.md` requires no new hard rules yet — this ADR captures the shape; hard rules land as the libraries are built.
- No code changes land from this ADR alone.  It sets scope and direction for a multi-library workstream.
