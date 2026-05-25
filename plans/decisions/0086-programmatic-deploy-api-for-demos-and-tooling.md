# Decision 0086: Programmatic deploy API for demos and host-side tooling

Status: `accepted`
Date: `2026-05-24`
Summary: `chumicro_workspace.deploy_api.deploy_project()` is the one programmatic deploy+marker-orchestration entry point; runner/marker primitives move to `chumicro_workspace`.
Related: Decision [0077](0077-one-device-staging-path.md) (one device staging path — this ADR adds the programmatic caller without adding a second staging path), Decision [0083](0083-functional-test-endpoint-taxonomy.md) (Category 1 host-driver-as-client shape that demos extend), Decision [0085](0085-board-to-host-sync-stdout-markers.md) (stdout-marker protocol the orchestration primitives implement), Decision [0082](0082-test-harness-as-infrastructure-library.md) (`support/` dissolution — new shared primitives land in `libraries/` or `workbench/`, not a new tree).

## Context

`demos/<name>/driver.py` exists to show a library working end-to-end against real hardware in one command (see [`demos/README.md`](../../demos/README.md)). The two demos written so far (`http_server_roundtrip`, the partial `mqtt_pub_sub`) each re-implement the same orchestration plumbing the `chumicro-workspace deploy` CLI already owns:

- Pick a device from `devices.yml`.
- Compose `secrets.toml` + per-project overrides + ad-hoc extras into a `/runtime_config.msgpack` payload.
- Resolve the deploy mode (the per-device + global resolution rules from [Decision 0068](0068-unified-deploy-mode-resolution.md)).
- Walk the entrypoint's import graph against `libraries/`.
- Stage the source tree + the msgpack payload through the device transport.
- Run the bootstrap on a background thread, parse stdout markers, expose a `wait_for(marker_name)` primitive to the orchestrator.

The CLI owns the first five steps; `chumicro_pytest_device.concurrent_runner.DeviceBootstrapRunner` + `chumicro_pytest_device.markers` own the sixth. Demos reach across both by importing `chumicro_pytest_device.test_runner.build_transport_for_entry` / `resolve_library_source_dirs` / `build_device_bootstrap` and instantiating `DeviceBootstrapRunner` directly. The driver is ~80% boilerplate and ~20% demo-specific orchestration.

This is the same drift class [Decision 0077](0077-one-device-staging-path.md) and the [deploy-path-unification workstream](../workstreams/deploy-path-unification.md) call out: divergent code paths for one logical operation, each introduced for a context, then drifting apart. Demos doing this is a second instance, with a second exposure surface (the pytest-device internals demos import are not a stable contract).

A secondary concern: the demo driver currently can — and the failing `mqtt_pub_sub` run did — accidentally inherit a per-device `deploy_mode: ram` override from `devices.yml`. Demos exist to show "this is how your project will run"; the production-shaped path is flash. The current driver respects the device override; the right shape is to enforce.

## Decision

**`chumicro_workspace.deploy_api.deploy_project(project_dir, ...)` is the one programmatic entry point for "deploy a project-shaped directory to a board and orchestrate it." Every host-side caller that wants a real board running real code — demos, ad-hoc scripts, future contributors writing one-off harnesses — goes through it. The orchestration primitives (`DeviceBootstrapRunner`, `MarkerQueue`, `parse_marker`, `Marker`, `MarkerTimeoutError`) move from `chumicro_pytest_device` into `chumicro_workspace` so the dependency direction stays acyclic.**

### Public surface

```python
from pathlib import Path
from chumicro_workspace.deploy_api import deploy_project, DeployedProject

with deploy_project(
    project_dir=Path("demos/mqtt_pub_sub"),
    device_id="pi-pico-w-circuitpython-board",     # or runtime= filter
    deploy_mode="flash",                            # demos pass this; tools may omit
    extra_runtime_config={                          # merged on top of secrets.toml
        "mqtt.broker.host": "10.0.0.5",
        "mqtt.broker.port": 1883,
    },
) as session:
    marker = session.wait_for("MQTT_CONNECTED", timeout_s=60)
    print(f"board up: {marker.values}")
    output = session.wait_for_completion(timeout_s=90)
```

`deploy_project` signature (keyword-only after `project_dir`):

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `project_dir` | `Path` | — | Directory with an `app.py` (and optional `project_config.toml`). |
| `device_id` | `str \| None` | `None` | Pick a specific device from `devices.yml`. |
| `runtime` | `"circuitpython" \| "micropython" \| None` | `None` | When `device_id is None`, pick the first matching device. |
| `deploy_mode` | `"flash" \| "ram" \| None` | `None` | `None` = devices.yml resolution (per [Decision 0068](0068-unified-deploy-mode-resolution.md)); explicit value overrides. |
| `extra_runtime_config` | `dict[str, object] \| None` | `None` | Flat-key keys merged on top of `secrets.toml` + `project_config.toml`. Last-write-wins. |
| `boot_shim` | `bool` | `True` | Synthesise `/code.py` or `/main.py` calling `app.run()` when `app.py` exposes `run()`; mirrors `chumicro-workspace deploy --boot-shim` auto-detection. |
| `import_graph` | `bool` | `True` | Walk `app.py`'s import graph against `libraries/` instead of shipping the full project directory. |

`DeployedProject` (the session handle):

| Method / property | Returns | Notes |
|---|---|---|
| `wait_for(marker_name, *, timeout_s)` | `Marker` | Blocks until the named marker arrives on board stdout; raises `MarkerTimeoutError` on timeout. |
| `wait_for_completion(*, timeout_s)` | `str` | Joins the bootstrap thread; returns full captured stdout. Re-raises any transport error. |
| `captured_stdout` | `str \| None` | Best-effort snapshot of stdout so far; `None` until the bootstrap finishes. |
| `device_entry` | `DeviceEntry` | The resolved device record, for callers that need its address / runtime / id. |
| `shutdown(*, timeout_s=5.0)` | `None` | Closes the transport, reaps the bg thread. Idempotent. |
| `__enter__` / `__exit__` | — | Context-manager calls `shutdown` on exit. |

### Demos pin `deploy_mode="flash"`

Demos exist to show the production-shaped path. The driver passes `deploy_mode="flash"` explicitly so a developer with a per-device RAM override in their `devices.yml` (legitimate for unit-test work) still sees the demo run the way a project would. This is a *caller-level* convention, not enforced by `deploy_project`: tooling that has a legitimate need for RAM mode (the test harness's per-suite opt-in) keeps the option.

### Execution shape: test-shaped raw-REPL bootstrap, not project-shaped autoboot

There are two ways to "run code on a board" in the workspace today:

- **Project-shaped autoboot** — what `chumicro-workspace deploy` does. Stage files, soft-reset the board, `/code.py` (CP) or `/main.py` (MP) runs from the substrate's own boot path. The host watches serial passively via the optional `--tail`. The board owns its lifecycle; the host is a witness.
- **Test-shaped raw-REPL bootstrap** — what `DeviceBootstrapRunner` does. Stage files, build an inline raw-REPL bootstrap that imports the entrypoint, execute via `transport.execute(bootstrap, on_line=...)` to stream stdout into a host-side callback. The host drives the board's lifecycle; the bootstrap returns when the entrypoint exits.

`deploy_project` exposes the **test-shaped** path. Demos need `on_line` streaming for marker waits, and they need the host to know when the board's bootstrap finishes (for `wait_for_completion` and clean shutdown). The autoboot path provides neither — `--tail` is a passive read with no completion signal and no in-process callback. The deploy_api shares the *staging* mechanism with the CLI (per [Decision 0077](0077-one-device-staging-path.md), there is one staging path; this ADR does not introduce a second), but the *execution* layer is test-shaped.

Consequence for board memory: the test-shaped bootstrap inlines the entrypoint + any prelude through the raw REPL via `compile()` + `exec()`. On a 256 KB-class board (Pi Pico W CP, the canonical minimum), an entrypoint composing `chumicro_runner.Runner` + `chumicro_wifi.WifiService` + `chumicro_mqtt.MQTTClient` is at risk of exhausting heap during the inline import phase — `deploy_project` does not change this budget. A demo whose entrypoint exceeds the budget is a defect in the entrypoint (too heavy for the target board), not a deploy_api shortcoming. The implementation phases include a board-side bake of a worked canonical composition on Pico W CP precisely to surface this; a follow-up may chunk the bootstrap (the existing `extended_transport.execute_scripts` path) to stay under the budget.

### Orchestration primitives move to `chumicro_workspace`

Today, four pieces of host-side device orchestration live in `chumicro_pytest_device`:

- `chumicro_pytest_device.concurrent_runner.DeviceBootstrapRunner` — bg-thread bootstrap runner with on_line dispatch.
- `chumicro_pytest_device.markers.{MarkerQueue, parse_marker, Marker, MarkerTimeoutError}` — marker syntax + thread-safe queue.
- `chumicro_pytest_device.test_runner.build_transport_for_entry` — wraps `chumicro_deploy.Device.create_transport` with deploy-mode resolution.
- `chumicro_pytest_device.test_runner.build_device_bootstrap` — composes an inline raw-REPL bootstrap script that imports the entrypoint and surfaces its stdout.

None of these are pytest-specific. Pytest-device uses them through its collection layer; demos and other programmatic callers want them through the deploy_api. They move to `chumicro_workspace`:

- `chumicro_workspace.device_runner` — `DeviceBootstrapRunner` + `RunnerNotStartedError`.
- `chumicro_workspace.markers` — `MarkerQueue`, `parse_marker`, `Marker`, `MarkerTimeoutError`, the reserved-names list, the marker syntax docstring.
- `chumicro_workspace.deploy_api._transport` (private) — `build_transport_for_entry` (moved + renamed; re-exposed via the public `deploy_project` signature, no need for direct callers).
- `chumicro_workspace.deploy_api._bootstrap` (private) — `build_device_bootstrap` (moved; same).

What stays in `chumicro_pytest_device`: the pytest collection layer (`collection.py`, `session.py`, `plugin.py`), the fixture surface under `fixtures/`, the runtime_config injection seam, and the result-parser layer that reads `PASS`/`FAIL`/`SKIP`/`SUMMARY`/`HEAP` off the marker stream. These genuinely *are* pytest-shaped.

`chumicro_pytest_device` re-exports the four moved names from their current paths (`from chumicro_pytest_device.concurrent_runner import DeviceBootstrapRunner` keeps working) as thin shims, and gains `chumicro-workspace` as a dependency. The shims exist so existing call sites (functional tests, pytest-device's own collection) keep working without a same-commit cascade rewrite; they retire once all callers cite the workspace paths.

Dependency direction after the move: `chumicro_deploy → chumicro_workspace → chumicro_pytest_device`. Today's edge `chumicro_pytest_device → chumicro_deploy` becomes `chumicro_pytest_device → chumicro_workspace → chumicro_deploy` — same DAG, one node deeper, no cycle.

### Demos may not reach across the workspace boundary

Once the API ships, `demos/<name>/driver.py` may import only from:

- The Python standard library.
- `chumicro_workspace.deploy_api` (the public surface above).
- `chumicro_workspace.markers` (for `Marker` / `MarkerTimeoutError` type imports in `except` clauses).
- Host-side counterparty libraries (e.g. `chumicro_mqtt` on CPython, stdlib `http.client`, `paho.mqtt` if a demo legitimately needs a different client implementation).
- `chumicro_pytest_device.fixtures.*` for host-side test utilities that are explicitly demo-relevant (the Mosquitto broker spawner, the LAN-IP detector); these are not "deploy plumbing", they're host helpers.

Forbidden: direct imports of `chumicro_deploy`, `chumicro_workspace.pipeline`, `chumicro_workspace.deploy_source`, `chumicro_pytest_device.test_runner`, `chumicro_pytest_device.concurrent_runner`. A CHU lint enforces this; the lint failure messages name the deploy_api equivalent.

The existing demo (`http_server_roundtrip`) reaches across the forbidden boundary today. It ports to the new API in the same workstream that lands the API; the lint goes from advisory to hard at that point.

## Rejected

- **Add the orchestration primitives to a new `workbench/device_runner/` package.** Cleaner separation, but adds a fourth workbench package whose only consumers would be `chumicro_workspace` and `chumicro_pytest_device`. The split is real overhead (a new pyproject.toml, a new test suite, a new check-api boundary) for a primitive set that genuinely belongs *inside* the workspace's orchestration responsibility. Promote later if a third independent consumer emerges.
- **Keep the orchestration primitives in `chumicro_pytest_device` and have `chumicro_workspace.deploy_api` depend on it.** A workspace runtime depending on a pytest plugin is semantically backwards: the workspace is the substrate, the pytest plugin is the consumer. The name `chumicro_pytest_device` also lies about what a demo driver pulls in.
- **Promote the primitives to `libraries/` as an infrastructure library (per [Decision 0082](0082-test-harness-as-infrastructure-library.md)).** The primitives are CPython-only (background threads, `queue.Queue`, subprocess transports). `libraries/` is the home for cross-runtime packages; CPython-only host orchestration is workbench-shaped, not library-shaped. The infrastructure-library flag is for *device-side* packages that aren't user-facing (the test harness), not for host orchestration.
- **Expose a `chumicro-workspace deploy --wait-for MARKER_NAME [...]` CLI flag instead of a programmatic API.** A demo needs a *sequence* of waits + host-side actions (publish a counterparty MQTT command, fire an HTTP request, observe a host receipt) interleaved between board markers. A CLI flag scales to one marker; the sequence shape needs Python.
- **Make `deploy_project` accept a `pytest.Config` or pytest-device session object for the runtime_config integration.** Couples demos to pytest. The extra-config dict is enough — it's the same data the pytest fixture today passes through `set_runtime_config(...)`, just expressed at the deploy_api boundary instead of through a pytest fixture.
- **Enforce `deploy_mode="flash"` inside `deploy_project` itself, not at the caller.** The deploy_api is also the right entry for ad-hoc programmatic tooling that may legitimately want RAM mode (a fast iteration loop on a developer's workbench). Demos are the audience that needs flash-enforcement; the rule belongs at the demo layer, not the substrate. The CHU lint enforces flash at the demo layer.

## Consequences

- **Demos shrink.** `http_server_roundtrip/driver.py` (~260 lines) and `mqtt_pub_sub/driver.py` (~470 lines pre-rewrite) collapse to ~80–120 lines each — almost all of it demo-specific orchestration (host MQTT client, host HTTP request, marker-sequenced narration). The deploy plumbing drops out.
- **Failure surface shrinks.** A demo that fails today could fail in `build_transport_for_entry`, `resolve_library_source_dirs`, `build_device_bootstrap`, `compose_runtime_config`, `start_mosquitto_broker`, or its own logic — six surfaces. After the API, the failure is either inside `deploy_project` (one place to instrument + fix) or inside the demo's own counterparty logic.
- **`chumicro_workspace` gains a runtime contract.** The `deploy_project` signature + `DeployedProject` method set become public API. The package's `check-api` gate covers them; breaking changes require a major bump (semver). This is new public surface for what is today an internal CLI tool.
- **`chumicro_pytest_device` retires the orchestration primitives in place over the workstream phases.** The shim layer keeps old imports working until callers update; the package's role becomes "pytest collection + fixtures over `chumicro_workspace`'s orchestration." Decision [0085](0085-board-to-host-sync-stdout-markers.md)'s `chumicro_pytest_device.markers` reference edits in place to `chumicro_workspace.markers` once the move lands.
- **A CHU lint forbids demo drivers from importing the workbench internals named in the "Demos may not reach across" section above.** Per [Decision 0074](0074-drift-mechanization-as-project-policy.md), a contract that can be mechanically checked must be. The lint message names the `chumicro_workspace.deploy_api` equivalent of each forbidden import.
- **AGENTS.md gets a small addition** under "Common pitfalls" or a near-equivalent section: a demo's driver script always uses `chumicro_workspace.deploy_api`, never reaches into `chumicro_pytest_device` or `chumicro_deploy` directly, and always pins `deploy_mode="flash"`.
- **`demos/README.md` is rewritten** to show the new driver shape as the worked example, with the deploy_api signature inline.
- **The deploy-path-unification workstream** ([plans/workstreams/deploy-path-unification.md](../workstreams/deploy-path-unification.md)) gains the deploy_api as a consumer of the same one-staging-path the workstream's Phase 2 converges on. The two workstreams compose: deploy-path-unification owns the *write* mechanism; this ADR's workstream owns the *programmatic caller surface* over it.
