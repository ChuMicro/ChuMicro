# Example sweep — stability & shape audit

> 4-board bench sweep of every `libraries/*/examples/*.py` to flush out runtime regressions, deploy-stack quirks, and shape problems with the example set itself.  Sweep harness in `.scratch/sweep_examples.py`; per-deploy logs in `.scratch/sweep_logs/group_<n>/`.

## Status

**Sweep loop closed — 128/128 deploys green across the canonical 4-board matrix** (Lolin S2 CP, Pi Pico W CP, Lolin S2 MP, Pi Pico W MP).  Six groups, stop-on-first-FAIL per group.  Every FAIL was either a real bug fixed mid-sweep or a shape problem that required structural cleanup.  Several follow-ups remain open (see "Open follow-ups" below); those are tracked here rather than retried in the harness.

## What landed

- **Recovery hint corrected (`FLASH_COPY_FAILED`).**  `workbench/deploy/src/chumicro_deploy/recovery.py` — dropped the wrong "msdosfs read-only flag, RESET clears it" framing; reformat (`chumicro-workspace reset-board --yes`) is now the primary recovery, with RESET demoted to optional pre-step.  Same correction applied to the test docstring at `workbench/deploy/tests/test_circuitpython_transport.py:1995-2001`.  User feedback: read-only-after-rsync is repeatable across resets in real bench experience, not a transient hiccup.
- **`devices.yml` drive paths corrected.**  Lolin S2 CP and Pi Pico W CP `circuitpy_drive_path` entries were swapped vs `boot_out.txt` UIDs.  Fixed in place; gitignored so the change is bench-only.
- **Eight cpython-only / template-shaped examples removed.**  `libraries/{http_server,mqtt,ntp,requests,sockets,websockets,wifi}/examples/quickstart.py` (7 fake-using doctest-shaped files) + `libraries/sockets/examples/udp_echo_loopback.py` (CPython-only loopback).  All imported `chumicro_*.testing` fakes (CPython-only by `__chumicro_runtimes__` marker) or were CPython-only templates per their docstrings.  Each library still has board-deployable siblings.  Per-library README + `docs/guide.md` rows updated.
- **`wifi/examples/connect_to_ap.py` written.**  Real wifi-up demo replacing the deleted FakeWifi quickstart.  Reads `wifi.ssid` / `wifi.password` from `runtime_config.msgpack`, prints state transitions + IP.  Validated 4/4 across the canonical bench.
- **Four `quickstart.py` files renamed to descriptive names**: `events/pub_sub_drain.py`, `kvstore/boot_counter.py`, `logging/stream_handler.py`, `wifi/connect_to_ap.py`.  Scaffold template renamed too: `quickstart.py.template` → `basic_usage.py.template`; `scaffold.py` + tests updated.  No more `quickstart.py` files in `libraries/*/examples/` — every example name describes what it shows.
- **`config/examples/end_to_end.py` modernized to flat-key `from_config(config, *, prefix=...)`** matching the library shape.  The prior `from_dict(section_dict)` shape predated the flat-key migration (commit `30e2878`) and crashed at deploy with `TypeError: load_section() missing 1 required keyword-only argument: 'prefix'` on every runtime.
- **`sockets/examples/tcp_roundtrip.py` rewritten** to point at `example.com:80` with HTTP GET + a per-library `helpers.py` for the wifi-up step (raw `wifi.radio` / `network.WLAN` primitives — no chumicro-wifi import, since chumicro-sockets doesn't declare it as a dep).  Was a CPython-targeted template hitting `127.0.0.1:8000` (no listener on a board), causing `EHOSTUNREACH` cleanly on Pi Pico W CP and a hard fault on Lolin S2 CP after stale wifi state.
- **CP button examples compacted to direct `board.D5`** with a one-line "edit per board" comment naming Pi Pico W (`board.GP14`) and Feather (`board.BUTTON`) overrides.  An earlier `BUTTON_PIN = ""` + `getattr` autodetect-fallback was over-engineered for the "user edits one line" use case.
- **`deploy-example` now wipes stale `lib/` packages by default**, with `--no-clean` to opt out.  Plumbed `clean: bool` through `Deployer.deploy()` → `transport.deploy_files()` → `flash_drive.rsync(delete=clean)` for the CP transport.  Default `False` preserves the existing `chumicro-workspace deploy` behavior; deploy-example explicitly passes `clean=True` (and accepts `--no-clean` to flip back).  MP transport accepts the param as a no-op for symmetry.  `settings.toml` + `boot.py` are excluded from the wipe so user runtime config + custom boot logic survive.  `test_deployer.py::test_clean_kwarg_propagates_to_transport` covers the wiring.  Pre-fix: Pi Pico W's 491 KB CIRCUITPY filled at 98 % after 7 different examples accumulated lib/ packages, blocking the rest of the sweep.
- **`scripts/verify_examples.py` learned `__chumicro_runtimes__` markers + sibling-import resolution.**  Files declaring a non-CPython runtime in the marker are treated as hardware-mode (skipping platform-built-in checks), matching the existing `circuitpython_*` / `micropython_*` filename-prefix behavior.  The verifier also adds each example's parent dir to `sys.path` during checking so `from helpers import wifi_up` resolves against the sibling helper.  Six new tests in `scripts/tests/test_verify_examples.py::TestHasHardwareRuntimeMarker`.
- **`example_source.py` adds `examples/` to `ImportGraphSource` search paths.**  Sibling `helpers.py` in a library's `examples/` directory now rides along to `/lib/helpers.py` on the device at deploy time.  Without this, `from helpers import …` from an example's entrypoint would resolve via the host import path during static analysis but fail on the device.
- **Sweep harness classifier extended for hard-fault / safe-mode markers.**  `Hard fault: ` / `Running in safe mode` / `CircuitPython core code crashed hard` now classify as FAIL.  Pre-fix, a hard fault on Lolin S2 CP (during `tcp_roundtrip` against an unreachable host with stale wifi state) was misclassified as PASS because none of the original markers matched.
- **8 network examples migrated to per-library `helpers.py` pattern.**  `libraries/{ntp,requests,mqtt,websockets,http_server}/examples/helpers.py` created mirroring the canonical sockets shape (`runtime_config()` + `wifi_up(ssid, password) -> (radio, ip)`, raw runtime primitives, `__chumicro_runtimes__` marker so verify_examples skips platform imports).  Eight examples refactored to drop `chumicro_wifi` + `chumicro_config` imports and the `_drive_until` / `service.check / handle / state` boilerplate: `ntp/circuitpython_ntp_query.py`, `requests/circuitpython_periodic_get.py`, `mqtt/circuitpython_telemetry.py`, `websockets/{circuitpython_client,circuitpython_server}.py`, `http_server/{circuitpython_two_thing_server,circuitpython_two_thing_sensor}.py`, `sockets/circuitpython_udp_echo_client.py`.  Examples now import only their owning library + the local `helpers` module (plus `chumicro_requests` from the http_server sensor example, which talks HTTP outbound).  `helpers.runtime_config()` returns a plain dict (raw msgpack decode) that all `from_config()` factories accept directly per `chumicro_config.section.load_section`'s dict-or-RuntimeConfig contract.  Renamed `_runtime_config` → `runtime_config` in sockets/helpers.py for the public API.  `verify_examples.py` clean (48 examples), full lint clean.  Bench validation queued.
- **`helpers.py` made truly standalone — inline msgpack decoder + scaffold integration.**  Replaced the `try: import msgpack except ImportError: return {}` path with a 60-line inline decoder covering every msgpack type the `chumicro-workspace` deploy pipeline produces (nil / bool / every int width / float 32+64 / str / bin / array / map; no ext / timestamp).  Pi Pico W MicroPython no longer needs `mpremote mip install msgpack` — same code path on every runtime.  Decoder validated against the reference `msgpack` impl on the host across small + large maps, all int widths, every string-length tier, nested structures, floats, bools, and arrays.  Single `if not ssid or ssid == "your-wifi-ssid"` placeholder check replaces the prior 3-element sentinel set.  All 6 library `helpers.py` files now identical (md5 verified) — single canonical version.  Promoted to library scaffold: `workbench/workspace/src/chumicro_workspace/_payloads/library_template/helpers.py.template` ships with every `python scripts/run.py new-library`, so a fresh library starts with a working copy that the user deletes if its examples don't need wifi.  `new-library` skill updated with delete-if-unused instruction.  Closes follow-up #2.
- **`http_server` library examples reshaped.**  Deleted `circuitpython_two_thing_sensor.py` (imported `chumicro_requests` which `chumicro-http-server` doesn't declare as a dep — same architectural rule that motivated the helpers.py refactor) and replaced `circuitpython_two_thing_server.py` with a single-board `circuitpython_simple_server.py` that demonstrates the API with `GET /`, `GET /api/uptime`, `POST /api/echo` routes and tells users to drive it with `curl` from their laptop.  Two-board patterns now live exclusively in the workspace template's `examples/two_board_handshake/{server,client}/`.  README + docs/guide.md tables updated; `workbench/workspace/` 0.14.0 → 0.15.0 captures the prior `helpers.py.template` scaffold integration.
- **Bench validation pass — helpers.py refactor + simple_server + two_board_handshake all green.**  Group 6 (CP-only network sweep) re-ran with the refactored examples — 18/18 PASS across `lolin-s2-cp` + `pi-pico-w-cp` for the 8 helpers.py'd library examples (`ntp/circuitpython_ntp_query`, `requests/circuitpython_periodic_get`, `mqtt/circuitpython_telemetry`, `websockets/{client,server}`, `sockets/{circuitpython_udp_echo_client,tcp_roundtrip}`, `msgpack/circuitpython_nvm_settings`, `http_server/circuitpython_simple_server`).  Spot-checked logs confirm the full helpers.py path fired end-to-end: `ntp_query` printed `WIFI_OK ip=172.16.1.29` then `NTP_OK unix_seconds=1778433511` (real query against the public NTP pool, proving the inline msgpack decoder reads creds from `/runtime_config.msgpack` correctly on real hardware); `simple_server` printed `WIFI_OK` + `Server listening on http://172.16.1.21:8080/`.  Workspace-template's `two_board_handshake/` validated **cross-runtime**: server side on `lolin-s2-cp` (CircuitPython) listening at `172.16.1.29:8080`, client side on `pi-pico-w-mp` (MicroPython) POSTing every 5 s.  Five round-trips visible in client tail (`status=201`); server tail logged `sensor=demo-temp value=24.95`; host-side `curl http://172.16.1.29:8080/api/latest` returned the latest reading as JSON.  Repeat-run on Pi Pico W CP after the session settled also confirmed the workspace-deploy boot-shim path (78-byte `code.py`) is healthy — the earlier transient see-the-file timeouts were rapid-reset / FSKit-residue-state artifacts, not a Pi-Pico-W small-file bug.

## Open follow-ups

Each entry has enough context for a cold pickup — file paths, reproducers, fix sketch, effort estimate.

### 1. 8 network examples violate the library-dep rule — SHIPPED + bench-validated

Resolved in the helpers.py migration commit; bench-validated in the follow-on Group 6 sweep — see "Bench validation pass" in "What landed" above.

### 2. Pi Pico W MP firmware lacks built-in `msgpack` — SHIPPED (option (c))

Resolved via the inline-msgpack-decoder approach.  See "What landed" above.  Helpers are now self-contained — no `mip install` needed on Pi Pico W MP.

### 3. `libraries/sockets/examples/tls_with_custom_ca.py` design call (medium effort)

**Symptom.** Dropped from the sweep matrix because the example's stub `CA_PEM` (`b"-----BEGIN CERTIFICATE-----\n# Replace with your real CA bytes.\n-----END CERTIFICATE-----\n"`) can't validate any real endpoint — TLS handshake fails immediately regardless of host.  The example is a TEMPLATE, not a runnable demo.

**Three options (each ~half-day):**
- **(a) Delete.** Same shape as the deleted `udp_echo_loopback.py`; move the API illustration into `libraries/sockets/docs/guide.md` as a fenced code block.  Loses the deployable file but keeps the API documentation.
- **(b) Embed ISRG Root X1 (~1.4 KB PEM)** and point at `letsencrypt.org:443`.  Becomes runnable as-is.  Trade-off: ~1.4 KB of PEM in the example, cert valid until 2030 (when ISRG retires it).  Lots of public services use Let's Encrypt, so the cert is broadly useful as a template starter.
- **(c) Read CA from a deploy-time config key** (`tls.ca_pem_path` in `runtime_config.msgpack` pointing at a host-side bundle the workspace ships).  Cleanest separation but adds workspace-template machinery.

**Repro.** Currently no bench repro since the file's commented out of the sweep harness Group 6 matrix.  To re-enable: uncomment `("sockets", "tls_with_custom_ca")` in `.scratch/sweep_examples.py`; deploy will fail with TLS validation error on every board.

### 4. `chumicro-config` README + docs/index.md + docs/guide.md still document the old `from_dict` pattern (medium effort)

**Symptom.** All three doc files document `WifiConfig.from_dict(config["wifi"])` (nested-section-dict pattern) instead of the current `WifiConfig.from_config(config, *, prefix="wifi")` (flat-key pattern).  Library code + every consumer (`WifiConfig.from_config`, `NTPClient.from_config`, `MqttConfig.from_config`, `HttpClient.from_config`, `WebSocketServer.from_config`, `HttpServer.from_config`) + the auto-generated API ref already use flat-key.  The `end_to_end.py` example fix in `4c97ffb7` touched only the example.

**Affected files:**
- `libraries/config/README.md` — has `from_dict` callouts at lines 6, 36, 39, 48, 61.
- `libraries/config/docs/index.md` — line 12.
- `libraries/config/docs/guide.md` — extensive `from_dict` walkthrough, multiple sections.

**Reference.** The auto-generated `libraries/config/site/search.json` (built by `mkdocstrings`) already shows the correct flat-key `load_section(target_class, config, *, prefix, …)` shape — that's the canonical signature.  The hand-written docs need to match.

**Fix shape.** Rewrite the three doc files to mirror the current library shape.  Match the example pattern from `libraries/config/examples/end_to_end.py` (which IS correct).  No code changes needed; docs-only.  Run `python scripts/run.py docs` after to verify the docs build.

### 5. CP-on-ESP32-S2 hard-fault on `tcp_client_socket` to unreachable host with stale wifi state (large effort, hardware-only repro)

**Symptom.** On Lolin S2 CP after a prior websockets-server deploy ran, `tcp_client_socket("127.0.0.1", 8000, radio=…)` produced `Hard fault: memory access or instruction error` → safe mode.  Fresh-boot reproducer (no prior wifi-using deploy) raises a clean `OSError [Errno 104] ECONNRESET` against the same target.  Suggests stale-socketpool state in `chumicro_sockets._adapters.cp` after a prior `socketpool.SocketPool(radio)` left some residual handle.

**Repro (requires bench, Lolin S2 CP):**
1. Deploy `websockets/examples/circuitpython_server.py` to the board: `chumicro-workspace deploy-example websockets circuitpython_server --device lolin-s2-circuitpython-board --non-interactive --no-tail`.  Let it run a few seconds (binds to `0.0.0.0:8765`).
2. Deploy `sockets/examples/tcp_roundtrip.py` (current shape, hits `example.com:80`) to the same board.  This SHOULD now work cleanly because `tcp_roundtrip` was rewritten — the stale-state path that triggered the hard fault was the old `127.0.0.1:8000` shape.
3. To reproduce the original hard-fault path: deploy any code that calls `tcp_client_socket` with an unreachable target after a prior wifi-using deploy.  Hard-fault appears as "CircuitPython core code crashed hard" in the board's serial output.

**Diagnostic note.**  The board recovers cleanly from safe mode after RESET — the FAT volume isn't damaged.  The crash happens inside CP core code (likely the socketpool C implementation), not chumicro_sockets Python code.  The chumicro side may just be triggering a CP-firmware bug.

**Fix sketch.** Two angles:
- (a) Add socket cleanup on close to chumicro_sockets._adapters.cp so a fresh `tcp_client_socket` starts with a clean pool.  Defensive; may not actually trigger the firmware bug.
- (b) File a CircuitPython upstream issue with a minimal repro that bypasses chumicro_sockets entirely (`socketpool.SocketPool(wifi.radio)` → `pool.socket(pool.AF_INET, pool.SOCK_STREAM)` → `connect((unreachable, port))`).  Verify firmware-side responsibility before chumicro-side workaround.

### 6. MicroPython transport's `clean=` kwarg is a no-op (medium effort)

**Symptom.** `MicropythonTransport.deploy_files(clean=True, …)` accepts the kwarg for API symmetry with `CircuitpythonTransport` but doesn't actually clean anything.  Same lib/-accumulation pattern that bit Pi Pico W CP would eventually bite Pi Pico W MP after enough deploys.  Pi Pico W MP's flash is 860 KB usable so the failure threshold is higher than Pi Pico W CP's 491 KB, but the same accumulation happens.

**Affected file.** `workbench/deploy/src/chumicro_deploy/micropython_transport.py:645-654` (`deploy_files` signature) and the body that follows.  The `clean: bool = False` parameter is annotated `# noqa: ARG002 — symmetry with CP transport; not yet plumbed for MP copy mode`.

**Fix shape.**  In `MicropythonTransport.deploy_files`, when `clean=True` and `mode="copy"`, run `mpremote fs rm -r :/lib` (or the per-file equivalent matching the CP rsync excludes — preserve `boot.py` / `main.py` / `settings.toml`-equivalents) before the `mpremote fs cp -r .` push.  Mount mode (`mode="mount"`) doesn't need it — that's transient by design.  Add a unit test mirroring `test_clean_kwarg_propagates_to_transport`.

**Repro.** Deploy several different examples to Pi Pico W MP in sequence; `mpremote fs ls /lib` will show every chumicro_* package from any prior deploy still present.

### 7. CYW43 power-save quirk has to be replicated in every per-library `helpers.py`

**Symptom.** Each `examples/helpers.py` that brings wifi up on MP needs a `try: wlan.config(pm=0xa11140); except (OSError, ValueError): pass` block to disable CYW43 idle power-save (otherwise Pi Pico W connects in 30+ s instead of <2 s).  This is documented in `chumicro_wifi._adapters/mp.py` but examples that bypass chumicro-wifi (per the dep rule) have to know the magic constant themselves.

**Affected files.**  Anywhere `helpers.py` lives — currently only `libraries/sockets/examples/helpers.py` (line ~80).  Will replicate to 6 more files when follow-up #1 lands.

**Fix shape.**  Two options:
- (a) Accept the duplication.  Document the magic constant clearly in each helper; mention chumicro_wifi as the canonical source.
- (b) Promote a shared helper utility into a tree the deploy stack already knows about (e.g. `support/example_helpers/` host-and-device-shipped).  But that's a new top-level decision and would need ADR coverage.

Recommend (a) for now; revisit if we add a 4th library helper pattern beyond wifi (e.g. RTC / time sync).

### 8. Sweep harness misses output on slow-wifi boards in `--no-tail` mode

**Symptom.** `chumicro-workspace deploy-example … --non-interactive --no-tail` captures output for ~2 s post-soft-reboot.  On Pi Pico W (cyw43), wifi-up + first TCP request can take 5-10 s.  The example's `print(...)` lines land OUTSIDE the capture window → harness sees "deploying ..." and nothing else → counts as PASS by exit code but actual output isn't visible.

**Repro.**  Deploy `sockets/tcp_roundtrip.py` to Pi Pico W MP with `--non-interactive --no-tail` directly.  Compare against deploying with `chumicro-repl --tail 30` immediately after — the latter shows the full WIFI_OK + HTTP 200 sequence.

**Fix shape.**  Two-axis:
- Sweep-harness side: `.scratch/sweep_examples.py` should optionally use the longer-tail path for known-slow examples (network ones).  `chumicro-deploy deploy` already has `--tail-seconds N` (per workbench-deploy-reliability Step 3); deploy-example doesn't expose it.
- Deploy-example side: add `--tail-seconds N` to `chumicro-workspace deploy-example`'s flag set, threading through to `runner.deploy(source, tail_seconds=…)` (which already accepts it).

**Effort.** Small (1-2 hours) for the deploy-example flag exposure; harness adoption is a one-line config change.

### 9. Another serial-terminal app holding a port blocks deploys — SHIPPED

**Symptom.** When any other process has a board's USB-CDC port open, the deploy stack's serial open fails with `OSError: [Errno 16] Resource busy`.  CoolTerm is one common holder, but the same pattern fires for any serial-terminal app — Mu, Thonny, screen, minicom, PyCharm / VS Code serial console, an orphan mpremote / chumicro-deploy from a SIGINT'd previous run.  Doesn't matter which app; the symptom is identical.

**Resolution.** Added a `SERIAL PORTS` check to `chumicro-workspace doctor` (`workbench/workspace/src/chumicro_workspace/health.py:check_serial_ports_held`).  Walks every device in `devices.yml`, runs `lsof` (via the existing `chumicro_deploy.recovery.diagnose_port_holders`), and surfaces a WARN finding listing the held ports + PIDs + commands.  Operator runs `chumicro-workspace doctor` before a sweep; if anything is held, the doctor row tells them what to close.  Doctor-only — too heavy for the per-second status loop.  Six unit tests cover Windows skip, no-devices.yml, empty registry, no-holders, held-port reporting, and best-effort behavior on `lsof` errors.  Existing `recovery.py` after-the-fact diagnosis (`_report_port_holders`) unchanged — both surfaces stay useful.

**Bigger options that didn't ship.**

- AppleScript / dbus auto-disconnect (`chumicro-workspace doctor --release-port <id>`).  OS-specific, bigger lift, doesn't generalize across the long tail of holder apps.  Skipped — the doctor diagnosis + manual close path is good enough.
- Sweep-harness fast-fail.  Sweep harness lives in `.scratch/` (gitignored) — option moot for a shipped feature.  Doctor's `SERIAL PORTS` row covers the same need from a checked-in surface.

### 10. `devices.yml` `circuitpy_drive_path` is fragile across boot orders — SHIPPED (option (a))

**Symptom.** macOS assigned CIRCUITPY drive names by mount order: first board → `/Volumes/CIRCUITPY`, second → `/Volumes/CIRCUITPY 1`.  `devices.yml` hard-coded the path at registration time, so a power-cycle / replug that swapped enumeration order silently invalidated it.  `_verify_drive_for_board` already auto-corrected at deploy time, but the field's persisted value was dead weight that papered over an asymmetry between the diff-deploy and full-deploy paths.

**Resolution.** Removed the `circuitpy_drive_path` field everywhere: `Device` dataclass and `CircuitpythonTransport` constructor (chumicro-deploy 0.10.1 → 0.12.0, public API break — but pre-1.0, no compat shim per AGENTS.md), `DeviceEntry` dataclass + YAML loader + writer, CLI `--drive` flag, demo / example / functional-test plumbing.  `_resolve_circuitpy_drive` calls `_circuitpy_volume_candidates()` (which globs every mounted `CIRCUITPY*` directory) and returns the first; `_verify_drive_for_board` runs on every CP-flash op, reads each candidate's `boot_out.txt`, and silently swaps to the UID-matching mount.  The legacy bare-name `find_circuitpy_drive()` shim was dropped in the same change after the user observed it was strictly redundant with `_circuitpy_volume_candidates` + verify.

**Bench-exposed bugs fixed in the follow-on.**  First bench run on a multi-CP-board host with both `CIRCUITPY` and `CIRCUITPY 1` mounted exposed two issues the previous field had been silently papering over:

- **`rsync --delete` was wiping `boot_out.txt`.**  `deploy_files` with `clean=True` (deploy-example's default) excluded `settings.toml` + `boot.py` but not `boot_out.txt` — so each clean deploy stranded the drive without identity info until the next hard reboot.  CP only writes `boot_out.txt` on hard reset; the deploy's soft-reboot doesn't regenerate it.  Without identity info, subsequent deploys couldn't UID-match the right drive on a multi-board host and silently landed on whichever mount happened to come first.  Fixed by adding `boot_out.txt` to the clean-deploy exclude tuple.
- **`_verify_drive_for_board` failed open when `boot_out.txt` was missing.**  Original behavior: read `boot_out.txt` → if absent, return `drive_path` unchanged.  That fall-open silently routed the deploy to whatever `candidates[0]` was.  New strict behavior: when `boot_out.txt` is missing on `drive_path`, probe the connected board and scan every candidate's `boot_out.txt` for a UID/machine match; swap to the matching mount.  When neither the probe nor any candidate yields identity info, raise `CircuitpythonTransportError` pointing the user at the recovery step (hard-reset the board to regenerate `boot_out.txt`) rather than silently mis-routing.  New `_identify_drive_via_probe` helper centralizes the strict path.

Legacy `devices.yml` files carrying the field still load — `Device.from_dict` ignores unknown keys.  ADRs 0027 + 0028 updated in place; troubleshooting + device-testing docs rewritten to match.  Workspace-template repo's `register-board/SKILL.md` updated too.

**Bench-validated 2026-05-10** on a multi-CP-board host (Lolin S2 CP + Pi Pico W CP both plugged, both CIRCUITPY drives mounted, mount order swapped from the initial-deploy session by an intervening Lolin S2 replug).  Three paths exercised end-to-end:

- **Cheap-path** — Pi Pico W deploy when `candidates[0]` already IS its mount: verify reads `boot_out.txt`, matches probe, returns immediately.  `/Volumes/CIRCUITPY/code.py` updated; sibling untouched.
- **UID auto-correct** — Lolin S2 deploy when `candidates[0]` is Pi Pico W's mount: verify reads boot_out, sees Pi Pico W UID, probes Lolin S2 via serial (UID `84722E7490C3`), detects mismatch, scans siblings, swaps to `/Volumes/CIRCUITPY 1`.  `/Volumes/CIRCUITPY 1/code.py` updated; Pi Pico W mount untouched.
- **`boot_out.txt` preservation across clean deploys** — both drives still carry valid `boot_out.txt` after the deploys, so the next sequence can re-verify without needing a hard-reset.

Strict-verify error path + boot_out-missing auto-correct path covered by unit tests rather than bench (`TestDriveVerification.test_raises_when_boot_out_missing_and_probe_unavailable` + `test_auto_corrects_when_boot_out_missing_but_sibling_matches`).

### 11. Library pyproject.toml ↔ src/imports audit — SHIPPED (with surprise)

**Audit run.** AST-walked `libraries/*/src/` for actual cross-library imports (eager + lazy) and compared against each `pyproject.toml`'s `dependencies` block.  Result table:

| Library     | Real imports                                          | Declared deps                                       | Status |
|-------------|-------------------------------------------------------|-----------------------------------------------------|--------|
| compat      | -                                                     | -                                                   | ✓ |
| config      | chumicro_msgpack                                      | chumicro-msgpack                                    | ✓ |
| events      | -                                                     | -                                                   | ✓ |
| http_server | chumicro_config, chumicro_sockets, chumicro_timing    | chumicro-sockets, chumicro-timing                   | ✗ (missing chumicro-config) |
| kvstore     | chumicro_msgpack                                      | chumicro-msgpack                                    | ✓ |
| logging     | -                                                     | -                                                   | ✓ |
| mqtt        | chumicro_config, chumicro_sockets, chumicro_timing    | chumicro-config, chumicro-sockets, chumicro-timing  | ✓ |
| msgpack     | -                                                     | -                                                   | ✓ |
| ntp         | chumicro_sockets                                      | chumicro-sockets                                    | ✓ |
| requests    | chumicro_sockets, chumicro_timing                     | chumicro-sockets, chumicro-timing                   | ✓ |
| runner      | chumicro_timing                                       | chumicro-timing                                     | ✓ |
| sockets     | -                                                     | -                                                   | ✓ |
| timing      | -                                                     | -                                                   | ✓ |
| websockets  | chumicro_sockets, chumicro_timing                     | chumicro-sockets, chumicro-timing                   | ✓ |
| wifi        | chumicro_config, chumicro_timing                      | chumicro-config, chumicro-timing                    | ✓ |

**The original claim (`chumicro-sockets` is missing `chumicro-timing`) was wrong.**  AST scan found zero cross-library imports in `libraries/sockets/src/` — the sockets library is genuinely standalone.  An older codebase shape may have used `chumicro_timing.ticks_ms` for socket-side timeouts, but it's been refactored out.

**Real finding: `chumicro-http-server` is missing `chumicro-config`.**  `HttpServer.from_config()` raises `MissingConfigKey` (imported lazily from `chumicro_config`) when half-TLS configuration is detected (cert_path without key_path or vice versa).  Users without chumicro-config installed get an `ImportError` instead of the proper config-validation error.  Fixed in this commit: added `chumicro-config` to `libraries/http_server/pyproject.toml` `dependencies`; bumped `libraries/http_server/VERSION` 0.2.1 → 0.2.2.

**Effort.** Audit was ~30 min including the AST script.  Fix was ~1 line + a VERSION bump.

### 12. MicroPython 1.28 lacks `TimeoutError` builtin (cross-runtime gotcha)

**Symptom.** `raise TimeoutError(...)` works on CPython + CircuitPython but on MicroPython 1.28 it raises `NameError: name 'TimeoutError' isn't defined`.  Cross-runtime helpers and library code must use `OSError` (or define a local exception class) instead.

**Already in effect.** `libraries/sockets/examples/helpers.py` uses `OSError` for the wifi-connect timeout (line ~63 + ~78) for this reason.  Documented inline.

**Fix shape.** Document this in `plans/patterns.md` under cross-runtime gotchas, alongside existing patterns.  Optional: add a CHU rule that flags `raise TimeoutError(` in cross-runtime tree files (libraries/*/src/, support/test_harness/src/).  CHU-rule version is the rigorous fix; documentation alone is the lighter touch.

## Reference

- **Sweep harness.** `.scratch/sweep_examples.py`.  Six groups, runs `chumicro-workspace deploy-example <lib> <ex> --device <board> --non-interactive --no-tail` per `(library, example, board)`, classifies stdout against a fail-pattern list, stops the group on first FAIL.  See its module docstring for resume / group-selection flags.
- **Per-deploy logs.** `.scratch/sweep_logs/group_<n>/<lib>__<example>__<board>.log` (gitignored).
- **Aggregate JSON.** `.scratch/sweep_results.json` (gitignored).
- **Bench.** `pi-pico-w-circuitpython-board`, `lolin-s2-circuitpython-board`, `pi-pico-w-micropython-board`, `lolin-s2-micropython-board` per `devices.yml`.  All four plugged in simultaneously; CoolTerm should be disconnected before sweep runs.
- **Helper pattern reference.** `libraries/sockets/examples/helpers.py` — the canonical shape for per-library `examples/helpers.py` files (used by follow-up #1).
- **Related commits.** `4c97ffb7` (4-board sweep + structural cleanup), `30de95ce` (helpers.py pattern + tcp_roundtrip refactor + button-pin compaction).
- **Related ADRs.** [Decision 0049](../decisions/0049-three-runtime-trinity.md) (CPython is host-test seam, not deploy target), [Decision 0042](../decisions/0042-library-dependency-policy.md) (library dep policy), [Decision 0059](../decisions/0059-deploy-example-front-door.md) (deploy-example as front-door command).
