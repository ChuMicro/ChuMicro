# Workstream: Project Workspace

Status: `proposed`

## Purpose

Give users a template-repo project workspace that unifies CircuitPython, MicroPython, and CPython at project scope — onboard a board, write app code, deploy to one or many targets, and watch the REPL.  Companion to Decision 0029, which records the design tradeoffs.

## Scope

- A `chumicro-workspace-template` repo: checked-in `run.py`, `workspace.yml`, `devices.yml`, `things/_template/`, `packages/` (gitignored), `libs/`, `.venv/` (gitignored), baseline `AGENTS.md`, lint + coverage knobs, `.pre-commit-config.yaml`.
- Five new chumicro libraries: `chumicro-deploy`, `chumicro-repl`, `chumicro-wifi`, `chumicro-mqtt`, `chumicro-workspace-runtime`.  The already-planned `chumicro-settings` is an assumed-necessity but is owned by its own next-up entry, not this workstream.
- Onboarding UX: `run.py add-device` handles responsive boards, boards in UF2 bootloader, and blank chips detectable by esptool.
- Firmware install + upgrade: `run.py install-firmware`, `run.py upgrade-firmware`, `--prerelease`, `--approve-board-storage-reset`, programmatic bootloader-entry where supported.
- Local library dogfooding: `library_sources:` maps a package name or mono-repo root to a local clone; reuses the Decision 0026 editable-install pattern.

Out of scope for this workstream:

- `chumicro-settings` itself (tracked separately in `next-up.md`).
- Hot-plug daemon (`run.py watch`) — defer until requested.
- Community-contributed firmware catalog — users paste URLs into `devices.yml`; contrib path is optional future work.
- ESP32 NVS backend for settings — tracked in open-questions.

## Current verified slice

Nothing shipped from this workstream yet.  Prerequisites that already exist:

- `support/device_transport/` (MicroPython + CircuitPython transports, both deploy modes) — Decision 0027, Decision 0028.
- `devices.yml` + `device-config.yml` schemas and loaders — Decision 0027.
- `support/test_harness/` lightweight on-device runner.
- Editable-install pattern for libraries + support packages — Decision 0026.

## Library sequencing

Six libraries (five new + `chumicro-settings`) land in a deliberate order so each phase has working dependencies.

| Phase | Library | Role | Depends on |
|-------|---------|------|------------|
| 1 | `chumicro-deploy` | Extraction of `support/device_transport/` into publishable package. Public API: Python + thin CLI. | Decision 0028 transport |
| 2 | `chumicro-repl` | CP/MP-aware serial TUI. UTF-8 + emoji safe. Traceback highlighting. `tail()` API for deploy. | pyserial |
| 3 | `chumicro-settings` | Already planned, lands here in this sequencing. Dict-like persistent storage. | msgpack |
| 3 | `chumicro-wifi` | Non-blocking connection manager. CP + MP + CPython-stub. | runner, settings |
| 4 | `chumicro-workspace-runtime` | Host-side CLI implementation + on-device `workspace_runtime` boot module. | deploy, repl, settings, wifi |
| 4 | `chumicro-workspace-template` repo | The checked-in `run.py`, `workspace.yml`, `things/_template/`, scaffolding files. | workspace-runtime |
| 5 | `chumicro-mqtt` | Refactor pythonProject3's 1043-line hand-rolled client into a runner-shaped service. | runner, wifi |

Rationale: Phase 1 unblocks everything.  Phase 2 is used by Phase 4's deploy-then-tail UX.  Phase 3 is two libraries in parallel (independent).  Phase 4 is the integration phase — the CLI plus the template.  Phase 5 lands the first non-trivial thing-template (MQTT sensor) and proves end-to-end.

## Implementation phases

### Phase 1: `chumicro-deploy` extraction

Three-audience package: chumicro mono repo (replaces `support/device_transport/` callers), chumicro-workspace-template (`run.py deploy`), and third parties building their own project templates.  Decision 0029 §8 records the workspace-agnostic + plugin-shaped requirement.

#### Public API sketch

```python
# chumicro_deploy/__init__.py — top-level surface
from chumicro_deploy import Deployer, Device, DeployResult, DeployError
from chumicro_deploy.transport import TransportProtocol
from chumicro_deploy.sources import FileSource, DirectorySource, FileMapSource, ImportGraphSource
```

Device construction — explicit, dict-based, env-based, or via opt-in loader:

```python
device = Device(
    transport="circuitpython",          # "micropython" | "circuitpython" | TransportProtocol instance
    address="/dev/cu.usbmodem1101",
    baudrate=115200,
    deploy_mode="ram",                  # "ram" | "flash"
    circuitpy_drive_path=None,          # auto-detected if omitted
    entrypoint_name="code.py",          # override if the device runs something else
    resource_prefix="/lib",             # where lib files land on device
)

# Or: from a dict (third parties build it however they want)
device = Device.from_dict({...})

# Or: from env vars (MYBOARD_ADDRESS, MYBOARD_TRANSPORT, ...)
device = Device.from_env(prefix="MYBOARD_")

# Or: opt-in chumicro-shaped devices.yml loader
from chumicro_deploy.config.chumicro import load_devices_yml
devices = load_devices_yml("devices.yml")
device = devices["back porch"]
```

File sources — pluggable, not tied to chumicro layout:

```python
# Ship a pre-built dict (third party handled assembly)
source = FileMapSource({"code.py": "...", "lib/wifi.py": "..."})

# Ship a directory tree as-is
source = DirectorySource(Path("./staging"), entrypoint="code.py")

# Let the library walk imports (used by workspace-runtime; available to anyone)
source = ImportGraphSource(
    entrypoint=Path("app.py"),
    search_paths=[Path("libs"), Path("packages")],
    extra_modules=["my.dynamic.module"],
)

# Or bring your own
class MySource(FileSource):
    def files(self) -> dict[str, bytes]: ...
    def entrypoint(self) -> str: ...
```

Deploy:

```python
deployer = Deployer(device)
result: DeployResult = deployer.deploy(
    source,
    on_progress=lambda pct, msg: ...,
    on_file_staged=lambda path: ...,
    on_execute_line=lambda line: ...,
)
# result.success, result.staged_files, result.execute_output, result.traceback
```

Probe / firmware — separate modules, usable without Deployer:

```python
from chumicro_deploy.probe import probe_device, DeviceInfo
info: DeviceInfo = probe_device(device)          # runtime_version, board_id, uid, modules_available

from chumicro_deploy.firmware import resolve_firmware_url, flash_firmware
url = resolve_firmware_url(board_id="adafruit_feather_esp32s3_...", runtime="circuitpython")
flash_firmware(url, device, reflash_method="uf2", on_progress=...)
```

Third-party config loader registration (Python entry points):

```toml
# third party's pyproject.toml
[project.entry-points."chumicro_deploy.config_loaders"]
myformat = "my_pkg.loader:load"
```

The CLI (`python -m chumicro_deploy deploy --device <id> --config devices.yml ...`) is a thin wrapper.  Every CLI action has a programmatic equivalent.  Default config loader tries chumicro's `devices.yml` shape; third parties override via entry point.

#### Portability knobs

- `Device.entrypoint_name` — default `code.py` for CP, `main.py` for MP; override freely.
- `Device.resource_prefix` — where lib files land on device, default `/lib`.
- `Deployer.skip_precheck`, `skip_soft_reset`, `skip_gc_collect` — opt out of built-in behaviors.
- `Deployer.pre_execute_hook(session)` — callback for third-party custom code between stage and execute.

#### What is NOT in `chumicro-deploy`

Stays out of scope (belongs to `chumicro-workspace-runtime`):

- `workspace.yml`, `things/`, `library_sources:`, `active.py`, `packages/` vs `libs/` distinction.
- Import-graph analysis specialized for chumicro library conventions.
- Interactive onboarding flows (`add-device`, `rename`, `discover`).
- REPL tailing orchestration (provided by `chumicro-repl`).

#### Tasks

- [ ] Create `libraries/deploy/` via `scripts/run.py new-library deploy`.
- [ ] Move transport protocol + `MicropythonTransport` + `CircuitpythonTransport` + harness bootstrap from `support/device_transport/` into `libraries/deploy/src/chumicro_deploy/`.
- [ ] Implement `Device`, `Deployer`, `DeployResult`, `DeployError` top-level classes.
- [ ] Implement `FileSource` protocol + `FileMapSource`, `DirectorySource`, `ImportGraphSource` built-ins.
- [ ] Implement `probe_device()` returning `DeviceInfo`.
- [ ] Implement `resolve_firmware_url()` + `flash_firmware()` with the shipped reflash family table.
- [ ] Implement `chumicro_deploy.config.chumicro.load_devices_yml()` as opt-in import.
- [ ] Implement `Device.from_dict()` + `Device.from_env()`.
- [ ] Implement entry-point discovery for third-party config loaders.
- [ ] Implement progress / file-staged / execute-line callbacks across deploy pipeline.
- [ ] Keep `support/device_transport/` as a thin re-export during transition; delete once nothing in the mono repo imports it directly.
- [ ] Migrate chumicro's `scripts/device_testing.py` to consume the new Python API.
- [ ] CLI: `python -m chumicro_deploy {deploy,probe,flash-firmware}` with `--config` loader resolution.
- [ ] Host-side tests parity with existing `support/device_transport/` coverage, plus new tests for each source type, config loader path, callback surface, and entry-point discovery.
- [ ] Functional test: deploy a minimal app to at least one CP and one MP board via the new package.
- [ ] Functional test: a standalone "third party" fixture repo (outside chumicro's tree, in `tests/fixtures/third_party_template/`) uses `chumicro-deploy` with its own non-chumicro file layout and a custom `FileSource` — proves portability.

#### Acceptance

- chumicro's `test-device` orchestration uses `chumicro-deploy` via its Python API with no behavior change.
- The `tests/fixtures/third_party_template/` fixture deploys successfully to both runtimes without importing any `chumicro_workspace_runtime` symbol and without touching any chumicro-specific file convention.
- Every CLI action has a documented programmatic equivalent.
- Zero references to `workspace.yml`, `things/`, or `library_sources:` in the deploy package source (enforced by a grep check in CI).

### Phase 2: `chumicro-repl` (minimum-viable core)

This phase delivers only what `run.py deploy` and basic interactive use need.  Richer interactive and scripting features live in a sibling workstream (`plans/workstreams/repl-playground.md`) and can evolve independently once this minimum lands.

- [ ] New library: `libraries/repl/`.
- [ ] Core: pyserial wrapper with UTF-8 safe framing, key bindings matching `mpremote` (Ctrl-C/D/X/E).
- [ ] Pattern detectors for CP `Traceback`, `Safe mode`, `Hard fault`; MP `Traceback`, `MPY: soft reboot`.  Color highlighting.
- [ ] Programmatic `tail(device_entry, seconds, fail_on_traceback) -> ExitCode`.
- [ ] Programmatic `ReplSession` context manager exposing `exec(code)`, `call(func, *args, **kwargs)`, `read_until(pattern, timeout)` — used by deploy orchestration, by `run.py repl`, and by test fixtures.
- [ ] Host-side tests: fake serial byte-stream fixtures + pattern assertions.
- [ ] Functional test: open REPL to at least one CP and one MP board, exchange Ctrl-C / Ctrl-D, verify clean exit.

Acceptance: `python -m chumicro_repl --device <id>` opens an interactive session indistinguishable from `mpremote` for basic workflows, with traceback highlighting as the visible differentiator, and the `ReplSession` API is good enough for downstream phases to build on.

See `plans/workstreams/repl-playground.md` for the larger "side portal" feature set (history, editor handoff, snippets, device introspection commands, multi-device pane, recording) — not blocking this phase.

### Phase 3a: `chumicro-wifi`

Goal: one unified `WifiService` that owns connection and reconnect across CP, MP-ESP32, and MP-Pico-W.  No runtime or firmware-level supervisor competes with the library.

#### Ownership stance

Library is the sole wifi supervisor.  This means:

- **CircuitPython**: the workspace template ships `settings.toml` **without** `CIRCUITPY_WIFI_SSID` / `CIRCUITPY_WIFI_PASSWORD` keys, so the supervisor auto-connect path in `web_workflow.c` never fires.  The library calls `wifi.radio.connect()` itself.  The blocking nature of CP's connect is accepted — documented as a one-time main-loop stall of up to the connect timeout on first attempt.  Subsequent reconnects are driven by the library with the same blocking call, budgeted per tick.
- **MicroPython ESP32**: after the first successful `wlan.connect()`, the library calls `wlan.config(reconnects=0)` to disable the firmware-level auto-reconnect ([network_wlan.c:594-600](../../.tools/micropython-v1.26.0/ports/esp32/network_wlan.c)).  Semantics per source: `reconnects=-1` unlimited (default), `reconnects=0` one attempt then stop, `reconnects=N` N retries after initial.  `0` is effectively "off."  Library drives retries itself with uniform backoff.
- **MicroPython Pi Pico W (CYW43)**: no firmware supervisor exists; library is sole owner by default.  Library additionally applies `wlan.config(pm=0xa11140)` to disable power-save (eliminates idle unresponsiveness).
- **CPython**: fake — always "connected."

The previously sketched `ownership="delegate"` mode (let CP's `settings.toml` auto-connect win) is **dropped**.  Uniform behavior beats matching CP's default UX; settings.toml wifi keys are treated as a footgun and excluded from the template.

#### API sketch

```python
from chumicro_wifi import WifiService, WifiConfig, State

config = WifiConfig(
    ssid="HomeNet",
    password="...",
    hostname="back-porch",               # optional
    static_ip=None,                      # or IPv4 tuple
    power_save=False,                    # always applied on Pico W
    connect_timeout_ms=15_000,           # CP blocking cap
    reconnect_backoff_start_ms=1_000,
    reconnect_backoff_max_ms=60_000,
    reconnect_max=None,                  # None = unlimited
)

wifi = WifiService(config, ticks=ticks)
runner.add(wifi)                         # runner check/handle protocol

wifi.state                               # State.DISCONNECTED | CONNECTING | CONNECTED | RECONNECTING | FAILED
wifi.connected                           # live bool
wifi.ip                                  # str | None
wifi.last_error                          # exception | None
wifi.on_state_change(callback)           # (old_state, new_state) -> None
```

State machine:

```
DISCONNECTED -> CONNECTING -> CONNECTED
                    |            |
                    |            v
                    |       RECONNECTING (on drop)
                    |            |
                    v            v
                 FAILED <--- backoff exhausted (if reconnect_max set)
```

Per-runtime adapters live in `chumicro_wifi._adapters/`: `cp.py`, `mp_esp32.py`, `mp_rp2.py`, `cpython.py`.  Adapter selection happens at `WifiService` construction via `sys.implementation.name` + board probe.

#### Tasks

- [ ] New library: `libraries/wifi/` via `scripts/run.py new-library wifi`.
- [ ] `WifiConfig` dataclass + `WifiService` class implementing runner `check`/`handle`.
- [ ] Four runtime adapters with a shared protocol.  Each adapter: `connect()`, `disconnect()`, `is_linked()`, `configure()`, `ip()`.
- [ ] Reconnect supervisor in `WifiService` — exponential backoff, capped at `reconnect_backoff_max_ms`, honors `reconnect_max`.
- [ ] `testing.py` with `FakeWifi` — drives state transitions explicitly for downstream library tests.
- [ ] Host-side tests covering state machine, backoff math, adapter selection, and failure paths.
- [ ] Cross-runtime tests (CP + MP unix-port) for the state machine and adapter contract.
- [ ] Functional test on the home testbed: connect to AP, verify reconnect after manual deassoc (`wlan.disconnect()` on MP; radio toggle on CP).
- [ ] Template `AGENTS.md` note: "do not add `CIRCUITPY_WIFI_SSID` to settings.toml — chumicro-wifi owns the radio."

#### Device verification still wanted

Docs do not settle these; run on plugged-in boards:

- Does `wifi.radio.enabled = False` in `boot.py` actually veto the CP supervisor auto-connect path before it fires?  If yes, the library can belt-and-suspenders this alongside the "no SSID key" approach.
- How long does CP's blocking `connect()` stall on a routable-but-unresponsive AP?  Informs `connect_timeout_ms` default.
- Does `wlan.config(reconnects=0)` on MP ESP32 take effect mid-session (after initial connect), or must it be set pre-connect?  Source suggests either works (it's just a config variable read at event time) but confirm on hardware.
- Pico W MP with `pm=0xa11140`: how much does responsiveness improve in practice?  Expected yes per community reports.

### Phase 3b: `chumicro-kvstore` + config pipeline (supersedes `chumicro-settings`)

Decision 0030 splits the old `chumicro-settings` scope into two unrelated concerns: read-only app **config** (shipped with the thing, TOML on host → msgpack on device, transformed at deploy) and mutable **persisted state** (a new, narrower library `chumicro-kvstore`).

The previously-sketched `chumicro-wifi` credential consumption reads from the config pipeline, not from `chumicro-kvstore`.  Credentials never land in any KV backend.

#### Config pipeline tasks (owned by `chumicro-workspace-runtime`, not a new library)

- [ ] Deployer merges `workspace.yml` environment defaults + `secrets.yml` entries + `things/<name>/config.toml` into a single dict.
- [ ] Deployer writes merged dict as `/runtime_config.msgpack` onto the device at deploy time.
- [ ] `secrets.yml` values referenced via `!secret <name>` are resolved at merge time and never travel with commits.
- [ ] Thing template `app.py` reads the file once at boot: `config = msgpack.unpackb(open("/runtime_config.msgpack", "rb").read())`.
- [ ] YAML host format accepted via `things/<name>/config.yml` when present; TOML wins when both exist.  JSON on device accepted via a per-thing `format: json` flag in its `thing.yml`.
- [ ] Template `AGENTS.md` documents: "do not reuse `settings.toml` for app config; do not store wifi creds in the KV store."

#### `chumicro-kvstore` tasks

- [ ] New library: `libraries/kvstore/` via `scripts/run.py new-library kvstore`.
- [ ] `KVStore` class with `backend="auto" | "nvm" | "nvs" | "littlefs" | "memory"` selection.  Default `auto` picks per `sys.implementation.name` + board probe.
- [ ] Per-runtime adapters under `chumicro_kvstore._backends/`: `cp_nvm.py`, `mp_nvs.py`, `mp_littlefs.py`, `memory.py`.
- [ ] Values encoded via `chumicro-msgpack`; CP NVM backend prepends a length + CRC header for power-loss-corruption detection.
- [ ] `commit_if_changed()` wear-mitigation helper.
- [ ] `KVStoreFull` and `KVStoreCorrupt` exceptions.
- [ ] `capacity`, `bytes_used`, `is_corrupt` properties.
- [ ] `testing.py` with `FakeKVStore` (wraps `MemoryBackend`, records calls).
- [ ] Host-side tests covering each backend via fakes.
- [ ] Cross-runtime tests on CP + MP unix-ports.
- [ ] Functional test: write a boot-counter across a hard reset on at least one CP board (NVM) and one MP board (NVS).

#### Acceptance

- A thing can ship a `config.toml`, have it deployed as `/runtime_config.msgpack`, and read it at boot with a single-line `msgpack.unpackb()` call.
- `KVStore` round-trips `{str, int, bytes, list, dict}` values across a hard reset on each supported backend.
- `store.capacity` returns a correct byte count per backend; `KVStoreFull` is raised before overflow.
- CP NVM backend flags `is_corrupt=True` on CRC mismatch after a mid-write power loss (tested via a deliberately corrupted blob), then resets to empty.

### Phase 4a: `chumicro-workspace-runtime`

- [ ] New library: `libraries/workspace-runtime/`.
- [ ] Host side: command dispatch (`setup`, `new`, `add-device`, `probe`, `discover`, `devices`, `deploy`, `sim`, `test`, `repl`, `env`, `use`, `rename`, `install-firmware`, `upgrade-firmware`, `sync`, `upgrade`).
- [ ] `devices.yml` three-zone writer with user-comment and key-order preservation on round-trip.
- [ ] Onboarding flows for the three board states (REPL, UF2 bootloader, blank-chip-esptool).
- [ ] Firmware URL derivation (CP S3 listing; MP scrape-and-cache).
- [ ] Import-graph resolver (AST walk starting from thing entrypoint, `library_sources:` override support).
- [ ] Device-side `workspace_runtime` module: `boot()` reads `active.py`, imports thing, calls `run()`.

### Phase 4b: `chumicro-workspace-template` repo

- [ ] Initialize companion repo.
- [ ] Ship: `run.py` shim, `workspace.yml`, `devices.yml` skeleton with three-zone comments, `secrets.yml.example`, `AGENTS.md`, `pyproject.toml` with pinned workspace-runtime + quality knobs, `.pre-commit-config.yaml`, `.gitignore`, `things/_template/`, `libs/` with `.gitkeep`, `packages/.gitignore`.
- [ ] One worked example thing under `things/example-hello/` that runs on all three runtimes via sim + on a real board.
- [ ] Template-side CI: lint + CPython tests + sim run + (optional, user-configured) device test.

Acceptance: a user clones the template, runs `python run.py setup`, plugs in a board, runs `python run.py add-device`, edits `things/example-hello/app.py`, runs `python run.py deploy`, sees output in REPL.  Zero additional setup.

### Phase 5: `chumicro-mqtt` refactor + first sensor thing template

- [ ] New library: `libraries/mqtt/`.
- [ ] Port the 1043-line `MQTTClient` from `/Users/chuxor/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py` into runner `check`/`handle` shape.  Non-blocking `select.poll` dispatch.  Pre-allocated bytearray buffers.  Will + publisher + subscriber.
- [ ] Host-side tests against a local broker fixture (mosquitto in CI? or a Python MQTT server fake).
- [ ] Functional test: publish + subscribe on a real board against the home testbed broker.
- [ ] Add `things/example-sensor/` to the template repo — temperature → MQTT publish on a heartbeat.

## Success criteria

- A user goes from `git clone <template-repo>` to a blinking-LED thing deployed on a board they've never connected before, in under ten minutes, on a laptop with only Python and a USB cable.
- The same `things/<name>/` runs on CP + MP + CPython-sim with no code changes when using only cross-runtime libraries.
- A chumicro developer can edit `libraries/timing/src/chumicro_timing/core.py` in their mono-repo clone and see the change in a workspace deploy without publishing.
- Moving a board between USB ports does not require manual `devices.yml` edits.
- Flashing a blank ESP32-S3 to running CircuitPython is a single `run.py add-device` flow with guided prompts.

## Notes

- `chumicro-mqtt` source-of-truth during refactor: read the original at `/Users/chuxor/circuitpython/pythonProject3/basefilesystem/lib/basefs/mqtt_client.py` and treat it as prior art — reshape, don't port verbatim.
- `workspace.yml` quality knobs (`lint`, `coverage_threshold`, `agent_strictness`) let the user dial their comfort.  Defaults are relaxed; `AGENTS.md` in the template tells LLM agents how to read them.
- Library sequencing is a guideline, not a hard ordering — Phase 3a and 3b can interleave, and Phase 2 can start before Phase 1 finishes if a developer-pair splits the work.  Phase 4 is the only gate that genuinely requires everything before it.

## Open sub-questions

(from `plans/open-questions.md`)

- Does `chumicro-mqtt` refactor need to land before the first end-to-end sensor template, or can an MQTT-less headless thing be the first proving ground?
- AST parsing sufficient for conditional imports, or does runtime trace-collection on CPython sim earn its keep?
- What does the `devices.yml` round-trip contract promise vs what the YAML library actually preserves on unusual user edits (anchors, merge keys, multi-doc)?

## Resolved feedback

- **ADR vs initiative:** Design tradeoffs live in Decision 0029; execution plan (phases, sequencing, acceptance) lives in this workstream doc.  Split applied 2026-04-21.
- **`run.py new`:** Allowed — it is a `cp -r things/_template` convenience, not a code generator.  No CLI binaries, no PATH linking, no pip install.
