# Workstream: Project Workspace

Status: `complete` — every phase shipped.  Phases 1, 2, 3a, 3b, 4a, 4b, 5, 6 shipped 2026-04-22 → 2026-04-26.  Phase 4b's pip-install-scaffolder shape was retired in Decision 0038 (2026-04-26) and replaced by a clone-the-repo bootstrap with `init` / `update` folded into `chumicro-workspace`; canonical starter at [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template).  Phase 4c is dissolved into Decision 0038 — the template *is* the repo.  Phase 7 (first sensor thing template) closed 2026-04-27 — Layer-1, Layer-2, Layer-3, sensor thing, README walkthrough all shipped.  Application-level OTA carved out into its own potential workstream at `plans/workstreams/ota.md` (unscoped) on 2026-04-27 so this workstream could close cleanly.

## Purpose

Give users a template-repo project workspace that unifies CircuitPython, MicroPython, and CPython at project scope — onboard a board, write app code, deploy to one or many targets, and watch the REPL.  Companion to Decision 0029, which records the design tradeoffs.

**When starting a session on this workstream, read `plans/workstreams/project-workspace-research.md` first.**  It holds the source-pinned facts, pythonProject3 MQTT refactor line references, API sketches, rejected alternatives, and URL list — picks up where the prior sessions' research left off so it does not have to be redone.

## Scope

- A `ChuMicro-Workspace-Template` repo (separate, public-on-public-day): checked-in `run.py` (self-bootstrapping), `workspace.yml`, `devices.yml`, `things/_template/`, `packages/` (gitignored), `libs/`, `_templates/secrets.yml` (materialized to `secrets.yml` at setup per Decision 0038 §5), `.venv/` (gitignored), baseline `AGENTS.md`, `pyproject.toml` pinning `chumicro-workspace`.
- Six new chumicro libraries (post-Decision-0038 consolidation): `chumicro-deploy`, `chumicro-repl`, `chumicro-wifi`, `chumicro-sockets`, `chumicro-mqtt`, `chumicro-workspace`.  The already-planned `chumicro-kvstore` (formerly `chumicro-settings`, see Decision 0030) is an assumed-necessity but is owned by its own next-up entry, not this workstream.
- Onboarding UX: `run.py add-device` handles responsive boards, boards in UF2 bootloader, and blank chips detectable by esptool.
- Firmware install + upgrade: `run.py install-firmware`, `run.py upgrade-firmware`, `--prerelease`, `--approve-board-storage-reset`, programmatic bootloader-entry where supported.
- Local library dogfooding: `library_sources:` maps a package name or mono-repo root to a local clone; reuses the Decision 0026 editable-install pattern.

Out of scope for this workstream:

- `chumicro-settings` itself (tracked separately in `next-up.md`).
- Hot-plug daemon (`run.py watch`) — defer until requested.
- Community-contributed firmware catalog — users paste URLs into `devices.yml`; contrib path is optional future work.
- ESP32 NVS backend for settings — tracked in open-questions.

## Current verified slice

**Phase 1 (`chumicro-deploy`) shipped 2026-04-22** — see the Phase 1 section below and the 2026-04-22 entry in `plans/history.md` for the completion record.  The transport layer previously housed in `support/device_transport/` now lives in `workbench/deploy/src/chumicro_deploy/` as part of the published package; `scripts/device_testing.py` and `scripts/pytest_device.py` consume it directly.  Portability to third-party project templates is proven by `workbench/deploy/tests/fixtures/third_party_template/`.

Remaining prerequisites for downstream phases that already exist:

- `devices.yml` + `device-config.yml` schemas and loaders — Decision 0027.
- `support/test_harness/` lightweight on-device runner.
- Editable-install pattern for libraries + support packages — Decision 0026.

## Library sequencing

Seven libraries (six new + `chumicro-kvstore`) land in a deliberate order so each phase has working dependencies.

Per Decision 0032, each package lives in `libraries/` (installer puts code on a microcontroller) or `workbench/` (installer puts code on a laptop).  `chumicro-workspace` lives in `workbench/`: the host CLI is what third parties `pip install`, and its on-device boot module ships as a data file that the CLI deploys onto the board — payload, not an installable package.

| Phase | Package | Folder | Role | Depends on |
|-------|---------|--------|------|------------|
| 1 | `chumicro-deploy` | `workbench/` | Extraction of `support/device_transport/` into publishable package. Public API: Python + thin CLI. | Decision 0028 transport |
| 2 | `chumicro-repl` | `workbench/` | CP/MP-aware serial TUI. UTF-8 + emoji safe. Traceback highlighting. `tail()` API for deploy. | pyserial |
| 3 | `chumicro-kvstore` | `libraries/` | Already planned, lands here in this sequencing. Tiny mutable KV for persisted runtime state. | msgpack |
| 3 | `chumicro-wifi` | `libraries/` | Non-blocking connection manager. CP + MP + CPython-stub. | runner, kvstore |
| 4 | `chumicro-workspace` | `workbench/` | One-stop host CLI: `init` (clone a template repo), `setup` (venv + materialize `_templates/`), `update` (re-flow tool-owned files from upstream), `add-device`, `deploy`, `switch`, `repl`, etc.  Ships the on-device `workspace_runtime` boot module as a data payload that the CLI writes onto the board at deploy time.  Decision 0038 consolidated the previously-separate `chumicro-workspace-template` package's `init` / `update` / three-zone manifest into this one. | deploy, repl, kvstore, wifi |
| 4 | `ChuMicro-Workspace-Template` repo | *separate repo* | The canonical template source: checked-in `run.py`, `workspace.yml`, `things/_template/`, `_templates/secrets.yml`.  Versioned and forkable independently — third parties can host their own template repos that the same `chumicro-workspace init --from <url>` applies. | — (data, not code) |
| 5 | `chumicro-sockets` | `libraries/` | Thin TCP client + TLS abstraction over CP `socketpool` / MP `socket` / CPython `socket`. Prereq for MQTT and future requests lib. See Decision 0031. | none (pure platform shim) |
| 6 | `chumicro-mqtt` | `libraries/` | Refactor pythonProject3's 1043-line hand-rolled client into a runner-shaped service on top of chumicro-sockets. QoS 0 + 1; internal shape allows QoS 2 later. | runner, wifi, sockets |
| 7 | `ChuMicro-Workspace-Template` first-sensor thing | *template repo* | End-to-end proving ground: a temperature sensor that connects via wifi, publishes via mqtt, persists a counter via kvstore. | all prior |

Rationale: Phase 1 unblocks everything.  Phase 2 is used by Phase 4's deploy-then-tail UX.  Phase 3 is two libraries in parallel (independent).  Phase 4 is the integration phase — the CLI plus the template.  Phase 5 (`chumicro-sockets`) is a small but strict prereq for MQTT that also sets up the future HTTP client.  Phase 6 (`chumicro-mqtt`) refactors the pythonProject3 client against the new sockets base.  Phase 7 lands the first non-trivial thing-template and proves the whole stack end-to-end.

## Implementation phases

### Phase 1: `chumicro-deploy` extraction ✅ Complete (2026-04-22)

Three-audience package: chumicro mono repo (replaced `support/device_transport/` callers), chumicro-workspace-template (`run.py deploy`, future), and third parties building their own project templates.  Decision 0029 §8 records the workspace-agnostic + plugin-shaped requirement.

Shipped across slices 1a–1f: extraction into `workbench/deploy/`, `Device` + `Deployer` + `DeployResult`/`DeployError` facade, `FileSource` protocol with three built-in sources, `probe_device` + `resolve_firmware_url` + `flash_firmware` (UF2 + esptool with programmatic bootloader entry and interactive fallback, per-runtime offsets, optional pre-erase), config-loader entry-point discovery, thin CLI, mkdocs docs, and a third-party portability fixture that deploys without touching any mono-repo module.  Hardware-verified on ESP32-S2, ESP32-S3, and Pi Pico W on both runtimes.

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

# Or: opt-in built-in devices.yml loader
from chumicro_deploy.config.default import load_devices_yml
device = load_devices_yml("devices.yml", device_id="back-porch")
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

The CLI (`python -m chumicro_deploy deploy --device <id> --config devices.yml ...`) is a thin wrapper.  Every CLI action has a programmatic equivalent.  The built-in loader (registered as `"default"`) reads the `devices.yml` schema that `chumicro-deploy` owns; third parties override via entry point with their own registered name.

#### Portability knobs

- `Device.entrypoint_name` — default `code.py` for CP, `main.py` for MP; override freely.
- `Device.resource_prefix` — where lib files land on device, default `/lib`.
- `Deployer.skip_precheck`, `skip_soft_reset`, `skip_gc_collect` — opt out of built-in behaviors.
- `Deployer.pre_execute_hook(session)` — callback for third-party custom code between stage and execute.

#### What is NOT in `chumicro-deploy`

Stays out of scope (belongs to `chumicro-workspace`):

- `workspace.yml`, `things/`, `library_sources:`, `active.py`, `packages/` vs `libs/` distinction.
- Import-graph analysis specialized for chumicro library conventions.
- Interactive onboarding flows (`add-device`, `rename`, `discover`).
- REPL tailing orchestration (provided by `chumicro-repl`).

#### Tasks

Folder layout was revised during implementation — packages ship from `workbench/<name>/` rather than `libraries/<name>/` per Decision 0032.  `support/device_transport/` was deleted outright once the move landed; a transitional re-export was not needed because all callers migrated in the same slice.

- [x] Create `workbench/deploy/` (Decision 0032; `new-library` scaffolder does not yet cover workbench packages — hand-scaffolded from existing conventions).
- [x] Move transport protocol + `MicropythonTransport` + `CircuitpythonTransport` + harness bootstrap from `support/device_transport/` into `workbench/deploy/src/chumicro_deploy/`.
- [x] Implement `Device`, `Deployer`, `DeployResult`, `DeployError` top-level classes.
- [x] Implement `FileSource` protocol + `FileMapSource`, `DirectorySource`, `ImportGraphSource` built-ins.
- [x] Implement `probe_device()` returning `DeviceInfo`.
- [x] Implement `resolve_firmware_url()` + `flash_firmware()` with the shipped reflash family table.
- [x] Implement `chumicro_deploy.config.default.load_devices_yml()` as opt-in import (renamed from `config.chumicro` on 2026-04-24 to reflect that `chumicro-deploy` owns the schema).
- [x] Implement `Device.from_dict()` + `Device.from_env()`.
- [x] Implement entry-point discovery for third-party config loaders.
- [x] Implement progress / file-staged / execute-line callbacks across deploy pipeline.
- [x] Delete `support/device_transport/` outright once callers migrated (no transitional re-export needed — single-slice migration).
- [x] Migrate chumicro's `scripts/device_testing.py` to consume the new Python API.
- [x] CLI: `chumicro-deploy {deploy,probe,flash,resolve-firmware-url}` with `--devices-file` / `--devices-format` loader resolution.
- [x] Host-side tests parity with existing `support/device_transport/` coverage, plus new tests for each source type, config loader path, callback surface, and entry-point discovery.
- [x] Functional test: deploy a minimal app to at least one CP and one MP board via the new package (hardware-verified on ESP32-S2, ESP32-S3, and Pi Pico W on both runtimes).
- [x] Functional test: a standalone "third party" fixture repo under `workbench/deploy/tests/fixtures/third_party_template/` uses `chumicro-deploy` with its own non-chumicro file layout and a custom `FileSource` — proves portability; a `sys.modules` leak check asserts no mono-repo coupling.

#### Acceptance

- [x] chumicro's `test-libraries-functional` orchestration uses `chumicro-deploy` via its Python API with no behavior change (`scripts/device_testing.py` + `scripts/pytest_device.py`).
- [x] The `workbench/deploy/tests/fixtures/third_party_template/` fixture deploys successfully through the fake transport without importing any `chumicro_workspace` symbol and without touching any chumicro-specific file convention.
- [x] Every CLI action has a documented programmatic equivalent (see `workbench/deploy/docs/api.md`).
- [x] Zero references to `workspace.yml`, `things/`, or `library_sources:` in the deploy package source.

### Phase 2: `chumicro-repl` ✅ Complete (2026-04-25)

This phase delivers only what `run.py deploy` and basic interactive use need.  Richer interactive and scripting features live in a sibling workstream (`plans/workstreams/repl-playground.md`) and can evolve independently once this minimum lands.

**Closing summary:** Shipped `workbench/repl/` v0.0.0 across eight commits over two days (2026-04-24 minimum-viable core → 2026-04-25 close-out).  Beyond the minimum spec, the package also ships an auto-reconnect loop in `tail()` / `run_loop()` for transient device drops, a recovery / hand-holding layer (`InteractiveReplSession`, `ReplFailureKind`, `RecoveryPlan`, `classify_session_failure`, `recovery_plan_for`) mirroring the `chumicro-deploy` pattern, a typed `ReplSessionDisconnected(ReplSessionError).cause` for mid-session drops, and the matching `examples/demo_repl_robustness.py` interactive walkthrough.  Repl-side learnings (BaseException-scriptable `FakeSerialPort`, typed mid-deploy disconnect subclasses) ported back to `chumicro-deploy`.  175 host-side tests at 94 % coverage; 9 hardware-gated functional tests passing on Pi Pico W (CP) + Pi Pico W (MP); preflight green.  See [`plans/history.md` 2026-04-25](../../README.md) for the full session log.

**Open Phase-4-prerequisite follow-up:** `chumicro-deploy`'s `CircuitpythonTransport` carries its own raw-REPL framing parallel to `chumicro_repl.session.ReplSession`.  Consolidation deferred until `chumicro-workspace` lands and the session-vs-pipeline seam is concrete.  Tracked in this file's "Open follow-up" subsection below.

- [x] New workbench package: `workbench/repl/` (Decision 0032 places host-only tools under `workbench/`; the earlier `libraries/repl/` line was an early sketch and is superseded by the library sequencing table at the top of this workstream).
- [x] Core: pyserial wrapper with UTF-8 safe framing (`Utf8StreamDecoder` in `framing.py`), key bindings matching `mpremote` (Ctrl-C/D/E forwarded; Ctrl-X is local exit) in `tui.py`.
- [x] Pattern detectors for CP `Traceback`, `safe mode`, `Hard fault`; MP `Traceback`, `MPY: soft reboot`; ANSI highlighting via `colorize()` and a tunable `Theme` in `highlight.py`.
- [x] Programmatic `tail(device, seconds, fail_on_traceback) -> ExitCode` in `_follow.py`, exposed at the top level as `chumicro_repl.tail`.
- [x] Programmatic `ReplSession` context manager exposing `exec(code)`, `call(function_name, *args, **kwargs)`, `read_until(pattern, timeout)` — driven by raw REPL over pyserial; same code path for CP and MP.
- [x] Host-side tests: 146 tests against `FakeSerialPort` / `FakeKeyboard` / `FakeTime` fakes covering framing, patterns, highlight, ReplSession (handshake / exec / call / read_until / error paths), tail (exit codes, UTF-8 boundary, port lifecycle, device resolution), TUI loop (forwarding, exit-key drain, Unicode), CLI (parser, dispatch, devices.yml routing), and disconnect/auto-reconnect across all three surfaces.  Coverage 94 % (at the agent gate).
- [x] Functional test: open REPL to at least one CP and one MP board, exec / call / clean exit; deploy code that raises and confirm tail's pattern detector catches the on-device traceback.  9 hardware-gated tests under `workbench/repl/functional_tests/`, all passing on a Pi Pico W (CP) + a Pi Pico W (MP).  Mirrors `workbench/deploy/functional_tests/` — fixtures load `devices.yml` defaults and skip cleanly when no board is configured.

Acceptance: `chumicro-repl --address /dev/cu.usbmodem...` (or the equivalent `python -m chumicro_repl ...`) opens an interactive session indistinguishable from `mpremote` for basic workflows, with traceback highlighting as the visible differentiator, and the `ReplSession` API is good enough for downstream phases to build on.  `--devices-file devices.yml` plus either `--device <id>` or `--runtime <circuitpython|micropython>` reads the same schema `chumicro-deploy` owns.  A startup banner identifies the connection and keybindings; a single carriage-return nudge on connect coaxes the friendly REPL into reprinting its `>>>` so the user is never staring at a blank screen.

See `plans/workstreams/repl-playground.md` for the larger "side portal" feature set (history, editor handoff, snippets, device introspection commands, multi-device pane, recording) — not blocking this phase.

#### Open follow-up

`chumicro-deploy`'s `CircuitpythonTransport` carries its own raw-REPL implementation that overlaps with `chumicro_repl.session.ReplSession` (Ctrl-A handshake + `OK<stdout>\x04<stderr>\x04>` framing).  Decision 0032 rule 8 ("scripts consume workbench packages") suggests deploy should eventually depend on repl for the raw-REPL framing and stop maintaining a parallel implementation.  Not undertaken in this phase — deploy's transport is integrated with bootstrap-script chunking, recovery classification, and probe / reset paths that are out of scope for repl's minimum core.  Track as a Phase 4 prerequisite once the workspace-runtime work lands and the natural seam between "session-level RPC" and "deploy-pipeline orchestration" is clearer.

### Phase 3a: `chumicro-wifi` ✅ Complete (2026-04-25)

**Library shipped 2026-04-25.**  Five slices closed Phase 3a end-to-end: skeleton + `WifiConfig` + state machine + reconnect supervisor + `FakeWifi` (Slice 0); CP `wifi.radio` adapter (Slice 1, Lolin S2 CP + Pi Pico W CP); MP `network.WLAN` adapter on ESP32 with `wlan.config(reconnects=0)` supervisor-off (Slice 2, Lolin S2 MP); MP CYW43 adapter with `wlan.config(pm=0xa11140)` power-save knob (Slice 3, Pi Pico W MP); live-AP acceptance via the gitignored host-driven runner at `.scratch/run_wifi_acceptance.py` (Slice 4, all four boards).  87 host tests at 99 % coverage, full per-substrate functional verification + live-AP connect-drop-reconnect cycle observed on every board.  `_templates/config.toml` shipped per ADR 0036 §5 — first library to ship a workspace-tooling-collectable template.


Goal: one unified `WifiService` that owns connection and reconnect across CP, MP-ESP32, and MP-Pico-W.  No runtime or firmware-level supervisor competes with the library.

#### Ownership stance

Library is the sole wifi supervisor.  This means:

- **CircuitPython**: the workspace template ships `settings.toml` **without** `CIRCUITPY_WIFI_SSID` / `CIRCUITPY_WIFI_PASSWORD` keys, so the supervisor auto-connect path in `web_workflow.c` never fires.  The library calls `wifi.radio.connect()` itself.  The blocking nature of CP's connect is accepted — documented as a one-time main-loop stall of up to the connect timeout on first attempt.  Subsequent reconnects are driven by the library with the same blocking call, budgeted per tick.
- **MicroPython ESP32**: after the first successful `wlan.connect()`, the library calls `wlan.config(reconnects=0)` to disable the firmware-level auto-reconnect ([network_wlan.c:594-600](https://github.com/micropython/micropython/blob/v1.26.0/ports/esp32/network_wlan.c)).  Semantics per source: `reconnects=-1` unlimited (default), `reconnects=0` one attempt then stop, `reconnects=N` N retries after initial.  `0` is effectively "off."  Library drives retries itself with uniform backoff.
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

### Phase 3b: `chumicro-kvstore` + config pipeline (supersedes `chumicro-settings`) ✅ Complete (2026-04-25)

**Library shipped 2026-04-25.**  Decision 0034 nails down the API + per-backend contracts.  `libraries/kvstore/` ships `KVStore` with mapping-shaped public API + three lifecycle methods (`commit`, `commit_if_changed`, `reload`), four exceptions (`KVStoreError` / `KVStoreFull` / `KVStoreCorrupt` / `KVStoreReadOnly`), four runtime-aware backends (memory, CP NVM with `MAGIC | LEN | CRC32 | MSGPACK` framing, MP NVS single-payload-blob in `chu_kv` namespace, MP LittleFS single `/_chu_kv.msgpack` with tmp+sync+rename atomicity), and `chumicro_kvstore.testing.FakeKVStore` for downstream library tests.  92 host tests at 99 % coverage; 27 functional tests pass on each of the four plugged-in boards (Lolin S2 CP/MP, Pi Pico W CP/MP).

The config-pipeline bullets below remain owned by `chumicro-workspace` (Phase 4a) and don't land a library, so they're tracked here as scope but not as Phase 3b deliverables.


Decision 0030 splits the old `chumicro-settings` scope into two unrelated concerns: read-only app **config** (shipped with the thing, TOML on host → msgpack on device, transformed at deploy) and mutable **persisted state** (a new, narrower library `chumicro-kvstore`).

The previously-sketched `chumicro-wifi` credential consumption reads from the config pipeline, not from `chumicro-kvstore`.  Credentials never land in any KV backend.

#### Config pipeline tasks (owned by `chumicro-workspace`, not a new library)

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

#### Device verification still wanted

Docs settle most numbers; these need boards:

- `print(len(microcontroller.nvm))` on ESP32-S3 and Pico W CP — confirms actual sizes match the `CIRCUITPY_INTERNAL_NVM_SIZE` defaults (8192 and 4096 respectively).
- MP ESP32 `esp32.NVS` commit survives hard reset — confirms the commit semantics in `ports/esp32/esp32_nvs.c:127-131`.
- Write latency for a 512 B blob across CP NVM, MP NVS, MP Pico W LittleFS — informs documentation guidance on write-budgets.
- Pico W MP LittleFS atomic rename survives pull-power mid-rename — confirms safe-update pattern.

### Phase 4 prerequisite: vendor on-device test runner into `chumicro-deploy`

External template-repo consumers (Phase 4b/4c) will want to run on-device tests for the things they author.  Today the only on-device runner is `chumicro_test_harness.runner.run_module` in [`support/test_harness/`](../../../support/test_harness/), which is workspace-internal and never published — `pip install chumicro-deploy` doesn't pull it in, and it isn't in the bundle.  Promoting it to a published `libraries/test-harness/` was considered and rejected: it's dev-time scaffolding, not production library code, so listing it alongside `chumicro-timing` / `chumicro-runner` / etc. in the CircuitPython bundle would muddy what users `circup install` for their actual project.

The cleaner shape is to **vendor the on-device runtime parts inside `chumicro-deploy`** — same pattern as the existing [`circuitpython_bootstrap_template.txt`](../../../workbench/deploy/src/chumicro_deploy/circuitpython_bootstrap_template.txt) — and re-export the host-side `raises()` helper from `chumicro_deploy.testing`.  Result: `pip install chumicro-deploy` is sufficient for both deploying code and running on-device tests, no separate install or bundle entry needed.

Tasks:

- [ ] Vendor `runner.run_module` (and its minimal deps) as a payload under `workbench/deploy/src/chumicro_deploy/_payloads/test_harness/`.  Stays at the same import path on-device (`from chumicro_test_harness.runner import run_module`) so no bootstrap-template changes are needed.
- [ ] Re-export `raises` from `chumicro_deploy.testing` so external consumers writing tests against their template-repo libraries can `from chumicro_deploy.testing import raises` without a separate package.
- [ ] Update `chumicro-deploy`'s on-device staging to copy from the vendored payload by default, while keeping the existing `support/test_harness/`-based path for in-repo use (so this repo's own functional tests don't change).
- [ ] Document the on-device test workflow in `workbench/deploy/docs/testing.md` (host-side fakes are already there) — when to use it, how to write a test, what gets staged.

Out of scope (left as-is for this repo):

- `support/test_harness/` stays put.  In-repo library tests keep importing `from chumicro_test_harness import raises` via the editable-install path; `run_cross_runtime.py` keeps driving the unix-port unit tests.  The vendoring is purely additive — it doesn't replace the in-repo path.

### Phase 4a: `chumicro-workspace` ✅

- [x] New workbench package: `workbench/workspace-runtime/`.
- [x] Host side: command dispatch (`setup`, `new`, `add-device`, `probe`, `discover`, `devices`, `things`, `deploy`, `switch`, `sim`, `test`, `repl`, `env`, `use`, `rename`, `install-firmware`, `upgrade-firmware`, `sync`, `upgrade`).
- [x] `devices.yml` three-zone writer with user-comment and key-order preservation on round-trip (Slice 3 — `ruamel.yaml`-backed).
- [x] Onboarding flows for the three board states (REPL, UF2 bootloader, blank-chip-esptool) — Slice 4.
- [x] Firmware URL derivation: CP S3 listing (Slice 5) + MP `micropython.org/download/<BOARD>/` live scrape (post-Slice-7 follow-on).
- [x] Import-graph resolver (AST walk starting from thing entrypoint, `library_sources:` override support) — Slice 6.
- [x] Device-side `workspace_runtime` module: `boot()` reads `active.py`, imports thing, calls `run()` — Slice 7.
- [x] Multi-thing-on-one-device deploys + `switch <name>` CLI — `multi_thing_boot_source` ships N things side-by-side under `/lib/things/<each>/` with per-thing runtime config msgpacks; `switch_source` re-points `/active.py` + canonical msgpack with three small files (no payload re-flash).
- [x] Live-board functional tests — `workbench/workspace-runtime/functional_tests/test_boot_shim_hardware.py` exercises the full `code.py` → `workspace_runtime.boot()` → `things.<name>.app.run()` chain on Pi Pico W CP/MP (4/6 pass on RAM mode; switch tests skip on RAM and need flash mode to see persisted prior payloads).
- [x] Docs / README pass — README + `docs/guide.md` rewritten to match the feature-complete API (CLI table, boot-shim layout, multi-thing flows, switch, programmatic API, config merge, firmware, devices.yml round-trip).

### Phase 4b: `chumicro-workspace-template` package ⚠️ superseded by Decision 0038

> **Superseded 2026-04-26.**  The pip-installable scaffolder shape was retired in Decision 0038 ("Workspace bootstrap via clone, not pip-installed scaffolder").  `init` / `update` / the three-zone manifest moved into `chumicro-workspace`; the `_payloads/default_template/` tree migrated to a separate Git repo at [`ChuMicro/ChuMicro-Workspace-Template`](https://github.com/ChuMicro/ChuMicro-Workspace-Template); `workbench/workspace-template/` was deleted from the mono-repo.  The historical record below is preserved as evidence of what shipped before the pivot.

- [x] (HISTORICAL) New workbench package: `workbench/workspace-template/`.  Now deleted.
- [x] (HISTORICAL) `init`/`update` commands shipped against a `_payloads/default_template/` tree.  Logic moved into `chumicro-workspace` per Decision 0038 §3.
- [x] (HISTORICAL) Three-zone model from Decision 0029 §9 generalized across the workspace tree.  Carried over verbatim to `chumicro_workspace.template_zones`, plus `_templates/` added as a fourth tool-owned prefix per Decision 0038 §5.
- [x] (HISTORICAL) End-to-end smoke verified: pip-install → init → setup → new thing → update flow.  Replaced by `git clone` → `python3 run.py setup` → `chumicro-workspace new` → `chumicro-workspace update` flow under Decision 0038.

### Phase 4c: dissolved into Decision 0038

> **Dissolved 2026-04-26.**  Phase 4c was originally "create a separate companion repo for the template files."  Decision 0038 makes the canonical template repo the *primary* bootstrap path (not an optional sibling to a built-in default), so there is no separate phase: the repo IS the bootstrap, the staging happened alongside the package consolidation, and there's no remaining "Phase 4c" deliverable to track.

The new repo is `ChuMicro/ChuMicro-Workspace-Template`, private, flagged as a GitHub template repo.  Initial content carved out from the deleted `_payloads/default_template/` tree with the dotfile rename pre-applied, a self-bootstrapping `run.py`, an `_templates/secrets.yml` source (no more `secrets.yml.example`), and a `pyproject.toml` pinning `chumicro-workspace`.

### Phase 5: `chumicro-sockets` ✅

Thin TCP client + TLS abstraction over the three runtimes' divergent socket stories.  Prerequisite for `chumicro-mqtt` and a future `chumicro-requests`.  Architecture recorded in Decision 0031.

**Shipped 2026-04-25.**  `libraries/sockets/` — `tcp_client_socket` / `tls_client_socket` factories + `TCPClientSocket` protocol + 3 adapters (CP `socketpool`, MP stdlib `socket`+`ssl`, CPython stdlib) + `FakeSocket` testing fake.  40 host tests at 95 % cov.

Deviation from the original Decision 0031 §2 sketch: the four-adapter shape (CP / MP-ESP32 / MP-RP2 / CPython) collapses to three.  Decision 0031 §1 already noted current MP ships `MICROPY_SSL_MBEDTLS=1` on both ESP32 and RP2 ports (1.26+), so the socket+ssl story is unified — one MP adapter covers both ports.  The wifi library's two-MP-adapter split persists because the per-substrate hardware knobs differ (ESP32 needs `reconnects`, CYW43 needs `pm`); the sockets library has no such per-substrate divergence.

CP TLS path uses the on-board `ssl` module directly — Decision 0015's minimum supported board class (Pi Pico W, ESP32-S2/S3, ESP32-S3 Feather native wifi) all ship `ssl` on current LTS firmware, so `tls_client_socket(context=...)` works the same on every supported runtime.  Legacy radios that lack `ssl` (AirLift / WIZNET5K-pre-mbedTLS) aren't in scope; users on those boards stay on the `adafruit_connection_manager` ecosystem.

#### Why this phase exists

Source-level research confirmed the runtimes do not share a usable common socket shape:

- **CircuitPython** has no raw `socket` module (only `socketpool.SocketPool(radio)`), no `recv()` (only `recv_into()`), no `ssl` module (TLS via radio `TLS_MODE` flag).
- **MicroPython** has stdlib `socket` with both `recv()` and `recv_into()`, `ssl` module shipped on ESP32 and on Pi Pico W (both via mbedTLS, `MICROPY_SSL_MBEDTLS=1` in current 1.26 source).
- **CPython** has stdlib `socket` + stdlib `ssl`.
- `adafruit_connection_manager` solves the CP side but is CP-only.

Without this library, every downstream networking library re-implements the same shim or picks a runtime and abandons the other.

#### Public surface

```python
from chumicro_sockets import tcp_client_socket, tls_client_socket, ssl_context_with_ca, TCPClientSocket
from chumicro_sockets.testing import FakeSocket

# Plain TCP
sock = tcp_client_socket("broker.example.com", 1883, radio=wifi.radio)

# TLS, runtime default CA store
sock = tls_client_socket("broker.example.com", 8883, radio=wifi.radio)

# TLS with injected custom-CA context (CPython / MP ESP32 / MP Pico W)
ctx = ssl_context_with_ca(ca_pem=CA_PEM)
sock = tls_client_socket("broker.example.com", 8883, context=ctx, radio=wifi.radio)

sock.setblocking(False)
sent = sock.send(packet_bytes)                     # int
nbytes = sock.recv_into(rx_buffer, 256)            # int; OSError(errno=11) on EAGAIN
fd = sock.fileno()                                 # for select.poll().register(fd, ...)
sock.close()
```

Two sibling factories (`tcp_client_socket`, `tls_client_socket`) so TLS config stays a proper injected dependency rather than an overloaded `ssl=bool|context` flag.  Connection happens inside the factory — callers never see a disconnected socket.  Protocol minimum on the returned object: `send`, `recv_into`, `close`, `setblocking`, `settimeout`, `fileno`.  No `recv()` (CP-incompatible idiom).

#### Tasks

- [ ] New library: `libraries/sockets/` via `scripts/run.py new-library sockets`.
- [ ] `TCPClientSocket` protocol (duck-typed, not ABC).
- [ ] Four adapters under `chumicro_sockets/_adapters/`: `cp.py`, `mp_esp32.py`, `mp_rp2.py`, `cpython.py`.  CP adapter implements the `SocketPool(radio)` memoization + `TLS_MODE` fake-context patterns in-tree (borrowing shape, not dependency, from `adafruit_connection_manager`; rationale in Decision 0031 §5).
- [ ] Adapter selection via `sys.implementation.name` + board probe inside each factory.
- [ ] Two sibling factories: `tcp_client_socket(host, port, *, radio=None)` and `tls_client_socket(host, port, *, context=None, radio=None)`.  No overloaded `ssl=` parameter.
- [ ] `ssl_context_with_ca(ca_pem: bytes) -> ssl.SSLContext` helper for the common "custom CA, default everything else" path.  Raises `UnsupportedSSLConfigError` on CP-radio runtimes so the failure is early and obvious.
- [ ] On CP-radio adapters, passing `context=<SSLContext>` to `tls_client_socket` raises `UnsupportedSSLConfigError` with a message directing the user to load the custom CA via the radio's board-level config.  `context=None` routes through the radio's default trust store.
- [ ] `testing.FakeSocket` — full protocol, scripted recv sequences, scripted `EAGAIN` injection, `sent` bytearray assertion surface.
- [ ] Host-side tests on CPython covering protocol conformance + FakeSocket behavior.
- [ ] Cross-runtime tests on CP + MP unix-ports that exercise the adapter selection + FakeSocket.
- [ ] `libraries/sockets/docs/` explaining why the library exists, comparison to `adafruit_connection_manager` and `umqtt.simple` raw-socket pattern.

#### Acceptance

- `chumicro-mqtt` (Phase 6) imports only from `chumicro_sockets` — no `socketpool`, `socket`, or `ssl` import in MQTT source.
- `FakeSocket` drives MQTT unit tests to 94 % coverage without hitting a real network.
- A minimal TCP echo-client example runs identically on all three runtimes.

### Phase 6: `chumicro-mqtt` refactor ✅

**Shipped 2026-04-26.**  `libraries/mqtt/` — non-blocking MQTT 3.1.1 client (QoS 0+1) built on `chumicro-sockets` + `chumicro-timing`.  Decision 0029 Phase 6's full rewrite scope is in: per-packet-id `InFlightTable` for QoS 1, explicit `ProtocolState` ladder + per-`PendingResponse` tracking (no broad `_waiting_state` lock), `WhenOversized` policy enum, `MQTTClient.check`/`handle` runner contract, no `adafruit_connection_manager` dep.  139 host tests at 94 % cov + 6 live Mosquitto integration tests + 6 host-side `tracemalloc` memory-pressure tests.  On-board perf: `.scratch/run_mqtt_perf.py` deploys a long-running publish/subscribe loop; verified live on all four boards (Lolin S2 CP/MP, Pi Pico W CP/MP) with **0 bytes net heap drift over 30 s**, and a 5-minute soak on Pi Pico W MP at 1 Hz publish (299 publishes / 299 received) also held at 0 bytes drift.

Preserved from the pythonProject3 client: the wire-format primitives (`encode_varlen`, `decode_varlen`, `encode_string`, `topic_matches`), the pre-allocated 256 B steady-state RX buffer with degraded-buffer overflow path, the callback-registration shape (`on_message`, `on_connect`, `on_publish`, etc.) and pattern-routed handlers, will + retain, half-keepalive PINGREQ.

Mosquitto 2.0 macOS quirk encountered + worked around: brew Mosquitto fails with `Error: Out of memory` at startup unless its `setrlimit(RLIMIT_NOFILE)` is dropped via `preexec_fn`.  Same shape works in both the pytest fixture and the perf runner.

### Phase 6 (original): `chumicro-mqtt` refactor

Port and redesign the ~1043-line MQTT client at `a previous-generation MQTT reference implementation` into a new library.  Keep the solid parts; rewrite the parts that got weird.  Land on top of `chumicro-sockets` (Phase 5) and `chumicro-timing` + `chumicro-runner`.  QoS 0 and QoS 1 supported; internal shape permits QoS 2 but it is not implemented.

#### Preserve from the original

- **Packet encoder/decoder primitives** — `_encode_varlen`, `_decode_varlen`, `_encode_string`, `topic_matches` are solid and stay mostly verbatim.
- **Non-blocking loop shape** — `select.poll()` + `ipoll(0)` cooperative dispatch, per-tick incremental work.
- **Pre-allocated 256 B static RX buffer** plus the degraded-state partial buffer for oversized messages; static allocation avoids fragmentation.
- **Callback registration API** — `on_message`, `on_connect`, `on_disconnect`, `on_subscribe`, `on_unsubscribe`, `on_publish`, pattern-routed `on_message_handlers` list.
- **Keepalive via PINGREQ** with `ticks_diff` / `ticks_add` — swap `adafruit_ticks` for `chumicro-timing`.
- **Will / retain** — feature-complete already.

#### Rewrite

- **QoS 1 in-flight tracking.**  Replace the single `_publish_retransmit` boolean and the practice of storing whole `MQTTMessage` objects in `_waiting_state_args` with a dict keyed by `packet_id`: `{packet_id: (msg_bytes, retry_count, deadline_ticks, completion_callback)}`.  Supports multiple concurrent QoS 1 publishes.  PUBACK matching compares bytes against the dict key, not against a live object that could be garbage-collected or mutated.
- **Callback dispatch.**  Remove the `popleft`-then-requeue pattern that desyncs when two publishes race (lines 489-499).  Callbacks for QoS 1 publish-completion are stored in the in-flight dict, keyed by `packet_id`, fired once on PUBACK.  Inbound-message callbacks fire immediately during `_handle_incoming_publish()` as today.
- **State machine.**  Explicit states: `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `DISCONNECTING`, `FAILED`.  Separate `ProtocolState` (connection lifecycle) from `PendingWork` (which specific responses the library is awaiting: CONNACK, SUBACK, UNSUBACK, PINGRESP).  Current code conflates them via `_waiting_state` — the rewrite names the two surfaces independently.
- **Handshake lock.**  Current code refuses to send anything while `_waiting_state` is set.  The rewrite only blocks packets of the *specific* type that would confuse the response (e.g. don't send a second CONNECT while waiting for CONNACK), and allows unrelated work (PUBLISH while waiting for SUBACK) to proceed.
- **Partial-send timeout.**  `_packet_count_that_must_send` counter leak (increment in `_send_from_queue` without a bounded-wait contract) is fixed by giving partial sends their own deadline and aborting into the reconnect path on exceed.
- **Oversized-message policy.**  Current `PARTIAL_STATE_DISCARDING` silently PUBACKs the broker and returns `b""` to user callback.  New policy is a `WhenOversized` enum: `DROP_SILENT` (current behavior, opt-in), `DROP_WITH_EVENT` (default, calls `on_oversized(topic, reported_length)` but still PUBACKs), `DISCONNECT` (treat as a protocol error).
- **Socket layer.**  Remove `adafruit_connection_manager` dependency.  Take a `TCPClientSocket` in constructor; default adapter via `chumicro_sockets.tcp_client_socket(...)`.  FakeSocket drives unit tests.
- **Timer layer.**  Replace `adafruit_ticks` imports with `chumicro-timing` `ticks_ms` / `ticks_add` / `ticks_diff`.
- **Runner integration.**  Implement the `check(now_ms) -> bool` / `handle(now_ms)` contract from Decision 0014.  Running under `chumicro-runner` means the LED-toggle-while-publishing requirement comes for free — per-tick budget caps work done, big blobs chunk naturally.

#### Allow but don't implement

- **QoS 2.**  Reserve `packet_type` constants (PUBREC 0x50, PUBREL 0x62, PUBCOMP 0x70) and allocate a parallel in-flight dict shape that would hold PUBREC / PUBREL / PUBCOMP state.  Do not wire handlers.  Document that the state-dict shape is forward-compatible.  Tests assert QoS 2 raises `UnsupportedQoSError`.

#### Tasks

- [ ] New library: `libraries/mqtt/` via `scripts/run.py new-library mqtt`.
- [ ] Port `_encode_varlen`, `_decode_varlen`, `_encode_string`, `topic_matches`.
- [ ] Port static-buffer RX + degraded-state partial buffer.
- [ ] Implement new `ProtocolState` + `PendingWork` state machines.
- [ ] Implement per-`packet_id` in-flight dict for QoS 1.
- [ ] Implement `WhenOversized` policy.
- [ ] Implement `MqttService` as a runner service (`check` / `handle`).
- [ ] Sit on `chumicro-sockets`; no direct `socketpool` / `socket` / `ssl` imports.
- [ ] Use `chumicro-timing` for all time math.
- [ ] `testing.py` with `FakeMqttBroker` (drives a FakeSocket with scripted CONNACK / SUBACK / PUBACK / PUBLISH sequences) to reach 94 % coverage.
- [ ] Host-side tests: state machine, QoS 1 concurrent publishes, PUBACK matching, oversized-message policy matrix, callback dispatch order, partial-send timeout, reconnect after socket close.
- [ ] Cross-runtime tests on CP + MP unix-ports for the state machine.
- [ ] Functional test on the home testbed: publish + subscribe against a real broker on both a CP board and a MP board.
- [ ] Example: `libraries/mqtt/examples/publish_heartbeat.py` runnable on all three runtimes.
- [ ] Rock-solid `libraries/mqtt/docs/` — architecture, usage, design rationale, migration guide from `adafruit_minimqtt` and `umqtt.simple`.

#### Acceptance

- Two concurrent QoS 1 publishes with different payloads both get their correct completion callbacks after two PUBACKs in any order.
- A big inbound PUBLISH (say 10 KB) does not stall a sibling runner service — an LED-heartbeat service on the same runner continues to toggle while the PUBLISH is chunking in.
- `WhenOversized.DISCONNECT` closes the socket cleanly and triggers the reconnect path.
- 94 % coverage on `chumicro-mqtt` sources.
- Publish + subscribe round-trip works on at least one CP board and one MP board against a live broker.

### Phase 7: first sensor thing template

End-to-end proving ground for the full stack (deploy + repl + wifi + kvstore + sockets + mqtt + workspace-runtime).

Integration concerns surfaced as the libraries first run together (service lifecycle, runner tick ordering, reconnect ownership, idle-tick CPU cost, etc.) live in [`plans/workstreams/phase-7-integration.md`](phase-7-integration.md).  Each entry there is open / resolved / deferred; resolutions flow back into the affected library's docs so the next consumer doesn't rediscover them.

- [x] Add `things/example_sensor/` to the `ChuMicro-Workspace-Template` repo: reads a temperature (real on-board thermistor when available, synthetic triangle wave otherwise), publishes via mqtt on a heartbeat, persists a boot-counter via kvstore.
- [x] `config.toml` for broker / topic / heartbeat period; deploy-time merge with workspace defaults + secrets.
- [x] Layer-1 functional test (`workbench/workspace/functional_tests/test_sensor_thing_hardware.py::test_sensor_thing_imports_resolve_on_cpython`): proves `app.py` imports cleanly through the chumicro-workspace dep stack on CPython.  Runs without hardware; catches API drift between sensor thing + libraries.
- [x] Layer-2 functional test: deploy → assert phase markers (`sensor: boot #N`, `sensor: connecting to wifi…`).  Shipped as `test_sensor_thing_reaches_boot_phase_marker_on_{micropython,circuitpython}` — uses a fail-fast wifi config (bogus SSID + zero reconnect budget) so `run()` raises `SystemExit` cleanly, letting `Deployer.deploy()` capture execute_output for assertions.  Sidesteps the originally-feared "while True: runner.tick() never terminates" problem entirely — no `chumicro-repl.tail()` observe pattern required for this test.  A streaming `tail()`-with-pattern-matching shape is still on the `../repl-playground.md` wishlist for non-terminating scenarios where fail-fast can't be configured, but Layer-2 itself is done.  Companion `test_sensor_thing_boot_counter_persists_across_deploys_on_micropython` proves kvstore lifecycle across two consecutive deploys.
- [x] Layer-3 functional test: live broker round-trip — `workbench/workspace/functional_tests/test_sensor_thing_hardware.py::test_sensor_thing_publishes_to_live_broker` spawns a LAN-bound Mosquitto fixture, auto-detects the host's LAN IP, runs `mosquitto_sub` as the subscriber, and asserts ≥ 2 heartbeat messages arrive on the configured topic within 60 s.  Skips cleanly when wifi env vars (`CHUMICRO_TEST_WIFI_SSID` / `CHUMICRO_TEST_WIFI_PASSWORD`) are missing or the device isn't in flash mode.  To run on the chumicro-developer's hardware: set the env vars, ensure a flash-mode board is in `devices.yml`, then `pytest -k publishes_to_live_broker`.
- [x] README walkthrough: clone → setup → add-device → edit two files → deploy → see heartbeats.

#### Acceptance

A user clones the template, runs `python run.py setup`, plugs in a board, runs `python run.py add-device`, edits one line of `things/example_sensor/config.toml` with their broker URL, runs `python run.py deploy`, and sees heartbeat messages arriving at their broker while the board's REPL streams to the terminal.  Under ten minutes from clone to first message.

**Phase 7 closed 2026-04-27** — Layer-1, Layer-2, Layer-3, sensor thing, README walkthrough all shipped.

**Application-level OTA carved out** to `plans/workstreams/ota.md` on 2026-04-27 — the idea is preserved as a discrete potential workstream without scope.  Design notes from prior exploration remain in `plans/workstreams/project-workspace-research.md` §OTA.

## Success criteria

- A user goes from `git clone <template-repo>` to a blinking-LED thing deployed on a board they've never connected before, in under ten minutes, on a laptop with only Python and a USB cable.
- The same `things/<name>/` runs on CP + MP + CPython-sim with no code changes when using only cross-runtime libraries.
- A chumicro developer can edit `libraries/timing/src/chumicro_timing/core.py` in their mono-repo clone and see the change in a workspace deploy without publishing.
- Moving a board between USB ports does not require manual `devices.yml` edits.
- Flashing a blank ESP32-S3 to running CircuitPython is a single `run.py add-device` flow with guided prompts.

## Notes

- `chumicro-mqtt` source-of-truth during refactor: read the original at `a previous-generation MQTT reference implementation` and treat it as prior art — reshape, don't port verbatim.
- `workspace.yml` quality knobs (`lint`, `coverage_threshold`) let the user dial their comfort.  Defaults are permissive (lint enabled, no coverage gate).  `AGENTS.md` in the template tells LLM agents how to read them.
- Library sequencing is a guideline, not a hard ordering — Phase 3a and 3b can interleave, and Phase 2 can start before Phase 1 finishes if a developer-pair splits the work.  Phase 4 is the only gate that genuinely requires everything before it.

## Open sub-questions

(from `plans/open-questions.md`)

- Does `chumicro-mqtt` refactor need to land before the first end-to-end sensor template, or can an MQTT-less headless thing be the first proving ground?
- AST parsing sufficient for conditional imports, or does runtime trace-collection on CPython sim earn its keep?
- What does the `devices.yml` round-trip contract promise vs what the YAML library actually preserves on unusual user edits (anchors, merge keys, multi-doc)?

## Resolved feedback

- **ADR vs initiative:** Design tradeoffs live in Decision 0029; execution plan (phases, sequencing, acceptance) lives in this workstream doc.  Split applied 2026-04-21.
- **`run.py new`:** Allowed — it is a `cp -r things/_template` convenience, not a code generator.  No CLI binaries, no PATH linking, no pip install.
