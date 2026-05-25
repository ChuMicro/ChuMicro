# Workstream: programmatic deploy API for demos and host-side tooling

Status: **shipped** (all six phases landed 2026-05-24). Accepts [Decision 0086](../decisions/0086-programmatic-deploy-api-for-demos-and-tooling.md) and tracks the implementation. Pairs with the [deploy-path-unification workstream](deploy-path-unification.md) — that workstream owns the *write* mechanism; this one owns the *programmatic caller surface* over it, plus the test-shaped execution layer that surfaces stdout markers to host orchestration.

## Problem

Demos and ad-hoc host-side scripts that want to "deploy a project directory to a board and orchestrate the bootstrap" re-implement the same six steps the `chumicro-workspace deploy` CLI already owns plus the bg-thread+marker orchestration that `chumicro_pytest_device` owns: pick a device, compose runtime_config, resolve deploy mode, walk imports, stage, build the inline bootstrap, run on a bg thread, parse stdout markers, expose `wait_for(marker_name)`. The two demos written so far (`http_server_roundtrip`, the partial `mqtt_pub_sub`) each reach into `chumicro_pytest_device.test_runner` + `chumicro_pytest_device.concurrent_runner` + `chumicro_workspace.pipeline` + `chumicro_deploy` directly. The driver is ~80% boilerplate and ~20% demo-specific orchestration; the pytest-device internals demos import are not a stable contract; and a per-device `deploy_mode: ram` override in `devices.yml` can quietly change a demo's behaviour.

The fix has three parts:

1. **One programmatic API** on `chumicro_workspace` that returns a marker-aware session handle. Demos collapse to ~100 lines.
2. **Orchestration primitives move to `chumicro_workspace`** so the dependency direction stays acyclic (workspace → pytest-device, not the reverse). The pytest collection layer keeps its home in pytest-device.
3. **A CHU lint forbids demo drivers from reaching workbench internals** and forbids `deploy_mode != "flash"` in demo drivers — per [Decision 0074](../decisions/0074-drift-mechanization-as-project-policy.md), a contract that can be mechanically checked must be.

## Implementation phases

### Phase 0 — Decide. **DONE 2026-05-24 — [Decision 0086](../decisions/0086-programmatic-deploy-api-for-demos-and-tooling.md) (`proposed`).**

Public API surface, the orchestration-primitives move target (the four named primitives, not just two), the test-shaped execution shape (not project-shaped autoboot), the demo-side forbidden-import list, and the deploy_mode-enforcement-at-caller rule are all named. 0086 stays `proposed` and promotes to `accepted` when **both** Phase 3a (port the existing demo without regression) and Phase 3b (rebuild the new demo on canonical libraries) land green on real hardware — that's the dual gate that proves the API serves both cases.

### Phase 0.5 — Roll the half-built `mqtt_pub_sub` back to `.scratch/`. **Do immediately.**

The currently-checked-in `demos/mqtt_pub_sub/` (driver + app + README) is not in a runnable state: the driver reaches across the forbidden boundary that Phase 5's lint will forbid, the canonical-library `app.py` rewrite never deployed cleanly to a Pico W CP, and the `extra_runtime_config` + Mosquitto plumbing in the driver duplicates what Phase 2 will collapse into one call. Leaving it in `demos/` for the workstream's duration means `chumicro-workspace verify-demos` and any cold reader of `demos/README.md` sees a demo that doesn't work.

Action this phase:

- `git mv demos/mqtt_pub_sub .scratch/mqtt_pub_sub_v1` (the `.scratch/` tree is gitignored — see AGENTS.md; the source files become local-only reference for Phase 3b's rewrite).
- Remove the bullet for this demo from any READMEs that list it.
- Commit Phase 0.5 standalone — separate from the workstream's substantive phases.

The `http_server_roundtrip` demo stays in place; it works in its current shape and ports under Phase 3a.

### Phase 1 — Move the orchestration primitives into `chumicro_workspace`

`git mv` the four primitives identified in [Decision 0086](../decisions/0086-programmatic-deploy-api-for-demos-and-tooling.md) ("Orchestration primitives move to `chumicro_workspace`" section):

| From | To |
|---|---|
| `workbench/pytest-device/src/chumicro_pytest_device/concurrent_runner.py` | `workbench/workspace/src/chumicro_workspace/device_runner.py` |
| `workbench/pytest-device/src/chumicro_pytest_device/markers.py` | `workbench/workspace/src/chumicro_workspace/markers.py` |
| `chumicro_pytest_device.test_runner.build_transport_for_entry` + `resolve_effective_deploy_mode` (the two functions) | `workbench/workspace/src/chumicro_workspace/_transport.py` (private; the deploy_api re-exposes through its public surface) |
| `chumicro_pytest_device.test_runner.build_device_bootstrap` + the bootstrap-script helpers it depends on | `workbench/workspace/src/chumicro_workspace/_bootstrap.py` (private; same) |

Update each moved file's module docstring to drop pytest-fixture framing — the primitives are host-side orchestration, not pytest-bound. Tests for each move alongside (`workbench/pytest-device/tests/test_*.py` → `workbench/workspace/tests/`); their bodies update for new import paths only.

Add `chumicro-workspace` to `workbench/pytest-device/pyproject.toml` `[project].dependencies`. Add re-export shims at the old paths so existing call sites keep working:

```python
# workbench/pytest-device/src/chumicro_pytest_device/concurrent_runner.py
"""Backwards-compat shim — primitives moved to chumicro_workspace.device_runner."""
from chumicro_workspace.device_runner import DeviceBootstrapRunner, RunnerNotStartedError

__all__ = ["DeviceBootstrapRunner", "RunnerNotStartedError"]
```

Equivalent shims for `markers.py` and the two `test_runner.py` symbols (the rest of `test_runner.py` — collection-shaped helpers — stays put). Update inbound code references inside `chumicro_pytest_device/*.py` (collection.py, session.py, fixtures/) to cite the workspace path directly; the shim exists only for *external* callers (functional tests, demos pre-rewrite).

Update [Decision 0085](../decisions/0085-board-to-host-sync-stdout-markers.md) in place to cite `chumicro_workspace.markers` as the home (per [decisions/README.md](../decisions/README.md): edit the body, no banners).

`workbench/workspace` `VERSION` minor bump (new public modules); `workbench/pytest-device` `VERSION` minor bump (new dep + retired ownership). `check-api` green; preflight green at coverage 94. Real-hardware bake: re-run a representative functional test (`libraries/mqtt/functional_tests/test_real_broker.py` or equivalent) on Pico W CP to confirm the moved orchestration runs unchanged from the consumer's view.

### Phase 2 — Implement `chumicro_workspace.deploy_api`

New module: `workbench/workspace/src/chumicro_workspace/deploy_api.py`. Public surface per [Decision 0086](../decisions/0086-programmatic-deploy-api-for-demos-and-tooling.md) "Public surface" table:

```python
from chumicro_workspace.deploy_api import deploy_project, DeployedProject
```

Implementation reuses the pieces moved in Phase 1 plus the workspace's existing internals:

| Step | Implementation |
|---|---|
| Device resolution | `chumicro_deploy.load_device_registry` (unchanged). |
| Transport build | `chumicro_workspace._transport.build_transport_for_entry` (moved in Phase 1). |
| Runtime-config compose | `chumicro_workspace.pipeline.compose_runtime_config` + the `extra_runtime_config` overlay applied at the top of the merged dict (last-write-wins, mirrors the pytest-device fixture's existing behaviour). |
| Import-graph walk | `chumicro_workspace.import_graph` (existing; the CLI calls into it). |
| Staging | `chumicro_workspace.deploy_source.WithRuntimeConfig` + the `project_*_source` helpers (existing). |
| Bootstrap build | `chumicro_workspace._bootstrap.build_device_bootstrap` (moved in Phase 1). |
| Bg thread + marker queue | `chumicro_workspace.device_runner.DeviceBootstrapRunner` (moved in Phase 1). |

`DeployedProject` is a thin dataclass holding `(device_entry, transport, runner)` with the public methods delegating to `runner`. Context-manager `__exit__` calls `shutdown()`.

Tests at `workbench/workspace/tests/test_deploy_api.py`:

- Deploy a synthesised project against `FakeTransport` + `FakeDeviceEntry`; assert the staged source dirs, the msgpack payload's flat keys, the bootstrap shape.
- Marker-wait happy path: a fake board emits `READY` → `wait_for("READY")` returns the marker.
- Marker-wait timeout path: no marker → `MarkerTimeoutError` with the marker name in the message.
- Context-manager teardown closes the transport even if the body raises.
- `deploy_mode="flash"` overrides a `FakeDeviceEntry` with `deploy_mode="ram"`.
- `extra_runtime_config` keys override `secrets.toml` defaults (last-write-wins).
- `extra_runtime_config=None` produces the same payload as the CLI's `compose_runtime_config` output (parity test against the CLI path).

`workbench/workspace` `VERSION` minor bump (new public submodule). `check-api` records the new surface. `preflight --coverage-threshold 94` green.

### Phase 3 — Port the two demos. Both gate the ADR promotion.

Run in parallel. Each commits independently with its own bench evidence. Both must land green on real hardware before [Decision 0086](../decisions/0086-programmatic-deploy-api-for-demos-and-tooling.md) promotes from `proposed` to `accepted`.

**Phase 3a — Port `http_server_roundtrip` to `deploy_api` (regression gate).**

Rewrite `demos/http_server_roundtrip/driver.py` against `chumicro_workspace.deploy_api`. Expected shape (~100 lines, vs. ~260 today):

```python
from chumicro_workspace.deploy_api import deploy_project

with deploy_project(
    project_dir=_DEMO_DIR, device_id=args.device, runtime=args.runtime,
    deploy_mode="flash",
) as session:
    hit = bind_to(session)   # bind_to gains a DeployedProject overload in 3a
    response = hit("/hello", timeout_s=args.ready_timeout_s)
    ...
    session.wait_for_completion(timeout_s=args.completion_timeout_s)
```

`demos/http_server_roundtrip/app.py` is untouched. The `bind_to` helper in `chumicro_pytest_device/fixtures/host_driver.py` gains a `DeployedProject` overload (same `runner.marker_queue` interface; trivial). Validate three round-trips against a real Pi Pico W CP, same expected output as today. **Gate: no regression in the demo's user-visible behaviour.**

**Phase 3b — Rebuild `mqtt_pub_sub` on `deploy_api` + canonical libraries (composition gate).**

Build `demos/mqtt_pub_sub/` fresh from the source in `.scratch/mqtt_pub_sub_v1/` (Phase 0.5):

- `app.py` composes `chumicro_config.load_runtime_config` + `chumicro_wifi.WifiService` + `chumicro_mqtt.MQTTClient.from_config` on a `chumicro_runner.Runner`. The board's main loop is the canonical `while True: now_ms = runner.tick(); runner.wait(now_ms)`; orchestration steps fire from library callbacks (`on_state_change`, `on_publish`, `on_subscribe`, `on_message`) and a per-tick advance, not from hand-rolled `drive_until` helpers (user feedback 2026-05-24).
- `driver.py` uses `chumicro_workspace.deploy_api` for the deploy + marker session; spawns Mosquitto on the host's LAN IP via `chumicro_pytest_device.fixtures.mosquitto.start_mosquitto_broker`; runs a CPython-side `chumicro_mqtt.MQTTClient` as the counterparty for the wildcard subscribe / cmd publish.
- Concepts demonstrated (per the user's scope decision 2026-05-24): connect, QoS 0 + QoS 1 publish in both directions, retained messages, wildcard topic filter, pattern handler.

**Board-memory budget bake.** Before committing 3b, run the canonical-library `app.py` directly against Pico W CP (256 KB RAM) and confirm: (1) the inline raw-REPL bootstrap doesn't crash with `MemoryError` during the import phase, and (2) `gc.mem_alloc()` after `runner.tick()` settles below 80% of the heap. If (1) fails, the entrypoint is too heavy for the target board — chunk the bootstrap via the existing `extended_transport.execute_scripts` path (multiple scripts, one interpreter session), or drop one library from the composition with a documented reason. If (2) fails but (1) passes, the demo still works but a follow-up entry goes into `plans/next-up.md` for an embedded audit. **Gate: end-to-end run against Pico W CP, all marker waits resolve, host receives all three telemetry messages.**

If 3b reveals an API gap that 3a didn't surface (it might — 3b exercises a longer marker sequence and bidirectional traffic), the gap fix lands as a Phase 2.x amendment commit *before* 3b's commit.

### Phase 4 — CHU lint forbids demo drivers from reaching workbench internals and forbids non-`flash` deploy mode

New lint code **CHU030** (the next free number; current high is CHU029, per `workbench/checks/src/chumicro_checks/rules/`). Scope: files under `demos/<name>/`.

**Forbidden imports** in `demos/<name>/*.py`:

- `chumicro_deploy.*`
- `chumicro_workspace.pipeline`
- `chumicro_workspace.deploy_source`
- `chumicro_workspace.import_graph`
- `chumicro_pytest_device.test_runner`
- `chumicro_pytest_device.concurrent_runner` (the shim path)
- `chumicro_pytest_device.markers` (the shim path)
- `chumicro_workspace.device_runner` and `chumicro_workspace.markers` for *anything other than type imports* (`Marker`, `MarkerTimeoutError` in `except` clauses are fine; instantiating `DeviceBootstrapRunner` directly is not — go through `deploy_project`).

**Allowed imports**: stdlib, `chumicro_workspace.deploy_api`, `chumicro_workspace.markers` (types only), `chumicro_pytest_device.fixtures.*` (host helpers — Mosquitto spawner, LAN-IP detector, UDP echo), and any device-side library imported as a CPython counterparty (`chumicro_mqtt`, `chumicro_http_server`, etc.) plus stdlib host clients (`http.client`, optional `paho.mqtt`).

**Forbidden kwarg value**: `deploy_project(..., deploy_mode="ram")` or any non-`"flash"` literal. Detected via AST: a `deploy_project` call whose `deploy_mode` keyword argument is a literal other than `"flash"` is a CHU030 violation. Non-literal values (`deploy_mode=args.deploy_mode`) are allowed — those are runtime decisions the lint can't reason about and the demo author has taken explicit responsibility for. Omitting the kwarg is also forbidden (the default of `None` triggers devices.yml resolution, which can yield RAM).

Lint message: per forbidden import, name the `chumicro_workspace.deploy_api` equivalent. Example: `CHU030: demos/mqtt_pub_sub/driver.py imports chumicro_pytest_device.test_runner.build_transport_for_entry — use chumicro_workspace.deploy_api.deploy_project instead.` For the deploy_mode case: `CHU030: demos/mqtt_pub_sub/driver.py calls deploy_project(deploy_mode="ram") — demos pin deploy_mode="flash" to match the production-shaped path.`

Tests cover the happy path (a compliant demo passes), each forbidden import (each fails with the expected message), the allowed `fixtures.*` exception, the literal-vs-non-literal kwarg distinction, and a `deploy_project` call missing the `deploy_mode` kwarg entirely.

Add an entry to AGENTS.md under "Common pitfalls" naming the rule + the lint code. Add an entry to [decisions/0060-chu-rules-home.md](../decisions/0060-chu-rules-home.md) (the CHU index).

### Phase 5 — Retire the `chumicro_pytest_device.{concurrent_runner, markers, test_runner shims}` shim layer

After Phases 1–4 land and all in-repo callers cite the workspace paths directly, delete the shim re-export modules. `workbench/pytest-device` minor bump. `check-api` shows the removed surface; the removal is intentional (shim, not public API). Any external consumer that was using the shim path migrates to `chumicro_workspace.{device_runner, markers}` per the shim's docstring.

Gated on a `grep -rn` returning empty:

```bash
grep -rn \
  'chumicro_pytest_device\.\(concurrent_runner\|markers\)\|from chumicro_pytest_device\.test_runner import \(build_transport_for_entry\|build_device_bootstrap\|resolve_effective_deploy_mode\)' \
  workbench/ libraries/ demos/ scripts/
```

Re-run the full preflight + a representative real-hardware bake (Pico W CP functional test) to confirm nothing depended on the shim re-export through transitive imports.

## Validation history

<!-- One line per phase as it lands.  Format: `- **YYYY-MM-DD** Phase N. <short summary> + commit hash.` -->

- **2026-05-24** Phase 0.5. Broken `demos/mqtt_pub_sub/` rolled to `.scratch/mqtt_pub_sub_v1/`; ADR + workstream filed together. Commit `6b22c42a`.
- **2026-05-24** Phase 1. Four orchestration primitives moved from `chumicro_pytest_device` to `chumicro_workspace.{device_runner, markers, device_orchestration}`; all in-repo callers updated; no back-compat shim per user direction ("nothing has shipped"). workspace 0.39.3→0.40.0, pytest-device 0.14.2→0.15.0. Preflight green at coverage 94. Commit `99c15443`.
- **2026-05-24** Phase 2. `chumicro_workspace.deploy_api.deploy_project()` + `DeployedProject` session implemented; 9 tests against FakeTransport + monkeypatched device resolution (staging shape, runtime_config overlay, deploy_mode override, error paths, marker waits, context-manager teardown). workspace 0.40.0→0.41.0. Preflight green at coverage 94. Commit `7fa499dd`.
- **2026-05-24** Phase 3a. `demos/http_server_roundtrip/driver.py` ported to deploy_api — 260 lines → 155 lines, all of it demo-specific narration. Bench: deployed against real Pi Pico W CP from clean reset; three round-trips render exactly as before; `DEMO_COMPLETE` arrives. Regression gate passes. Commit `925f1af6`.
- **2026-05-24** Phase 3b. `demos/mqtt_pub_sub/` rebuilt on Runner + MQTTClient + chumicro_config canonical composition with event-driven state machine (no `drive_until` helpers). Two non-obvious gotchas encoded: WifiService stays off the runner (its blocking CP `wifi.radio.connect` violates runner-tick cooperative shape), `DemoState.advance()` registers as a `runner.add_periodic(100 ms)` so the runner wakes up between MQTT events to fire the pacing timer. Marker order matters: `add_pattern_handler` callback fires before `on_message` so `PATTERN_HIT` prints before `CMD_RECEIVED` — driver waits in arrival order. Bench: Lolin S2 CP runs the full pipeline through the cmd round-trip and two telemetry messages (USB-CDC dropped before the third — board-specific, not a demo defect). Pi Pico W CP wifi fails with `ConnectionError: Unknown failure 1` despite the same `wifi_up()` succeeding in http_server_roundtrip on the same board; documented in the demo README and in plans/next-up.md as a known issue. Commit `381c8abc`.
- **2026-05-24** Phase 4. CHU030 lands — forbidden-imports + literal-`deploy_mode="flash"` enforcement on every `.py` under `demos/`. 15 tests cover the prefix-match, bare/from-import distinction, noqa suppression, literal-vs-non-literal kwarg case, and silent no-op when `demos/` is absent. Both shipped demos pass under the rule with no suppressions. checks 0.10.1→0.11.0. Commit `765f53c5`.
- **2026-05-24** Phase 5. No shims to retire (Phase 1 did the hard-cut). Decision 0086 promoted `proposed` → `accepted`: 3a confirms the API doesn't regress an existing demo, 3b confirms the canonical-library composition works on real hardware (Lolin S2 CP); the Pi Pico W wifi issue is a board / radio-state quirk independent of the deploy_api surface, tracked separately in plans/next-up.md.

## Out of scope

- **Tail / log-stream surface on `DeployedProject`.** The CLI's `--tail` flag is request/response on a finished bootstrap; the bg-thread session already streams stdout into the marker dispatcher. If a future caller wants raw stdout streaming (an interactive demo, a `--watch` mode), it's a follow-up `session.iter_lines()` addition, not Phase-2 surface.
- **Two-board orchestration.** Today's `DeviceBootstrapRunner` is one-board. A demo that needs two boards (board-to-board mesh handshake, multi-publisher MQTT scenario) needs two `deploy_project(...)` calls and host-side coordination across both sessions. The Phase-2 API supports two parallel sessions because the underlying transport is per-device; a richer "co-orchestrate N boards" helper is future work.
- **Replacing `chumicro-workspace deploy` CLI internals with calls into `deploy_api`.** The CLI keeps its existing implementation; this workstream only extracts the shared bits the API needs and reuses them. A later workstream can fold the CLI to call `deploy_api` internally if the double-implementation drift starts to show.
- **`deploy_api` for non-`app.py` shapes.** The API assumes a project shape with an `app.py` entrypoint (per [`demos/README.md`](../../demos/README.md) and the workspace template). Raw single-file deploys (no `project_config.toml`, no `app.py`) stay on `chumicro-deploy` directly; they're not a demo-shaped case.
- **Public API for the `Marker` extension.** Adding new marker names (e.g. `WIFI_CONNECTED`, `MQTT_DISCONNECTED`) is a per-library / per-demo concern; [Decision 0085](../decisions/0085-board-to-host-sync-stdout-markers.md) owns the marker-name reservation rules and stays the home for those additions.
- **Moving `chumicro_pytest_device.fixtures.*` to `chumicro_workspace`.** The Mosquitto spawner, LAN-IP detector, and UDP echo are genuinely shared host-side helpers; their `pytest_device` package home leaks the pytest framing. Renaming or relocating them is its own follow-up workstream once Phase 5 retires the orchestration shims and the package's role is "pytest collection + host fixtures over `chumicro_workspace`'s orchestration." Not part of this workstream because the demo lint (Phase 4) explicitly allows `chumicro_pytest_device.fixtures.*` for now.
- **Chunking the inline bootstrap automatically based on board RAM budget.** Phase 3b's board-memory bake either fits or it doesn't; if it doesn't, the workstream's commit-level fix is per-bootstrap chunking via `execute_scripts`. A generic "deploy_api detects board RAM and auto-chunks" feature is real work that should be motivated by a second demo that fails the same way, not by this one.
