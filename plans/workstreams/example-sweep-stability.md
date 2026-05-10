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

## Open follow-ups

Each entry has enough context for a cold pickup — file paths, reproducers, fix sketch, effort estimate.

### 1. 8 network examples violate the library-dep rule — SHIPPED

Resolved in the helpers.py migration commit; see "What landed" above for details.  Bench validation across the 4-board matrix is queued — the static `verify_examples.py` pass is green but on-board execution hasn't been re-run since the migration.

### 2. Pi Pico W MP firmware lacks built-in `msgpack` (small effort, depends on workaround chosen)

**Symptom.** The `examples/helpers.py` pattern's optional `runtime_config.msgpack` read path falls back to in-file constants on Pi Pico W MP because `import msgpack` raises `ImportError`.  Result: `RuntimeError: set WIFI_SSID + WIFI_PASSWORD …` until the user installs msgpack or edits the example.

**Repro.**
```bash
.venv/bin/chumicro-deploy deploy --devices-file devices.yml \
    --device pi-pico-w-micropython-board \
    --file-map .scratch/probe_files.json \
    --entrypoint /main.py
```
Where `.scratch/probe_files.json` is `{"/main.py": "try:\n    import msgpack\n    print('OK')\nexcept ImportError as e:\n    print('FAIL', e)\n"}`.  Pi Pico W MP prints `FAIL no module named 'msgpack'`; Lolin S2 MP and both CP boards print `OK`.

**Workarounds available today:**
- **Per-bench**: `mpremote connect /dev/cu.usbmodem112401 mip install msgpack` (one-time setup).
- **Per-example**: edit `WIFI_SSID` / `WIFI_PASSWORD` constants in the example, the helper falls back to those.

**Long-term fix options:**
- (a) Have `chumicro-workspace setup` opportunistically `mip install msgpack` on every registered MP device.  Aligns with "workspace bootstraps the device's runtime baseline".
- (b) Ship `chumicro-msgpack` to MP boards by default at workspace setup time (already a chumicro-published library; the `chumicro-config` library declares it as a dep already).  Same delivery mechanism as (a).
- (c) Embed a tiny msgpack decoder inline in `helpers.py` — ~50 lines, no deps; worst from a maintenance standpoint.

**Recommended:** option (a) or (b).  Workspace setup already does board-side dep installs for the project's `pyproject.toml` deps; extending to "always include msgpack on MP" is a small change.

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

### 9. CoolTerm interferes with bench sweeps — current workaround is manual disconnect

**Symptom.** When the user has CoolTerm open against a board's USB-CDC port, the deploy stack's serial open fails with `OSError: [Errno 16] Resource busy`.  Recovery requires the user to disconnect CoolTerm in its UI.  Happened 3+ times during this session; sweep paused each time.

**Affected.** Any agent-driven workflow that targets boards a human is interactively monitoring.

**Existing diagnostic.**  `chumicro-deploy probe` already detects the holder and prints `PID 1309: /Applications/CoolTerm.app/Contents/MacOS/CoolTerm` as a hint.  That's already in `recovery.py`'s `PORT_UNAVAILABLE` plan.

**Fix shape options:**
- (a) Add a `chumicro-workspace doctor --release-port <id>` flow that politely tells CoolTerm to disconnect via AppleScript / dbus / SIGTERM-with-prompt.  Bigger lift, OS-specific.
- (b) Just document the current behavior in `docs/contributing/working-with-agents.md` so users running bench sweeps know to close CoolTerm first.  Minimal lift.
- (c) Add a non-interactive port-conflict detector to the sweep harness that fast-fails with a clear "close CoolTerm and re-run" message before any deploys, instead of failing on the first port-conflict deploy.  Medium lift.

Recommend (b) immediately + (c) when scope allows.

### 10. `devices.yml` `circuitpy_drive_path` is fragile across boot orders

**Symptom.** macOS assigns CIRCUITPY drive names by mount order: first board → `/Volumes/CIRCUITPY`, second → `/Volumes/CIRCUITPY 1`.  `devices.yml` hard-codes the path at registration time, but a power-cycle / replug can swap which board comes up first → the file is wrong on paper.  The deploy stack auto-corrects via `_verify_drive_for_board` (UID-based), but the fragility is real.

**Affected.** Multi-CIRCUITPY-board hosts (any host with 2+ CP boards plugged in simultaneously).

**Fix shape.**  Three options:
- (a) Drop `circuitpy_drive_path` from `devices.yml` entirely; always resolve via UID at deploy time.  Backward-incompat but cleaner.  Existing `_verify_drive_for_board` does the work already.
- (b) Auto-update `devices.yml` whenever `_verify_drive_for_board` corrects a mismatch at deploy time.  Minimally disruptive but introduces side-effects on a config file.
- (c) Just document the fragility in `docs/contributing/device-testing.md` and let users `chumicro-workspace add-device` again if they hit it.

Recommend (a) — the path is already dead weight given UID auto-correct exists.  Workstream-template repo would need to drop the field too.

### 11. `chumicro-sockets` doesn't declare `chumicro-timing` in `dependencies` despite using it

**Symptom.** `libraries/sockets/pyproject.toml` has no `[project] dependencies = [...]` block at all, but the library's adapters use `chumicro_timing.ticks_ms` / `ticks_diff` etc. (per the workstream history of "lazy adapter selection pattern").  A user `pip install`-ing `chumicro-sockets` doesn't get `chumicro-timing` automatically.

**Repro.**
```bash
grep -A 5 "^dependencies" libraries/sockets/pyproject.toml
# (returns nothing)
grep -rn "chumicro_timing" libraries/sockets/src/
# (returns matches confirming runtime usage)
```

**Fix shape.** Add `dependencies = ["chumicro-timing"]` to `libraries/sockets/pyproject.toml` `[project]` section.  Also audit other library pyprojects for similar gaps — could be a wider issue.  Example-sweep tangent; not a sweep-blocking finding.

**Effort.** Trivial for sockets (one line).  Audit pass across all libraries' pyproject.toml ↔ src/ imports could surface more — likely 1-2 hours total.

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
