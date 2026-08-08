# Example sweep — stability & shape audit

> 4-board bench sweep of every `libraries/*/examples/*.py` to flush out runtime regressions, deploy-stack quirks, and shape problems with the example set itself.  Sweep harness in `.scratch/sweep_examples.py`; per-deploy logs in `.scratch/sweep_logs/group_<n>/`.

## Status

**Sweep loop closed — 128/128 deploys green across the canonical 4-board matrix** (Lolin S2 CP, Pi Pico W CP, Lolin S2 MP, Pi Pico W MP).  Six groups, stop-on-first-FAIL per group.  Every FAIL was either a real bug fixed mid-sweep or a shape problem that required structural cleanup.  Several follow-ups remain open (see "Open follow-ups" below); those are tracked here rather than retried in the harness.

**Re-validation pass 2026-05-10 — 127/128 PASS + 1 transient flake.**  Re-ran the full sweep after the day's substantial follow-ups (helpers.py refactor x2, 5 examples switched to `helpers.ticks_ms`, ntp library → chumicro_timing + DI alignment, chumicro-wifi detection → `os.uname().machine` whitelist, deploy-example `--tail-seconds` flag, tls_with_custom_ca rewrite).  Initial Group 4 surfaced a known design limitation — `runner/circuitpython_button_led` + `timing/circuitpython_debounce` hardcoded `board.D5` (Wemos-only), AttributeError on Pi Pico W.  Refactored both to a `BUTTON_PIN = ""` override + `BOARD_BUTTON_PINS` whitelist keyed on `board.board_id` (one entry per line: Pi Pico W/2 W → GP14, Lolin S2 mini/pico → D5, Adafruit Feather S2/S3 → BUTTON); autodetect picks the right pin when BUTTON_PIN is empty, explicit override wins when set.  Re-run Group 4 with autodetect: 8/8 PASS on both CP boards.  Group 6's transient FAIL (`websockets/circuitpython_server` @ pi-pico-w-cp at deploy 10/20 — `KeyboardInterrupt` mid-`time.sleep(0.02)` loop) didn't reproduce on manual re-test; cyw43 USB-CDC residue from the immediately-prior client deploy is the prime suspect, but no clear source in the disconnect path.

**Timing analysis from the re-validation sweep:**

| group | S2-cp | PicoW-cp | S2-mp | PicoW-mp |
|---|---|---|---|---|
| smoke (1) | 19.3s | 7.0s | 5.3s | **2.5s** |
| network (6) | 43.8s | 21.8s | — | — |

Lolin S2 CP is 3-10× slower than Pi Pico W MP (the fastest combo) for the same example.  Root cause: S2's slow USB-CDC throughput produces a ~20s rsync floor on `/Volumes/CIRCUITPY` for any deploy (vs PicoW-cp ~6-7s; MP boards bypass entirely via mpremote RAM mode).  Network examples on cyw43 show 1.5-2× run-to-run variance from wifi-up timing (mqtt/circuitpython_telemetry on S2-cp: 35.8 → 52.4 → 57.1s across three runs).  For dev iteration, Pi Pico W MP is the fastest target; for worst-case-production validation, S2 CP is the slowest.

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
- **Bench validation pass — helpers.py refactor + simple_server + two_board_handshake all green.**  Group 6 (CP-only network sweep) re-ran with the refactored examples — 18/18 PASS across `lolin-s2-cp` + `pi-pico-w-cp` for the 8 helpers.py'd library examples (`ntp/circuitpython_ntp_query`, `requests/circuitpython_periodic_get`, `mqtt/circuitpython_telemetry`, `websockets/{client,server}`, `sockets/{circuitpython_udp_echo_client,tcp_roundtrip}`, `msgpack/circuitpython_nvm_settings`, `http_server/circuitpython_simple_server`).  Spot-checked logs confirm the full helpers.py path fired end-to-end: `ntp_query` printed `WIFI_OK ip=192.0.2.29` then `NTP_OK unix_seconds=1778433511` (real query against the public NTP pool, proving the inline msgpack decoder reads creds from `/runtime_config.msgpack` correctly on real hardware); `simple_server` printed `WIFI_OK` + `Server listening on http://192.0.2.21:8080/`.  Workspace-template's `two_board_handshake/` validated **cross-runtime**: server side on `lolin-s2-cp` (CircuitPython) listening at `192.0.2.29:8080`, client side on `pi-pico-w-mp` (MicroPython) POSTing every 5 s.  Five round-trips visible in client tail (`status=201`); server tail logged `sensor=demo-temp value=24.95`; host-side `curl http://192.0.2.29:8080/api/latest` returned the latest reading as JSON.  Repeat-run on Pi Pico W CP after the session settled also confirmed the workspace-deploy boot-shim path (78-byte `code.py`) is healthy — the earlier transient see-the-file timeouts were rapid-reset / FSKit-residue-state artifacts, not a Pi-Pico-W small-file bug.

## Open follow-ups

Each entry has enough context for a cold pickup — file paths, reproducers, fix sketch, effort estimate.

### 1. 8 network examples violate the library-dep rule — SHIPPED + bench-validated

Resolved in the helpers.py migration commit; bench-validated in the follow-on Group 6 sweep — see "Bench validation pass" in "What landed" above.

### 2. Pi Pico W MP firmware lacks built-in `msgpack` — SHIPPED (option (c))

Resolved via the inline-msgpack-decoder approach.  See "What landed" above.  Helpers are now self-contained — no `mip install` needed on Pi Pico W MP.

### 3. `libraries/sockets/examples/tls_with_custom_ca.py` — SHIPPED (option (b'))

**Resolution.** Rewrote the example to embed **ISRG Root X1** (Let's Encrypt's self-signed root, valid through 2035-06-04, sha256 fingerprint `96:BC:EC:06:…:08:C6` matching CT logs) as the `CA_PEM` constant and target `letsencrypt.org:443` for the TLS handshake.  Picked option (b') over (b) (example.com) after the bench check showed `example.com` migrated from DigiCert to Cloudflare/SSL.com — its vendor isn't locked, so embedding "the example.com root" became a moving target.  `letsencrypt.org` is operated by ISRG (the same org that owns the root), so the cert chain is as stable as anything on the public internet gets.

Example shape mirrors `tcp_roundtrip.py`: top-level `wifi_up` via the canonical `helpers.py`, then `ssl_context_with_ca(CA_PEM)` → `tls_client_socket("letsencrypt.org", 443, context=context, radio=radio)` → `GET / HTTP/1.0` → 256-byte recv head.  Docstring rewrote to make the "REPLACE `CA_PEM` with your homelab CA bytes and the host string with your own server" lesson explicit, kept the prior MP mbedTLS substrate quirks (self-signed cert rejection, IP-only SAN issues), and added the chain-rotation recovery hint (`openssl s_client -connect letsencrypt.org:443 -showcerts`).

Marked CP-only via `__chumicro_runtimes__ = ("circuitpython",)` after bench discovery: MicroPython rp2 firmware boots with the system clock at 2021-01-01, and TLS validation fails with `ValueError: The certificate validity starts in the future` against any leaf cert whose `notBefore` is more recent (which `letsencrypt.org`'s leaf is, since LE rotates leaves every ~90 days).  CP doesn't hit this — its clock starts close enough to current via the cyw43 / firmware base.  The MP clock-quirk is now a documented substrate note in the docstring with a one-line workaround pointer (`ntptime.settime()` before TLS) for adapters who want to run it on MP.

**Bench-validated 2026-05-10** on the canonical CP matrix:
- **Pi Pico W CP** (`/dev/cu.usbmodemABCD1234`): `WIFI_OK ip=192.0.2.21` → `sent: GET / HTTP/1.0` → `received 256 bytes (head): b'HTTP/1.0 200 OK\r\nAccept-Ranges: bytes\r\n...'` → `closed cleanly`.
- **Lolin S2 CP** (`/dev/cu.usbmodemEF567890`): `WIFI_OK ip=192.0.2.29` → identical HTTP/1.0 200 OK head → `closed cleanly`.

Both boards completed full TLS handshake against `letsencrypt.org:443` using only the embedded ISRG Root X1 as trust anchor (system store NOT consulted), proving the helper does what it claims.

**Side observation — root-caused + fixed in the same session (#7 follow-on).** Lolin S2 MP was failing every wifi-up call with `RuntimeError: Wifi Unknown Error 0x0102` (`ESP_ERR_INVALID_ARG` from ESP-IDF), reproduced with `tcp_roundtrip.py` too (no TLS).  Root cause: helpers.py's `wlan.config(pm=0xA11140)` (CYW43 power-save magic) was called on every MP board with `try / except (OSError, ValueError)`, but ESP32 raises `RuntimeError` (the catch-all branch in MP's `esp_exceptions_helper`).  Worse, the unhandled exception left the wifi stack in `ESP_ERR_WIFI_STATE` until a hard reset.

Fixed by switching from "fire and hope" to a positive whitelist on the actual board identifier `os.uname().machine`.  Both helpers.py and `chumicro_wifi._adapters.mp` now check `if os.uname().machine in CYW43_MACHINES:` (today: `("Raspberry Pi Pico W with RP2040",)`).  Aligned shape across both: helpers.py uses module-level `_CYW43_MACHINES` constant, chumicro_wifi exports `CYW43_MACHINES` publicly.  Replaces the prior heuristics — helpers.py's first attempt at `sys.platform == "rp2"` and chumicro_wifi's `try: import esp32` (negative-by-elimination).  New CYW43-bearing boards extend the whitelist rather than hoping the inference does the right thing.

chumicro_wifi tests updated: `test_default_stack_detection_on_cpython_is_cyw43` → `test_default_stack_detection_on_cpython_is_espidf` (CPython's machine string isn't in the whitelist so it falls through to espidf, the safe default with try/except guards on its ESP-specific knob).  New `test_default_stack_detection_picks_cyw43_for_pico_w_machine` monkeypatches `os.uname` to assert positive cyw43 detection on the Pi Pico W machine string.  `test_construction_with_default_stack_uses_auto_detect` updated: CPython auto-detect now lands on `mp_esp32` (was `mp_rp2`).

Propagated to all 7 helpers.py + scaffold template (md5-identical post-edit).  `chumicro-wifi` 0.1.0 → 0.2.0 (public detection-behavior shift; pre-1.0 minor).

**Bench-validated 2026-05-10** on both MP boards via two paths:

* **chumicro_wifi adapter detection** via `wifi/connect_to_ap.py`:
  * Pi Pico W MP: `ADAPTER: mp_rp2` → `WIFI_OK ip=192.0.2.2`
  * Lolin S2 MP: `ADAPTER: mp_esp32` → `WIFI_OK ip=192.0.2.16`
* **helpers.py whitelist** via `sockets/tcp_roundtrip.py`:
  * Pi Pico W MP: `WIFI_OK ip=192.0.2.2` → HTTP/1.1 200 OK → closed cleanly (fast — pm= still fires)
  * Lolin S2 MP: `WIFI_OK ip=192.0.2.16` → HTTP/1.1 200 OK → closed cleanly (pm= correctly skipped)

### 4. `chumicro-config` README + docs/index.md + docs/guide.md still document the old `from_dict` pattern — SHIPPED

**Resolution.** All three hand-written doc files rewritten to teach the flat-key `from_config(config, *, prefix=...)` pattern that library code + every consumer (`WifiConfig`, `NTPClient`, `MqttConfig`, `HttpClient`, `WebSocketServer`, `HttpServer`) has been using since the migration in commit `30e2878`.  Key changes: opener tagline reframed from "section-namespaced dict, `<Name>Config.from_dict()`" to "flat-key dict (dotted prefixes like `wifi.ssid`), `<Name>Config.from_config()`"; quick-example one-liner became `WifiService(WifiConfig.from_config(config))` (no per-section dict slice); the library-author template grew the `prefix="wifi"` kwarg to `load_section`; the on-disk runtime-config shape rewritten as a flat dict with dotted keys (with a separate "source TOML stays nested for humans, deploy flattens it" subsection so users see the connection); added a `try_load_section` section covering the soft-load path no doc surface previously taught; `RuntimeConfig` (the dict-like view `load_runtime_config()` returns) named explicitly throughout.  `chumicro-config` 0.2.1 → 0.2.2 (patch — docs-only).  `python scripts/run.py docs` green; full lint + per-library tests green.

### 5. CP-on-ESP32-S2 hard-fault on `tcp_client_socket` to unreachable host with stale wifi state — MOVED OUT

Moved to `plans/open-questions.md` ("Next CP hard fault on stale socketpool state — investigate") on 2026-05-10.  The sweep harness can't trigger it on demand — the original repro path (`tcp_roundtrip` against `127.0.0.1:8000` with stale wifi state) was structurally fixed when the example was rewritten to hit `example.com:80`.  Diagnostic + repro recipe + two fix angles preserved at the new location for the next natural occurrence.

### 6. MicroPython transport's `clean=` kwarg is a no-op — SHIPPED

**Resolution.** `MicropythonTransport.deploy_files(clean=True)` now wipes `:/lib` on the device before the `mpremote fs cp -r` push when `mode="copy"`, mirroring the CP transport's `rsync --delete` semantics for the actual accumulation site.  Top-level user-managed files (`boot.py`, `main.py`, `settings.toml`, `runtime_config.msgpack`) live outside `/lib` and survive unchanged.  Mount mode treats `clean` as a no-op (mount staging is transient by design — nothing on device flash to clean).  New `_clean_device_lib` helper tolerates a missing `/lib` (first deploy on a clean device) by swallowing mpremote's non-zero exit when `rm -r` against a non-existent path fails — "the dir we wanted gone is gone" is the desired post-condition either way.  Removed the `# noqa: ARG002` on the `clean` parameter.

Four new unit tests:

- `test_copy_mode_default_clean_false_does_not_wipe_lib` — additive-by-default contract preserved.
- `test_copy_mode_clean_true_wipes_lib_before_push` — `fs rm` precedes `fs cp` (ordering matters: wiping after the push would clobber the just-deployed payload).
- `test_copy_mode_clean_true_tolerates_missing_lib_dir` — first-deploy case where `/lib` doesn't exist yet still completes the push.
- `test_mount_mode_clean_kwarg_is_no_op` — mount mode never issues `fs rm`.

**Bench-validated 2026-05-10** on Pi Pico W MP: before deploy, `/lib` carried 11 packages from prior sweeps; after `chumicro-workspace deploy-example timing micropython_blink --device pi-pico-w-micropython-board --non-interactive` (deploy-example passes `clean=True` by default), `/lib` had just `chumicro_timing/` — exactly the import-graph's scope.

**Side finding.** Bench validation surfaced a separate pre-existing bug in `ImportGraphSource._device_path_for` that emits filenames with the import-statement case (`Heartbeat.py`) instead of the on-disk case (`heartbeat.py`); CP+FAT32 masks it via case-insensitive lookup, MP+LittleFS doesn't.  Tracked as follow-up #13.

**`chumicro-deploy` 0.12.0 → 0.13.0** — public API behavior change (the `clean` kwarg now does something on MP transport).  Pre-1.0 minor bump.

### 7. CYW43 power-save constant duplication across helpers.py — SHIPPED (option (a))

**Resolution.** Accepted the duplication and tightened documentation per option (a).  Both CYW43 power-save comment blocks in the canonical `libraries/sockets/examples/helpers.py` (the docstring example + the actual code path) now name `chumicro_wifi._adapters.mp.CYW43_PM_DISABLE` as the canonical home + provenance, with a one-line note that example helpers can't import their non-deps which is why each helper carries its own copy.  Updated text propagated byte-identical across all 7 sibling files: `libraries/{sockets,ntp,requests,mqtt,websockets,http_server}/examples/helpers.py` plus the new-library scaffold template at `workbench/workspace/src/chumicro_workspace/_payloads/library_template/helpers.py.template` (md5 verified identical post-edit).

Option (b) (shared `support/example_helpers/` package) considered and skipped — a future 4th wifi-adjacent helper need (RTC sync, mDNS, etc.) is the natural forcing function for revisiting.

### 8. Sweep harness misses output on slow-wifi boards in `--no-tail` mode — SHIPPED (deploy-example side)

**Resolution (deploy-example side).** `chumicro-workspace deploy-example` now exposes `--tail-seconds N`, threading through to `runner.deploy(source, tail_seconds=…)` (the chumicro-deploy plumbing was already complete end-to-end; only the front-door CLI surface was missing).  CP-only — MP transport ignores the kwarg via the existing filter in `_deploy_files_kwargs`.  Help text names the slow-wifi sweep-harness use case explicitly so future operators reach for it without re-deriving.

`FakeTransport.deploy_files` gained a `tail_seconds: float | None = None` kwarg + `last_tail_seconds` attribute so tests can assert the value flowed end-to-end.  Two new deploy-example tests: `test_tail_seconds_flag_flows_to_transport` (asserts `--tail-seconds 30` reaches the transport with `30.0`) + `test_tail_seconds_default_is_none` (asserts no flag → `None`, preserving the prior fall-through-to-transport-default behavior).

**Bench-validated 2026-05-10** on Pi Pico W CP with `requests/circuitpython_periodic_get`:
- Default 10 s window: captured 3 lines (`WIFI_OK ip=…`, `Polling http://example.com/ every 30 s`, one `[1] ERROR=…` cycle).
- `--tail-seconds 45`: captured 4 lines — second polling cycle (`[2] ERROR=…`) appears, proving the longer window catches output that would otherwise land outside the capture.

**Side observation — root-caused + fixed in the same session.** Was tracked here as "request deadline too tight for cyw43 first-call latency"; the actual root cause was a time-base mismatch.  Five examples (requests / mqtt / websockets×2 / http_server) were passing `time.monotonic_ns() // 1_000_000` as `now_ms` to runner-shaped clients whose internal deadline math uses `chumicro_timing.ticks_ms` (wrapping mod 2^29) — different time domains, deadline check fired immediately.  Worked accidentally on fresh-boot boards where both clocks were near 0; broke after multiple deploys this session.  Fixed by adding `ticks_ms` / `ticks_add` / `ticks_diff` to `helpers.py` (inline impl matching `chumicro_timing`'s shape, no chumicro_timing import per the example-dep rule) and switching every example to `from helpers import ticks_ms, ...`.  ntp library was the outlier — it used `time.monotonic` internally; switched to `chumicro_timing` (added as dep) so its deadline math matches the new helpers.ticks_ms shape.  Initial fix only injected `ticks_ms` (matched the prior shape); follow-on commit aligned ntp's DI with the canonical `chumicro_requests` / `chumicro_mqtt` / `chumicro_websockets` / `chumicro_http_server` pattern by accepting all three (`ticks_ms_func` / `ticks_add_func` / `ticks_diff_func`).  Pre-1.0 minor rename: `ticks_ms=` → `ticks_ms_func=`; tests updated.  ntp `chumicro-ntp` 0.2.0 → 0.3.0 → 0.4.0 (chumicro-timing dep + DI shape alignment).  Also converted remaining `time.monotonic`-based wait loops in mqtt + requests examples to ticks per the "ticks for everything" directive.  Bench-validated 2026-05-10 on Pi Pico W CP: `periodic_get` returns `[1] status=200 bytes=528 led_ticks=2`; `ntp_query` prints `NTP_OK unix_seconds=…`; `simple_server` listens at `:8080`.

`chumicro-workspace` 0.16.0 → 0.17.0 (new public CLI flag); `chumicro-deploy` 0.13.1 → 0.13.2 (testing fake gained `tail_seconds` kwarg + `last_tail_seconds` attribute).

**Sweep-harness side (gitignored, so noted not committed).** `.scratch/sweep_examples.py` can now pass `--tail-seconds 45` (or higher) for known-slow groups (network examples on cyw43 boards).  Operator adoption is a one-line config change in the harness when the next sweep runs.

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

### 12. MicroPython 1.28 lacks `TimeoutError` builtin — SHIPPED (docs only)

**Resolution.** Documented in `plans/patterns.md` under a new "Missing builtins on MicroPython 1.28" section, neighboring the existing "Cross-runtime shim" pattern.  Entry covers the symptom (`NameError` on MP), the three established workarounds (library-specific subclass like `HttpTimeoutError` / `WebSocketTimeoutError` for new code, `OSError` directly for helper / glue code, local `class TimeoutError(OSError): ...` if the name is genuinely wanted), and explicitly tells future maintainers not to add a polyfill to `chumicro_compat` — a 2026-05-10 survey found zero callers wanting bare `TimeoutError`, so a compat polyfill would be public API surface with no consumers.

CHU lint rule deferred — the codebase is currently clean and the pattern doc gives future agents the right shape.  Add a `chumicro-checks` rule the first time `raise TimeoutError(` reappears in a cross-runtime tree.

### 13. `ImportGraphSource` resolved class-import aliases as case-mismatched submodule paths — SHIPPED

**Resolution.** Two-part fix in `workbench/deploy/src/chumicro_deploy/sources.py`:

- **`_resolve_module` is now case-strict.**  New `_exists_case_strict(path)` helper lists the parent directory and verifies that the lookup name appears with its exact casing in `iterdir()`.  Necessary on case-insensitive host filesystems (default macOS APFS, NTFS) where `Path.is_file()` returns True for case-mismatched lookups — a `Heartbeat.py` probe succeeds against a real `heartbeat.py`, so the walker couldn't tell `from chumicro_timing import Heartbeat` (a *class* import) apart from `from chumicro_timing import heartbeat` (a *submodule* import).  Without this strictness the class case was treated as a submodule and staged as `Heartbeat.py` on the device, which CP+FAT32 forgave (case-insensitive lookup) but MP+LittleFS rejected (`ImportError: no module named 'chumicro_timing.heartbeat'`).

- **`_device_path_for` uses the on-disk filename, not the import-statement case.**  Defense in depth — for true submodule imports the walker now passes a resolved path whose case matches disk, but writing `resolved_path.name` instead of `dotted_parts[-1] + ".py"` removes a class of bugs where the resolved-path object retains the lookup's case rather than the on-disk one.

**Regression test.** `TestImportGraphSource.test_class_import_does_not_pull_in_case_mismatched_module` builds the exact "class lives in a lowercase module" shape (`timing.heartbeat.Heartbeat`) and asserts: the real submodule lands at `/lib/timing/heartbeat.py`, the class-import alias does NOT produce a `/lib/timing/Heartbeat.py` wrong-case path.  On case-sensitive Linux the test confirms baseline (the bad path never gets created); on case-insensitive macOS APFS the test exercises the fix directly.

**Bench-validated 2026-05-10** on Pi Pico W MP: `chumicro-workspace deploy-example timing micropython_blink --device pi-pico-w-micropython-board --non-interactive` now succeeds where the previous deploy (pre-fix) failed at import.  `/lib/chumicro_timing/heartbeat.py` lands with lowercase filename and the blink entrypoint runs (verified the device-side ImportError is gone; the example silently toggles an LED so no stdout to capture).

**`chumicro-deploy` 0.13.0 → 0.13.1** — patch (bugfix, no API change).

## Reference

- **Sweep harness.** `.scratch/sweep_examples.py`.  Six groups, runs `chumicro-workspace deploy-example <lib> <ex> --device <board> --non-interactive --no-tail` per `(library, example, board)`, classifies stdout against a fail-pattern list, stops the group on first FAIL.  See its module docstring for resume / group-selection flags.
- **Per-deploy logs.** `.scratch/sweep_logs/group_<n>/<lib>__<example>__<board>.log` (gitignored).
- **Aggregate JSON.** `.scratch/sweep_results.json` (gitignored).
- **Bench.** `pi-pico-w-circuitpython-board`, `lolin-s2-circuitpython-board`, `pi-pico-w-micropython-board`, `lolin-s2-micropython-board` per `devices.yml`.  All four plugged in simultaneously; CoolTerm should be disconnected before sweep runs.
- **Helper pattern reference.** `libraries/sockets/examples/helpers.py` — the canonical shape for per-library `examples/helpers.py` files (used by follow-up #1).
- **Related commits.** `4c97ffb7` (4-board sweep + structural cleanup), `30de95ce` (helpers.py pattern + tcp_roundtrip refactor + button-pin compaction).
- **Related ADRs.** [Decision 0049](../../decisions/0049-three-runtime-trinity.md) (CPython is host-test seam, not deploy target), [Decision 0042](../../decisions/0042-library-dependency-policy.md) (library dep policy), [Decision 0059](../../decisions/0059-deploy-example-front-door.md) (deploy-example as front-door command).
