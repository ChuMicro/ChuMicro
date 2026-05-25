# Handoff 2026-05-24 — `demos/mqtt_pub_sub` wifi failure on Pi Pico W

## What this session was about

Session goal: build a second demo (`demos/mqtt_pub_sub/`) using `start_mosquitto_broker` + `chumicro_mqtt`, then push it (and the underlying API work it surfaced) end-to-end. The work expanded into a full six-phase workstream once we hit that the current demo pattern duplicates ~80% of `chumicro-workspace deploy`'s internals — see [`plans/decisions/0086-programmatic-deploy-api-for-demos-and-tooling.md`](../decisions/0086-programmatic-deploy-api-for-demos-and-tooling.md) and [`plans/workstreams/programmatic-deploy-api.md`](../workstreams/programmatic-deploy-api.md).

All six phases shipped (commits `6b22c42a`, `99c15443`, `7fa499dd`, `925f1af6`, `381c8abc`, `765f53c5`, `3d7a262d`, `6efa1e94`). The one unsolved item: **`demos/mqtt_pub_sub` fails on Pi Pico W CP with `ConnectionError: Unknown failure 1` at wifi connect**, despite the same `wifi_up()` succeeding in `demos/http_server_roundtrip` against the same board / AP / credentials. The demo works end-to-end on Lolin S2 CP (with eventual USB-CDC dropout that's board-specific, not a demo defect).

## What's in flight

Nothing — working tree clean (modulo `.idea/chumicro.iml` PyCharm-driven drift that's not part of this work). Last commit `6efa1e94` is pushed.

## What got done

Eight commits shipped on `main` this session, all green at coverage 94:

| Commit | Phase | Summary |
|---|---|---|
| `6b22c42a` | 0 + 0.5 | ADR 0086 + workstream filed; broken `demos/mqtt_pub_sub/` rolled to `.scratch/mqtt_pub_sub_v1/`. |
| `99c15443` | 1 | `git mv` four orchestration primitives from `chumicro_pytest_device` to `chumicro_workspace.{device_runner, markers, device_orchestration}`. Hard cut, no shim per user direction. workspace 0.39.3 → 0.40.0, pytest-device 0.14.2 → 0.15.0. |
| `7fa499dd` | 2 | `chumicro_workspace.deploy_api.deploy_project()` + `DeployedProject` session class implemented. 9 tests against `FakeTransport`. workspace 0.40.0 → 0.41.0. |
| `925f1af6` | 3a | `demos/http_server_roundtrip/driver.py` ported to deploy_api — 260 lines → 155 lines. Validated on Pi Pico W CP, three round-trips render exactly as before. |
| `381c8abc` | 3b | `demos/mqtt_pub_sub/` rebuilt on Runner + MQTTClient + chumicro_config canonical libs with event-driven state machine. Validated on Lolin S2 CP. |
| `765f53c5` | 4 | CHU030 lint — forbids deploy plumbing imports in `demos/`, requires literal `deploy_mode="flash"`. 15 tests. checks 0.10.1 → 0.11.0. |
| `3d7a262d` | 5 | Decision 0086 promoted `proposed` → `accepted`. Workstream marked `shipped` with full Validation history. |
| `6efa1e94` | post-5 | Defensive `wifi.radio.stop_station()` precheck added to mqtt demo's `app.py`. Did NOT fix the Pi Pico W issue; kept for other boards. |

`http_server_roundtrip` demo re-validated end-to-end on Pi Pico W CP after all changes (`.scratch/http_demo_final.log`).

## What was learned

Most durable lessons are already in commit message bodies + the workstream's Validation history + the demo READMEs. The two that are most likely to bite again:

- **`runner.wait` sleeps until the next deadline source** — if you build a demo on top of `Runner` with MQTT registered, MQTT's keepalive (~30s) is the only deadline the runner knows. Your demo's own pacing timer (a `next_telemetry_due_ms` field, say) is invisible. The fix is to register a `runner.add_periodic(advance_fn, period_ms=100)` so the runner wakes up between MQTT events. Encoded in `demos/mqtt_pub_sub/app.py` with a comment explaining why.

- **`add_pattern_handler` callbacks fire BEFORE `on_message`** — the MQTT client dispatches in that order. So a board printing `PATTERN_HIT` from the pattern handler and `CMD_RECEIVED` from `on_message` will surface them in that order on stdout. A host driver waiting in the wrong order will have the marker queue drop the first-arrived marker (queue's documented behavior: non-matching markers during a `wait_for(X)` are dropped). Encoded in `demos/mqtt_pub_sub/driver.py` with a comment.

## Riskiest assumption

[VERIFIED: bench 2026-05-24 .scratch/http_demo_final.log] `wifi_up()` works on Pi Pico W CP against the configured AP — `http_server_roundtrip` connected and completed three round-trips. Resume confidence: high.

[VERIFIED: bench .scratch/mqtt_diag_picow_v4.log] `wifi_up()` fails on Pi Pico W CP from the *mqtt demo's* `app.py` with `ConnectionError: Unknown failure 1` immediately — not a timeout, the underlying `wifi.radio.connect` returns the error. **The whole hypothesis-tree to investigate hangs on: what is the mqtt demo doing that the http demo isn't, that puts the radio into a "Unknown failure 1"-returning state.**

If the next session finds `wifi_up` works fine when run from a stripped mqtt-demo `app.py` (just `wifi_up` + a print), the problem is the import graph; if it still fails, the problem is environmental (wifi router state, board state across the long bench session, etc.) and the demo's code is fine.

## To re-research / verify next session

Pick up at `demos/mqtt_pub_sub/app.py` with the Pi Pico W still as the target.

**Cheapest first experiment** [HYPOTHESIS: cheapest test = strip imports]: create a `.scratch/mqtt_min.py` with *just* the mqtt demo's imports + `wifi_up` + a single `print("WIFI_OK")` — no `Runner`, no `MQTTClient`, no `DemoState`. Run via `.scratch/mqtt_diag.py` (which has the per-line on_line tap and is already wired to Pico W). If that fails, the issue is an import side effect; if it succeeds, the issue is something else in the demo body.

**Second experiment** [HYPOTHESIS: deploy ordering]: deploy the mqtt demo with `chumicro-workspace deploy` (not `deploy_api`) — that uses autoboot, not the test-shaped raw-REPL bootstrap. If wifi succeeds there but fails through deploy_api, the bootstrap-exec path itself is doing something to wifi state. The mqtt demo isn't a workspace project right now; you'd have to wrap it as `projects/mqtt_pub_sub_test/` to use the CLI.

**Third experiment** [HYPOTHESIS: import side effect on wifi.radio]: grep `chumicro_mqtt`, `chumicro_runner`, `chumicro_config` for any `import wifi` or `wifi.radio` access at module / import time. Should be none (the sockets factory does it lazily), but worth confirming directly rather than reasoning about it.

**Fourth experiment** [HYPOTHESIS: physical replug fixes it]: power-cycle the Pi Pico W via unplug/replug (not `reset-board --yes`, which only soft-wipes). If the demo then works once and fails on the second run, the radio state is sticky across the soft-reset path; `wifi.radio.stop_station()` evidently isn't sufficient to clear it.

## Dead ends

- **`wifi.radio.stop_station()` precheck before `wifi_up()`.** Added in commit `6efa1e94`. Did not change the failure mode on Pi Pico W. Kept defensive for other CP boards.
- **Retry with 5 / 8 / 10 second settles** between `reset-board` and the deploy. Same failure every time. Not transient.
- **Switching device to Lolin S2.** Works (mostly — eventual USB-CDC dropout) but doesn't tell us anything about the Pi Pico W path. Lolin S2 is also currently disconnected (USB-CDC dropped during a bench run and didn't reauto-enumerate; needs physical replug).
- **Looking at the captured board stdout via `wait_for_completion(timeout_s=30.0)`** in the driver's `except` branch. With wifi hung mid-`wifi_up`, the bootstrap doesn't return in 30 s, so `wait_for_completion` itself times out and `session.captured_stdout` returns `None`. Workable only if you bump the fallback to ~120s (board's overall deadline) or use `.scratch/mqtt_diag.py` which has the per-line `on_line` tap.

## How to rebuild context fast

- **Run state**: `git --no-pager log --oneline -10` shows the eight commits this session shipped.
- **Workstream prose**: `plans/workstreams/programmatic-deploy-api.md` (`Status: shipped`). The Validation history at the bottom lists every commit + the gates it satisfied; the Phases block describes the design.
- **API design**: `plans/decisions/0086-programmatic-deploy-api-for-demos-and-tooling.md` (`Status: accepted`).
- **Working demo (Pi Pico W)**: `demos/http_server_roundtrip/driver.py`. Compare to `demos/mqtt_pub_sub/driver.py` — both go through `deploy_project()`.
- **Failing demo (Pi Pico W)**: `demos/mqtt_pub_sub/app.py` (`wifi_up` on line ~57 after the `stop_station` precheck).
- **Per-line tap diag harness**: `.scratch/mqtt_diag.py` — monkey-patches `DeviceBootstrapRunner._run` to print every captured line + the bg-thread exception. Currently wired to `pi-pico-w-circuitpython-board`. Run with `.venv/bin/chumicro-workspace reset-board --device pi-pico-w-circuitpython-board --yes && .venv/bin/python .scratch/mqtt_diag.py`.
- **Captured failure**: `.scratch/mqtt_diag_picow_v4.log` (Pi Pico W `Unknown failure 1`), `.scratch/mqtt_demo_lolin_v3.log` (Lolin S2 working mostly), `.scratch/http_demo_final.log` (Pi Pico W http demo green).

## Gotchas

- **Hardware state is point-in-time**: as of write, Pi Pico W CP is enumerated at `/dev/cu.usbmodem112301`; Lolin S2 CP was at `/dev/cu.usbmodem84722E7490C31` but is currently disconnected (USB-CDC drop during bench) — **needs physical replug to come back**. Pi Pico W MP + Lolin S2 MP enumerate but weren't exercised this session. Re-probe with `.venv/bin/chumicro-workspace devices` on resume.

- **`secrets.toml` at repo root must contain valid `wifi.ssid` + `wifi.password`** — present at session end, validated by http demo working.

- **`mosquitto` on PATH at `/opt/homebrew/sbin/mosquitto`** — verified, mqtt demo successfully spawns brokers at session end.

- **The driver's `_await_marker_while_driving_host` poll loop is necessary, not optional** — without it, `wait_for(marker_name)` blocks the main thread and the host MQTT client's bg I/O stalls, so the board's QoS 1 publishes pile up unrecveived. Encoded inline; don't refactor it back into a plain `wait_for`.

- **`load_runtime_config()` returns a `RuntimeConfig` object** (not a `dict`). `chumicro_workspace.compose_runtime_config()` returns a flat `dict`. The pytest-device fixture path uses the dict; the on-device app uses the RuntimeConfig. Both support `.get(key, default)` so most code reads identically, but `for key in config` works on the dict and not (currently) on `RuntimeConfig`. Not a problem in current code; flag for the future if someone writes iteration over keys.

- **No workstream-prose-vs-code drift uncovered.** The workstream's Validation history was written as each phase shipped, so it's accurate by construction.
