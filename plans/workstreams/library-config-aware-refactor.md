# Workstream: library `from_config` factories — config-aware constructors across the six networking libs

Status: **open — Phase 0 (manifests) shipped; Phase 1 (validation hook) and per-library refactor still to do.**

The libraries `mqtt`, `requests`, `http_server`, `ntp`, `websockets`, and `wifi` were written before the runtime-config strategy ([Decision 0035](../decisions/0035-runtime-config-structure.md), [Decision 0057](../decisions/0057-two-file-config.md), [`config-shape-beginner-ergonomics`](archive/config-shape-beginner-ergonomics.md)).  Today only `chumicro_wifi.WifiConfig.from_config` exists — `WifiService(WifiConfig.from_config(config))` reads `wifi.ssid` / `wifi.password` straight off the deployed `runtime_config.msgpack`.

The other five libraries don't import `chumicro_config` at all in their `src/`.  They take their tunables as constructor args; their tests + examples read keys directly off the flat config dict and pass them in by hand.  The forward shape is to grow `<Lib>Client.from_config()` factories on each library so a beginner can write::

    mqtt = MQTTClient.from_config(config, socket=...)

instead of::

    mqtt = MQTTClient(
        socket=...,
        client_id=config["mqtt.client_id"],
        keep_alive_seconds=config["mqtt.keep_alive_seconds"],
        username=config.get("mqtt.username"),
        password=config.get("mqtt.password"),
    )

Manifests ship first ([Phase 0](#phase-0--declare-manifests-shipped)) so deploy-time validation, tooling discoverability, and the future `from_config` factories all share one source of truth.  The actual factory code follows library by library.

## Premise

Two facts drove this workstream:

1. **`chumicro-workspace`'s `validate_runtime_config` is library-shape**: it walks the `[tool.chumicro.config]` blocks across libraries in the deploy graph, unions them, and verifies the user's merged config dict satisfies the union.  No manifest = no validation.  Six of seven networking libs had no manifest; `validate` was a near-no-op for any project that didn't use `chumicro-wifi`.
2. **`chumicro-pytest-device` doesn't validate at all today**.  Mono-repo functional tests stage `runtime_config.msgpack` blindly; if the user's `secrets.toml` doesn't have `mqtt.broker.host`, the test boots and crashes on `MissingConfigKey` instead of skipping with a clear precheck error.

The user-facing failure mode: a contributor adds a key to a functional test or example, forgets to populate `secrets.toml`, and gets a cryptic boot crash on a board instead of "you forgot key X."

The unification ([`scripts-workbench-config-unification`](archive/scripts-workbench-config-unification.md), [`config-shape-beginner-ergonomics`](archive/config-shape-beginner-ergonomics.md)) shipped the *plumbing* — flat-key wire format, `compose_runtime_config`, `set_runtime_config`, `validate_runtime_config`.  This workstream lights up the *consumers* on every networking library.

## Scope (sequenced)

### Phase 0 — declare manifests (shipped)

Five libraries (`mqtt`, `requests`, `http_server`, `ntp`, `websockets`) gained `[tool.chumicro.config]` blocks in their `pyproject.toml`.  All keys declared as `optional` — none of these libraries' `src/` code reads runtime config today, so calling anything required would lie about what the library actually demands.  The manifests document the **forward-looking** library config surface that the Phase 2 `from_config` factories will consume.

`sockets` was deliberately **not** given a manifest.  `chumicro-sockets` is a low-level construction kit — every consumer passes explicit host/port to `tcp_client_socket(host, port)` etc.  There are no inherent library-level defaults to read from `runtime_config.msgpack`.  The functional-test reads of `sockets.echo.host` / `sockets.echo.port` are **test infrastructure**, not library config — those belong in Phase 1's per-conftest required-keys mechanism, not in the library manifest.

`wifi` already had its manifest from before; left untouched.

### Phase 1 — `chumicro-pytest-device` validation hook

Today `chumicro_pytest_device.runtime_config.set_runtime_config(config, payload)` stages bytes blindly.  Add a validation step that runs before `transport.stage`:

1. The conftest passes `set_runtime_config(config, payload, required_keys=("mqtt.broker.host", "mqtt.broker.port"))`.
2. The plugin checks every required key is present in the payload.
3. On miss: `pytest.skip(f"functional test requires runtime-config keys: {missing}")` — clear precheck error, no on-device crash.

Why per-conftest required-keys instead of leaning on the library manifest: **the library doesn't require any of these keys** (its `src/` reads nothing), but the *test* against a real broker does require `mqtt.broker.host`.  That's a test-infrastructure concern, not a library-config concern.  The manifest stays library-shaped; the test declares its own contract.

`chumicro-pytest-device` minor VERSION bump.  Public-API surface change to the `set_runtime_config` signature (additive — new optional kwarg, existing zero-validation callers keep working).

### Phase 2 — per-library `from_config` factories + library refactor

For each library that has a manifest:

1. Add a `<Lib>Client.from_config(config, *, <non-config-args>)` classmethod that reads the library's manifest keys with sensible defaults for missing optional keys.
2. Update `examples/` to use `from_config` (this also fixes the post-migration broken examples that read nested `config.get("telemetry")` etc. — those silently fall through to hardcoded constants today).
3. Update functional tests where applicable (some tests construct directly to test edge cases — leave those alone).
4. Library minor VERSION bump per Decision 0023.

Order: probably `ntp` first (smallest surface — three knobs), then `mqtt` (largest surface), then the rest in any order.

**Hardware validation is mandatory for Phase 2.**  Each library's refactor must pass the four-board canonical matrix (Pi Pico W CP/MP + Lolin S2 CP/MP) before landing.  CPython unit tests don't catch on-device config-load failure modes.

### Phase 3 — `python scripts/run.py deploy-example <lib> <name>` (mono-repo)

A thin CLI that:

1. Locates `libraries/<lib>/examples/<name>.py`.
2. Composes config from root `secrets.toml` + per-lib `libraries/<lib>/examples/config.toml` (if present).
3. Validates against the import-graph manifest union (using the same `validate_runtime_config` the workspace deploy path uses).
4. Stages the example as `code.py` (CP) / `main.py` (MP) on the target device alongside the library deps.
5. Optionally drops to REPL via `chumicro-repl` for live observation.

Sister piece in `chumicro-deploy`: a "deploy-this-single-file-as-code.py" primitive that the `scripts/run.py` wrapper composes with.  Same primitive can power `chumicro-workspace` for user-authored libraries inside template-repo workspaces (later — not in scope today).

The pre-condition for this phase is the example-file shape being **self-executing** (top-level code that runs on import).  Most existing examples already are; any that aren't (e.g. `mqtt/examples/quickstart.py` exposes `def run_quickstart()`) get reshaped during Phase 2 anyway.

## Constraints

- Manifest declarations are **library-shaped**, not test- or example-shaped.  No `[tool.chumicro.config.functional_tests]` / `[tool.chumicro.config.examples.<name>]` sub-tables.  Test contracts live in conftest.py (Phase 1); example contracts live in the example file's own use of `from_config` (Phase 2).
- All Phase 0 keys are optional today — none of the five libraries' `src/` code reads runtime config yet.  Phase 2 may promote some to required where the library genuinely cannot function without (rare; `chumicro-wifi` is the only library where this is true today, and even there it's only `wifi.ssid` + `wifi.password`).
- No backwards-compat burden — `from_config` is additive; existing constructor calls keep working.
- Hardware validation gate is mandatory for Phase 2 only.  Phase 0 (pyproject-only) and Phase 1 (host-side test plumbing) ship without four-board sweeps.

## What this unblocks

Once all three phases ship:

- A contributor running `python scripts/run.py test-libraries-functional --library mqtt` against an unconfigured `secrets.toml` gets a precheck error (Phase 1), not a boot crash.
- A contributor running `python scripts/run.py deploy-example mqtt circuitpython_telemetry --device pi-pico-w` (Phase 3) gets the merged config validated host-side (Phase 0 manifests) before staging — same clear error path the user-project deploy path has had since Decision 0055.
- The "library cookbook" experience works: `WifiService(WifiConfig.from_config(config))` + `MQTTClient.from_config(config, socket=...)` + `NTPClient.from_config(config, socket=...)` is the canonical pattern; one source of truth for what each library reads from config; tooling can `dump-required-keys` against the import graph to show users what their `secrets.toml` should contain.

## Open questions

- **`requests.now_utc_tuple`** — used by tests + examples to seed the RTC for TLS cert validation on hardware without a real-time clock.  Belongs in `chumicro-requests`'s manifest as a forward-looking "library knows how to seed RTC if asked" knob, or stays as test-infrastructure outside the manifest?  Today: outside the manifest.  Revisit during Phase 2 when the `from_config` factory design lands.
- **TLS material paths in `http_server`** (`http_server.tls.cert_path`, `http_server.tls.key_path`) — declared optional today.  `from_config` factory should know how to construct an `ssl.SSLContext` from these paths for the listener.  Worked out during Phase 2.
- **Per-lib refactor parallelism** — Phase 2 can be done one lib per session with hardware validation in the loop, or batched across multiple libs in one session.  Probably one-lib-at-a-time given the mandatory four-board sweep.
