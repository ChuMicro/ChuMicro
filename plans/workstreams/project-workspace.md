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

- [ ] Create `libraries/deploy/` via `scripts/run.py new-library deploy`.
- [ ] Move transport protocol + `MicropythonTransport` + `CircuitpythonTransport` + harness bootstrap from `support/device_transport/` into `libraries/deploy/src/chumicro_deploy/`.
- [ ] Keep `support/device_transport/` as a thin re-export during transition; delete once nothing else imports it.
- [ ] Expose a Python API: `Deployer(device_entry).deploy(source_root, entrypoint)`.  Expose a minimal CLI: `python -m chumicro_deploy deploy --device <id> ...`.
- [ ] Host-side tests parity with existing `support/device_transport/` test coverage.
- [ ] Functional test: deploy a minimal app to at least one CP and one MP board via the new package.

Acceptance: chumicro's own `test-device` orchestration uses `chumicro-deploy` via its Python API, no behavior change.

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

- [ ] New library: `libraries/wifi/`.
- [ ] Non-blocking `WifiService` implementing runner `check`/`handle` protocol.
- [ ] Backoff + reconnect.  Works on CP (`wifi.radio`), MP (`network.WLAN`), and CPython-stub (always "connected", for sim).
- [ ] Host-side tests with `FakeWifi` in a `testing.py` submodule.
- [ ] Functional test: connect to the home testbed network, publish a heartbeat.

### Phase 3b: `chumicro-settings`

Tracked in `next-up.md`; coordinate merge window with Phase 3a since `chumicro-wifi` consumes it for credential storage.

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
