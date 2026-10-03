# Workstream: source and doc defects surfaced by the docs-overhaul research

Status: active

The cold-writer research ledgers for the docs overhaul
([docs-overhaul.md](docs-overhaul.md)) re-derived every claim from source and
found the following defects outside the pages being rewritten. Each row names
the file and lines the ledger cited; verify against the current tree before
fixing, since line numbers drift. Pages inside the overhaul queue are not
listed here; their drift is fixed by their rewrite.

## Tool behavior and text

| # | Defect | Evidence |
|---|---|---|
| S1 | `deploy --no-wipe` help text, the `Deployer.deploy_diff` docstring, and the template README say hand-installed libraries survive an additive deploy; the additive scope still reconciles `/lib` and the entrypoint, so they are deleted | `workbench/deploy/src/chumicro_deploy/protocol.py:158-192`; `deployer.py:283-291`, `339-349`; `workbench/deploy/tests/test_diff_deploy.py:177-201`; `cli/deploy.py:900-917` help text |
| S2 | The firmware-floor warning recommends `python3 run.py install-firmware --device <id>`, which the parser rejects because `--method` is required | `workbench/workspace/src/chumicro_workspace/firmware_support.py:188-194`; `cli/firmware.py:176-178` |
| S3 | The MQTT auth keys the client reads are `mqtt.username` and `mqtt.password`; the starter `secrets.toml` comments put them under `[mqtt.broker]` and `docs/contributing/config-files.md` shows `[mqtt.broker.auth]`, so both documented shapes are ignored | `libraries/mqtt/src/chumicro_mqtt/client.py:236-237`; `_payloads/secrets.toml.template:40-41`; `docs/contributing/config-files.md:47-53` |
| S4 | A missing required config key raises `ConfigManifestError`, which neither `deploy` nor `deploy-example` catches, so the user sees a traceback and exit 1 where the docstring promises exit 2; no CLI test covers it | `cli/examples.py:411-422`, `462-466`; `cli/deploy.py:644-660`; `config_manifest.py:70-77` |
| S5 | The validation message says "required by imported libraries" while the union covers every library in the workspace | `config_manifest.py:286-290` |
| S6 | The missing-`secrets.toml` hint hardcodes `chumicro-workspace setup`; template users run `python3 run.py setup`; sibling hints use `runner_invocation` | `health.py:119-123`, `155-158` |
| S7 | `setup --help` says `--workspace-dir` walks up to `workspace.yml`; `setup` uses the current directory | `cli/setup.py:205-208` |
| S8 | `.gitignore:77-92` comments name `_workspace_template/`, which does not exist | `.gitignore:77-92` |
| S9 | `micropython_transport.py` docstring says top-level files survive `clean`; the code clears the whole root except the keep set | `workbench/deploy/src/chumicro_deploy/micropython_transport.py:726-729`, `783-788` |
| S10 | `bootstrap` prints a footer suggesting a bare `deploy`, which fails with "multiple projects" in a template workbench that ships `projects/example_sensor` | `cli/bootstrap.py:21-36`; `workspace.py:107-108` |
| S11 | `repl --tail` sets one deadline from `seconds` before the read loop and keeps it across a reconnect, so replug time counts against the tail window; the `reconnect_seconds` docstring says the window is additional to `seconds` | `workbench/repl/src/chumicro_repl/_follow.py:128-130` (docstring), `156-159` (deadline), `173-200` (reconnect inside the loop) |
| S12 | The traceback highlighter's header pattern requires `Traceback (most recent call last):` followed by a bare `\n`; the decoded serial text is never CRLF-normalized, so a board's `\r\n` line endings would defeat the match. Hardware confirmation open (wiring ledger U6) | `workbench/repl/src/chumicro_repl/patterns.py:73-77`; `_follow.py:205` and `framing.py:99-125` (no `\r` handling) |
| S14 | The `deploy-example` tail comment says the user presses Ctrl-D to leave the chumicro-repl session; Ctrl-X exits and Ctrl-D soft-reboots the board | `workbench/workspace/src/chumicro_workspace/cli/examples.py:503-506`; `workbench/repl/src/chumicro_repl/line_mode.py:760-762`; `tui.py:464-466` |
| S15 | The `deploy-example --tail` help says the command drops into `chumicro-repl tail` to follow the example's output; the code opens an interactive chumicro-repl session (line mode on a terminal), which shows later board output only after an entered line, so a result printed after the 10 s capture waits until the user presses Enter | `workbench/workspace/src/chumicro_workspace/cli/examples.py:503-510`, `598-604`; `workbench/repl/src/chumicro_repl/cli.py:85-97`, `118-121`; `line_mode.py:615-629`, `643-712` |
| S16 | The CircuitPython transport's autoreload docstring says a soft reboot resets `supervisor.runtime.autoreload` to on, so no restore is needed; CircuitPython 10.2.0 enables auto-reload only in its startup block after a reset or power-up, so every flash deploy leaves the board with auto-reload off until the next power cycle, and a later hand-copied `code.py` does not restart the program | `workbench/deploy/src/chumicro_deploy/circuitpython_transport.py:405-421`, `1934-1946`; `.tools/circuitpython-10.2.0/main.c:1101-1107`; `supervisor/shared/reload.c:42-49` |
| S13 | The probe-failure diagnosis runs under the MicroPython transport, whose held-or-denied-port text is mpremote's `failed to access <port> (it may be in use by another program)` with no errno; the serial-unreachable markers do not include `failed to access`, so a busy or permission-denied port falls through to `NO_PROBE_RESPONSE` and prints the blank-ESP32 esptool advice | `workbench/deploy/src/chumicro_deploy/recovery.py:36-46` (the mpremote text); `workbench/workspace/src/chumicro_workspace/onboarding.py:151-158`, `344-369`; `cli/_common.py:212-238` (transport default `micropython`) |
| S17 | CircuitPython's connector returns a blocking socket; the generator TCP demo passes it directly to helpers that yield only on EAGAIN, so a send or receive can block the runner. The explicit-service demo sets nonblocking mode. The generator README documents the required correction; executable behavior remains unchanged. | `libraries/sockets/src/chumicro_sockets/_adapters/cp.py:197-211`; `generators.py:connect,send_all,recv_until`; `demos/sockets_runner_connector/app.py:echo_run`; CircuitPython 10.2.0 raspberrypi `Socket.c:556-595,700`; host reproduction `.scratch/cold-writer/system/check-cp-generator-blocking.py` |
| S18 | LittleFS storage treats every file-open `OSError` as empty storage, including access or I/O failures. `KVStore`'s class docstring promises that an unreadable filesystem raises. The persistence rewrite must distinguish detected corruption from an empty mapping without treating emptiness as a reliable diagnosis. | `libraries/kvstore/src/chumicro_kvstore/_backends/mp_littlefs.py:load`; `libraries/kvstore/src/chumicro_kvstore/core.py:KVStore.__init__,reload` |
| S19 | FSKit detection returns `False` for unavailable commands, missing process, timeouts and nonzero diagnostic exits. The recovery handler interprets any false result after recovery as `FSKit wedge cleared.`. A failed diagnostic therefore cannot establish recovery; the troubleshooting brief requires a successful real file/deployment operation. | `workbench/deploy/src/chumicro_deploy/macos_fskit.py:detect_fskit_wedge`; `workbench/workspace/src/chumicro_workspace/cli/health.py:_fix_fskit_wedge` |

## Documentation outside the overhaul queue

| # | Defect | Evidence |
|---|---|---|
| D1 | ADR 0024 shows `circup install chumicro-timing` with a hyphen; circup rejects hyphenated names | `plans/decisions/0024-mip-mpy-folder-serving.md:51`; circup 3.1.0 `command_utils.py` |
| D2 | The workspace guide says circup uses hyphens, that a MicroPython board needs WiFi for `mpremote mip`, and that hand-installed files survive a later deploy | `workbench/workspace/docs/guide.md:231`, `238` |
| D3 | The workspace guide's config example uses `[mqtt] host` (the client reads `mqtt.broker.host`) and a project name `back-porch`, which `new` rejects | `workbench/workspace/docs/guide.md:180-185` |
| D4 | The workbench template README uses `circup install chumicro-wifi` and says circup uses hyphens; it also says `--no-wipe` keeps hand installs | template `README.md:158`, `220-237` (ChuMicro-Workbench-Template `main`) |
| D5 | ADR 0078 says re-adding a library leaves its tree alone and names a `--pin` flag; the code backs up and replaces the tree and the flag is `--version` | `plans/decisions/0078-library-acquisition-is-host-local.md:17-22`; `library.py:140-179` |
| D6 | ADR 0057 says `find_project_config` accepts a legacy `config.toml` and names "ChuMicro-Workspace-Template"; the code checks only `project_config.toml` and the repository is ChuMicro-Workbench-Template | `plans/decisions/0057-two-file-config.md:15`, `31`; `deploy_source.py:54-69` |
| D7 | ADR 0111 says a fresh workspace defaults to experimental until stable is complete; the code default is stable | `plans/decisions/0111-workspace-acquisition-coherence.md:18`; `curated_libraries.py:57-62` |
| D8 | `libraries/README.md` lists nRF52840 as likely to work; ADR 0015 lists it unsupported (no `deque` on CircuitPython) | `libraries/README.md:34`; `plans/decisions/0015-board-architecture-support.md:102` |
| D9 | The bundle README template and `bundle_layout.py` say mpy v6 means "MicroPython 1.24+"; format 6 dates from v1.19 and the project floor is 1.27 | `scripts/templates/bundle_readme.md.template:48`; `scripts/bundle_layout.py:37-39` |
| D10 | `libraries/wifi/README.md:85` says `connect_to_ap.py` and the acceptance test skip silently without credentials; the example raises and the tests skip visibly at collection | `libraries/wifi/README.md:85`; `examples/connect_to_ap.py:27-28`; `functional_tests/conftest.py:12-18` |
| D11 | Example docstrings cite a per-example `examples/config.toml` that does not exist; examples get `secrets.toml` only | `libraries/mqtt/examples/telemetry.py:17-19`; `libraries/requests/examples/periodic_get.py:12-14`; `example_source.py:79-81` |
| D12 | `libraries/config/docs/guide.md:157-177` shows `[wifi] password` in `project_config.toml` and says the tool merges per-library defaults; the pipeline merges `secrets.toml` and `project_config.toml` only | `libraries/config/docs/guide.md:155-177`; `pipeline.py:52-57` |
| D13 | `workspace.py:13` calls `workspace.yml` "gitignored defaults + credentials" | `workbench/workspace/src/chumicro_workspace/workspace.py:10-17` |
| D14 | `docs/contributing/device-testing.md:196` says the on-device test hits a silent-skip path; the plugin skips visibly; line 202 omits ntp from the libraries that need WiFi credentials | `docs/contributing/device-testing.md:196`, `202` |
| D15 | Template `examples/wifi_only/README.md:42-45` says bad credentials show repeated `wifi: failed`; with the default `reconnect_max` the app prints `wifi: connecting` repeatedly | template `examples/wifi_only/README.md:42-45`; `libraries/wifi/src/chumicro_wifi/service.py:222-238` |
| D16 | ADR 0015's context summary lists Broadcom, NXP i.MX RT, and Renesas RA as supported architectures; its decision tiers name only the ESP32 family, RP2040, and RP2350, and `board-quirks.md` names four families | `plans/decisions/0015-board-architecture-support.md:59-64` against `85-104`; `docs/troubleshooting/board-quirks.md:26` |
| D17 | Workspace README and guide promise registry refresh on every probe and runtime changes under `add-device --force`; `probe` only prints identity, and the force path updates address, firmware version and hardware while retaining the existing runtime field. Normal target resolution uses the saved address without UID rebinding. | `workbench/workspace/README.md:101`; `workbench/workspace/docs/guide.md:82-90`; `workbench/workspace/src/chumicro_workspace/cli/devices.py:_cmd_probe,_cmd_add_device`; `cli/_common.py:_resolve_device`; `workbench/deploy/src/chumicro_deploy/config/default.py:_normalize_device_entry` |
| D18 | Decision 0017 names `CFLAGS_EXTRA` and `_build_env()` and calls the RingIO workaround self-removing. The preparation code uses `build_environment()` to append the disabling flag to `CFLAGS`; an upstream repair does not automatically remove the explicit zero. | `plans/decisions/0017-circuitpython-ringio-bug.md`; `scripts/prepare_circuitpython.py:prepare_circuitpython`; `scripts/shared.py:build_environment` |
| D19 | Runtime-config writer docstring says CircuitPython cannot decode MessagePack float64. Pinned CircuitPython accepts marker `0xcb`; the portable pure decoder requires float32. `use_single_float=True` remains correct for the shared format. | `workbench/workspace/src/chumicro_workspace/writer.py:11-18`; `.tools/circuitpython-10.2.0/shared-module/msgpack/__init__.c:441-449` |
| D20 | Drive-verification docstring says an existing `boot_out.txt` lets a single board skip serial probing. That branch calls `probe_implementation()` before comparing mounted and serial identities. | `workbench/deploy/src/chumicro_deploy/circuitpython_transport.py:_verify_drive_for_board` |

## Validation history

- 2026-09-27: opened from the wiring-wifi and install research ledgers and three
  start-here brief reviews. Nothing fixed yet.
- 2026-10-02: S17 reproduced with the real adapter/helpers and a fake socket,
  without hardware or network I/O. Pinned runtime source confirms blocking by
  default. Runner guide sample now selects nonblocking mode; demo READMEs name
  synchronous DNS and the CircuitPython limitation. Library/demo behavior is
  unchanged.
- 2026-10-02: D17 re-derived from registry handlers and normalization. Board
  connection brief instructs explicit address refresh and runtime correction;
  adjacent package documentation remains queued separately.
- 2026-10-02: S18, D18 and D19 re-derived from storage, build helpers and pinned
  native decoder source. Remaining briefs use the verified behavior; no
  executable product changes made.
- 2026-10-02: S19 and D20 re-derived from host recovery and drive-identification
  code. macOS brief separates a diagnostic result from observed recovery.
