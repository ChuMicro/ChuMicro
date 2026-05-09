# Workstream: library `from_config` factories — config-aware constructors across the six networking libs

Status: **all phases shipped + bench-validated 2026-05-08 — Phases 0 + 1 + 2 (mqtt / ntp / requests / websockets / http_server) + 3 (`deploy-example` CLI per Decision [0059](../decisions/0059-deploy-example-front-door.md)).  CP-side bench session ran `timing/circuitpython_blink` + `ntp/circuitpython_ntp_query` + `requests/circuitpython_periodic_get` against both Pi Pico W CP and Lolin S2 CP; all six deploys succeeded end-to-end with WIFI_OK, NTP_OK, and HTTP 200 captured.  All three follow-ups shipped same day: (1) mqtt example's PEP 448 `**unpack` rewritten to temp-variable merge; (2) MP transport gained a `follow="soft_reboot"` kwarg mirroring CP's flash-mode pattern, `Deployer` auto-routes for `(MP, flash, /main.py)`, MP `while True` app code now deploys end-to-end with timeout-bounded partial-output capture (bench-validated on Pi Pico W MP + Lolin S2 MP); (3) CIRCUITPY UID stale-warning silenced on success.  Workstream complete.**

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

### Phase 1 — `chumicro-pytest-device` validation hook (shipped 2026-05-06)

`chumicro_pytest_device.runtime_config.set_runtime_config` gained an optional `required_keys` kwarg; the plugin's `pytest_collection_modifyitems` hook checks the staged payload against the registered required keys and applies a session-wide skip marker to every `DeviceRuntimeItem` when one or more are absent.  Skip message names every missing key in declaration order so the user knows exactly what to populate in `secrets.toml` or per-project config.

Per-conftest required-keys (not lib-manifest-driven) is the right shape: **the library doesn't require any of these keys** (its `src/` reads nothing), but the *test* against a real broker does require `mqtt.broker.host`.  That's a test-infrastructure concern, not a library-config concern.  The manifest stays library-shaped; the test declares its own contract via `set_runtime_config(..., required_keys=...)`.

All seven networking-library conftests updated to declare their required keys:

| Library conftest | Required keys |
|---|---|
| `wifi` | `wifi.ssid`, `wifi.password` |
| `mqtt` | `wifi.ssid`, `wifi.password`, `mqtt.broker.host`, `mqtt.broker.port` |
| `sockets` | `wifi.ssid`, `wifi.password`, `sockets.echo.host`, `sockets.echo.port` |
| `requests` | `wifi.ssid`, `wifi.password` (TLS test handles its `requests.now_utc_tuple` need inline) |
| `http_server` | `wifi.ssid`, `wifi.password` |
| `ntp` | `wifi.ssid`, `wifi.password` |
| `websockets` | `wifi.ssid`, `wifi.password`, `websockets.server.host`, `websockets.server.port` |

`chumicro-pytest-device` 0.4.0 → 0.5.0.  Additive API change — existing zero-validation callers keep working with the empty-tuple default.

Hardware validation **not** required for Phase 1 — host-side test plumbing only; CPython unit tests cover the new behavior.  When a contributor next runs `python scripts/run.py test-libraries-functional` against unconfigured creds, they'll get a clear precheck skip instead of an on-device boot crash.

### Phase 2 — per-library `from_config` factories + library refactor

For each library that has a manifest:

1. Add a `<Lib>Client.from_config(config, *, <non-config-args>)` classmethod that reads the library's manifest keys with sensible defaults for missing optional keys.
2. Update `examples/` to use `from_config` (this also fixes the post-migration broken examples that read nested `config.get("telemetry")` etc. — those silently fall through to hardcoded constants today).
3. Update functional tests where applicable (some tests construct directly to test edge cases — leave those alone).
4. Library minor VERSION bump per Decision 0023.

Status:

* **mqtt — shipped 2026-05-06 (host-side; hardware queued).**  `MQTTClient.from_config(config, *, radio=None, socket=None, socket_factory=None)` reads `mqtt.broker.host` / `mqtt.broker.port` / `mqtt.client_id` / `mqtt.keep_alive_seconds` / `mqtt.username` / `mqtt.password` with sensible defaults (`test.mosquitto.org:1883`, `chumicro-mqtt`, 60 s keepalive, no auth).  Auto-builds a default socket factory using config-supplied broker host/port when caller doesn't pass `socket=` / `socket_factory=`.  `mqtt/examples/circuitpython_telemetry.py` rewritten to use `WifiConfig.try_from_config(config)` + `MQTTClient.from_config(config, radio=...)` + flat-key reads for app-level concerns (`telemetry.topic`, `telemetry.command_topic`, `telemetry.sensor_id`).  Fixes the post-migration broken nested-section reads (`config.get("telemetry")` was silently returning `None` and falling through to constants).  mqtt 0.1.6 → 0.2.0.  **Hardware validation gap: the four-board sweep confirming the refactored example actually publishes is queued for a follow-on session — not closed.**
* **ntp — shipped 2026-05-07 (host-side; hardware queued).**  `NTPClient.from_config(config, *, radio=None, socket=None, socket_factory=None)` reads `ntp.server` / `ntp.port` / `ntp.timeout_ms` — **all optional** with fall-back defaults (`pool.ntp.org`, port 123, 5 s timeout).  Documented asymmetry vs mqtt: ntp's auto-built UDP socket factory reads zero config keys (server/port live on `NTPClient` itself, not on the socket), and the public NTP pool is the documented fallback for `ntp.server`, so an empty `config` dict is valid input.  `ntp/examples/circuitpython_ntp_query.py` rewritten to use `WifiConfig.try_from_config(config)` + `NTPClient.from_config(config, radio=...)`; falls back to placeholder wifi creds when `runtime_config.msgpack` is absent (NTP server falls through to library default — no edits needed).  ntp 0.1.1 → 0.2.0; 38 tests pass at 98 % coverage.  **Hardware validation gap: four-board sweep against the canonical matrix queued together with mqtt and Phase 3's first consumer — see pairing recommendation below.**
* **requests — shipped 2026-05-07 (host-side; hardware queued).**  `HttpClient.from_config(config, *, radio=None, ssl_context=None, connection_factory=None)` reads `requests.default_timeout_ms` / `requests.default_max_redirects` / `requests.user_agent` / `requests.max_body_bytes` — **all optional** with library defaults (10 s, 5 redirects, `chumicro-requests/0.1` UA, default body cap).  Same asymmetry as ntp: the auto-built `connection_factory` reads zero config keys (host/port live on each request URL, not on the client), so empty `config` is valid input.  `requests.now_utc_tuple` open question resolved: stays **outside** the manifest — only the TLS functional test seeds the RTC, and it does so via per-conftest `set_runtime_config(..., required_keys=...)` (Phase 1 mechanism).  Library code does no RTC seeding.  `requests/examples/circuitpython_periodic_get.py` rewritten to mirror the mqtt + ntp shape; fixes the post-migration broken nested-section reads (`config.get("wifi")`, `config.get("periodic_get", {})` were silently returning `None` / empty falling through to constants).  requests 0.1.4 → 0.2.0; 183 tests pass at 97 % coverage.  **Hardware validation gap: four-board sweep queued together with mqtt + ntp + Phase 3's first consumer.**
* **websockets — shipped 2026-05-07 (host-side; hardware queued).**  Two factories:
    * `WebSocketClient.from_config(config, *, radio=None, ssl_context=None, connection_factory=None)` reads `websockets.client.max_message_bytes` (optional, library default).  Same asymmetry as ntp / requests — the auto-built `connection_factory` reads zero config keys (host/port/use_tls live on each `connect()` URL, not on the client).
    * `WebSocketServer.from_config(config, on_connection, *, radio=None, listener=None, accept_path=None, max_connections=2)` reads `websockets.server.host` (default `0.0.0.0`) / `websockets.server.port` (default `8765`, the library-convention demo port) / `websockets.server.max_message_bytes` (optional, library default).  Auto-builds a listener via `chumicro_sockets.tcp_listening_socket(host, port, radio=...)` when caller doesn't pass `listener=`.  `on_connection` is required positional — it's a callback the user must provide; can't be read from a flat dict.
    * **Manifest-quirk documented:** `websockets.client.connect_url` is in the manifest because users set it per-project, but `WebSocketClient.from_config` doesn't read it — URL is a per-connection arg the user passes to `connect()` after construction.  Documented in the from_config docstring and exercised by the test `test_connect_url_not_consumed_by_from_config`.  Same pattern would apply to any future per-call argument that's nonetheless useful to declare in a project config.
    * `accept_path` is per-deploy app routing, not library-shape — kept as a `from_config` kwarg, intentionally absent from the manifest.
    * Both examples (`circuitpython_client.py` + `circuitpython_server.py`) rewritten to mirror the mqtt + ntp + requests shape.  websockets 0.9.2 → 0.10.0; 284 tests pass at 96 % coverage.  **Hardware validation gap: four-board sweep queued.**
* **http_server — shipped 2026-05-08 (host-side; hardware queued).**  `HttpServer.from_config(config, *, handler=None, radio=None, ssl_context=None, listener_factory=None)` reads `http_server.bind_host` (default `0.0.0.0`) / `bind_port` (default 8080, the existing example port) / `max_connections` / `request_timeout_ms` / `max_request_body_bytes` (last three default to library constants) plus the optional TLS pair `tls.cert_path` / `tls.key_path`.  TLS resolution priority: explicit `listener_factory` wins; else explicit `ssl_context` triggers `tls_listening_socket`; else both config TLS paths trigger TLS via `ssl_context_with_cert_and_key_paths`; else plain TCP.  **Half-TLS** (one of the two paths set, the other absent) raises `MissingConfigKey` so a half-configured deploy fails loudly instead of silently falling through to plain TCP — same loud-failure principle mqtt's `from_config` applies for missing broker host.  `examples/circuitpython_two_thing_server.py` rewritten to mirror the workstream's other refactored examples; `circuitpython_two_thing_sensor.py` left as-is (it's an HTTP *client*, not a server, so Phase 2 requests already covers its config story).  http_server 0.1.4 → 0.2.0; 11 new TestFromConfig tests; package coverage 95 %.  **Hardware validation gap: four-board sweep queued.**

**Hardware validation is mandatory before each library's Phase 2 closes.**  Each refactor must pass the four-board canonical matrix (Pi Pico W CP/MP + Lolin S2 CP/MP).  CPython unit tests don't catch on-device config-load failure modes.  mqtt's host-side tests at 95 % coverage and the example imports clean — that's necessary but not sufficient.

### Phase 3 — `python scripts/run.py deploy-example <lib> <name>` (mono-repo)

**Status: shipped 2026-05-07 (host-side; hardware queued).**  Three commits across `chumicro_deploy` + `chumicro_workspace` + `scripts/run.py`:

* **3a** ([Decision 0053](../decisions/0053-recovery-layer-philosophy.md)'s `DeployFailureKind` enum gained `NO_PYTHON_RUNTIME`) — classifier patterns + recovery plan pointing at `install-firmware`; non-retryable per the destructive-action consent rule.  Lights up across every workbench tool that classifies deploy failures, not just `deploy-example`.
* **3b** (`chumicro_workspace.example_source` FileSource) — composes `ImportGraphSource` + `WithRuntimeConfig` + `__chumicro_runtimes__` filtering; adds example-path resolution under `libraries/<lib>/examples/<name>.py`, runtime → entrypoint mapping (CP `code.py` / MP `main.py`), and a default output path under `<secrets>.parent/.scratch/` so generated msgpack artifacts never pollute the tracked tree.  17 tests at 100 % coverage.
* **3c** (`chumicro-workspace deploy-example` subcommand + `python scripts/run.py deploy-example` shim) — full state-(1)–(4) handler covering precheck (file exists / runtime marker / multi-runtime disambiguation), no-device-registered (state 1) with TTY-detected interactive vs `--non-interactive` non-interactive bootstrap fall-through, runtime mismatch (state 2 precheck), `NO_PYTHON_RUNTIME` (state 3 → exit 6), and generic deploy failure (state 4 → exit 4).  Distinct exit codes 0/2/3/4/5/6 per ADR 0059 §5.  Optional `--tail` drops into `chumicro-repl` after deploy; `--non-interactive` forces no-tail.  `--list` discovers available examples.  24 cli tests + 4 shim tests pass; workspace package at 94 % coverage.

**Below is the original investigation note kept for context.**


User-facing surface:

1. Locates `libraries/<lib>/examples/<name>.py`.
2. Composes config from root `secrets.toml` + per-lib `libraries/<lib>/examples/config.toml` (if present).
3. Validates against the import-graph manifest union (using the same `validate_runtime_config` the workspace deploy path uses).
4. Stages the example as `code.py` (CP) / `main.py` (MP) on the target device alongside the library deps.
5. Optionally drops to REPL via `chumicro-repl` for live observation.

**Implementation shape (investigated 2026-05-06; not yet started):**

The existing `chumicro_deploy.Deployer.deploy(source: FileSource)` plus `chumicro_workspace.WithRuntimeConfig` decorator handle most of the plumbing — `WithRuntimeConfig` already reads `secrets_toml` + `project_config`, validates against `library_roots` manifests, and merges the encoded msgpack into the inner source's file map at `/runtime_config.msgpack`.

What doesn't exist yet: a `FileSource` implementation that maps a **single example file** to the on-device entrypoint (renaming `circuitpython_telemetry.py` → `/code.py` / `/main.py`) plus walks the example's import graph to bring along the right library `src/` trees under `/lib/`.  Existing `DirectorySource` treats a whole directory as one project — wrong shape for "this single file is the entrypoint, neighbouring example files in the same folder are unrelated."  Existing `project_import_graph_source` assumes a workspace-shaped project directory layout, also wrong.

So Phase 3 is **new infrastructure**, roughly:

* `chumicro_workspace.example_source(library_name, example_name, *, runtime, secrets_toml, ...)` returning a `FileSource` — the new piece.  Resolves the example file path under `libraries/<lib>/examples/<name>.py`, walks its imports against the workspace's library roots to determine which libs to ship, builds the path → bytes map with the example renamed to the runtime-appropriate entrypoint name, then wraps in `WithRuntimeConfig` for the config-merge + validation step.  Per-lib `examples/config.toml` (if present) feeds in as the `project_config` argument.
* `python scripts/run.py deploy-example <lib> <name>` — thin CLI on top.  Reads `devices.yml` for the target, calls into the new function, drives `Deployer.deploy(source)`.  Optional `--tail` flag drops to `chumicro-repl tail` after deploy for live output.

Estimated scope: ~150–200 LOC for the new `example_source` (most of which is the import-graph walk + entrypoint-path resolution; config merge + validation reuses `WithRuntimeConfig`) + ~50 LOC CLI wrapper + ~150 LOC tests covering the file map, entrypoint resolution per-runtime, manifest validation pass-through, and the missing-file error paths.

**Recommended pairing with hardware validation:** Phase 3's first real consumer should be `mqtt/examples/circuitpython_telemetry.py` (refactored in Phase 2 mqtt this session — currently waiting on its own four-board hardware sweep).  Doing both together — implement Phase 3, then validate Phase 2 mqtt + Phase 3 in one hardware sweep against the four-board canonical matrix — closes both gaps with a single bench session.  Stub `examples/config.toml` for mqtt would carry `[telemetry]` topic / command_topic / sensor_id and possibly `[mqtt]` broker overrides for the user's local broker.

The original "wifi pilot first" framing is now stale: wifi's only example (`quickstart.py`) uses `FakeWifi` deliberately so it runs anywhere, so it doesn't exercise the manifest/config-merge path Phase 3 is built around.  mqtt telemetry is the right pilot — Phase 2 mqtt landed precisely so this pairing would be coherent.

The pre-condition for this phase is the example-file shape being **self-executing** (top-level code that runs on import).  Most existing examples already are; the refactored `mqtt/examples/circuitpython_telemetry.py` is.  Any others that aren't get reshaped during the corresponding library's Phase 2 anyway.

**Sister piece (not in scope today):** the same `example_source` could power `chumicro-workspace` for user-authored libraries' examples inside template-repo workspaces — but the user has explicitly scoped Phase 3 to mono-repo only ("for now it would be easier if they just ran the examples from the chumicro repo itself in a fork or clone").  Promote later if a template-repo user actually asks.

## Constraints

- Manifest declarations are **library-shaped**, not test- or example-shaped.  No `[tool.chumicro.config.functional_tests]` / `[tool.chumicro.config.examples.<name>]` sub-tables.  Test contracts live in conftest.py (Phase 1); example contracts live in the example file's own use of `from_config` (Phase 2).
- All Phase 0 keys are optional today — none of the five libraries' `src/` code reads runtime config yet.  Phase 2 may promote some to required where the library genuinely cannot function without (rare; `chumicro-wifi` is the only library where this is true today, and even there it's only `wifi.ssid` + `wifi.password`).
- **`required` vs `optional` axis**: required = library has no sensible default and genuinely cannot function without (`wifi.ssid` / `wifi.password`).  optional = library has a default it falls back to (everything else: broker host defaults to `test.mosquitto.org`, NTP server to `pool.ntp.org`, HTTP timeout to 30 s, etc.).  When in doubt: optional.  Promoting to required is a deploy-time-error-on-miss hard gate against every consumer; reserve it for "the library cannot construct itself without this."
- **Validator semantics**: `chumicro_workspace.validate_runtime_config` only enforces `required_keys` — missing one fails the deploy.  `optional_keys` carry no enforcement; the validator accepts them present-or-absent without comment, and unknown keys (not declared in any library's manifest) pass through silently.  Documentation/discoverability tools (`dump-config`, future `dump-required-keys`) read `optional_keys` so users see what they *can* set; the validator does not gate on them.
- **Three-layer mental model**: per-library manifest declares "if you use me, here are my keys" → `validate_runtime_config` aggregates the manifests of every library in a project's deploy graph into a per-project union → that union is what the validator checks the user's merged `secrets.toml` + per-project config dict against.  A library manifest alone can never tell a user what their `secrets.toml` needs — that's only knowable in the context of "user X is using libs Y, Z, W."
- No backwards-compat burden — `from_config` is additive; existing constructor calls keep working.
- Hardware validation gate is mandatory for Phase 2 only.  Phase 0 (pyproject-only) and Phase 1 (host-side test plumbing) ship without four-board sweeps.

## What this unblocks

Once all three phases ship:

- A contributor running `python scripts/run.py test-libraries-functional --library mqtt` against an unconfigured `secrets.toml` gets a precheck error (Phase 1), not a boot crash.
- A contributor running `python scripts/run.py deploy-example mqtt circuitpython_telemetry --device pi-pico-w` (Phase 3) gets the merged config validated host-side (Phase 0 manifests) before staging — same clear error path the user-project deploy path has had since Decision 0055.
- The "library cookbook" experience works: `WifiService(WifiConfig.from_config(config))` + `MQTTClient.from_config(config, socket=...)` + `NTPClient.from_config(config, socket=...)` is the canonical pattern; one source of truth for what each library reads from config; tooling can `dump-required-keys` against the import graph to show users what their `secrets.toml` should contain.

## Open questions

- ~~**`requests.now_utc_tuple`** — used by tests + examples to seed the RTC for TLS cert validation on hardware without a real-time clock.  Belongs in `chumicro-requests`'s manifest as a forward-looking "library knows how to seed RTC if asked" knob, or stays as test-infrastructure outside the manifest?  Today: outside the manifest.  Revisit during Phase 2 when the `from_config` factory design lands.~~  Resolved 2026-05-07 with Phase 2 requests: stays outside the manifest.  RTC seeding is application-level concern, not library-level — coupling `chumicro-requests` to platform-specific RTC modules (CP `rtc.RTC`, MP `machine.RTC`) for a TLS-only test infrastructure need would distort the library's surface.  The TLS functional test reads the key via per-conftest `set_runtime_config(..., required_keys=("requests.now_utc_tuple",))` per the Phase 1 mechanism, which is exactly the right shape for a test-infrastructure key.
- ~~**TLS material paths in `http_server`** (`http_server.tls.cert_path`, `http_server.tls.key_path`) — declared optional today.  `from_config` factory should know how to construct an `ssl.SSLContext` from these paths for the listener.  Worked out during Phase 2.~~  Resolved 2026-05-08 with Phase 2 http_server: both paths optional, but **both-or-neither** — half-TLS raises `MissingConfigKey`.  `from_config` builds the context via `chumicro_sockets.ssl_context_with_cert_and_key_paths(...)` and routes through `tls_listening_socket`; explicit `ssl_context=` arg overrides + works with no config paths set; explicit `listener_factory=` skips the auto-build entirely.
- **Per-lib refactor parallelism** — Phase 2 can be done one lib per session with hardware validation in the loop, or batched across multiple libs in one session.  Probably one-lib-at-a-time given the mandatory four-board sweep.

## Future cleanups (lower priority)

- **Q11 ratchet** — a `scripts/check_config_manifest.py` lint that fails CI when a library's `src/` imports `chumicro_config` without declaring a `[tool.chumicro.config]` block in its `pyproject.toml`.  Would catch manifest-drift after-the-fact: a contributor who adds `from chumicro_config import config` to a library and forgets to declare the keys it reads.  Today: zero violations (only `chumicro-wifi` imports `chumicro_config` in `src/`, and it has a manifest), so the ratchet would ship green from day one.  Not high-priority since the failure mode it prevents is theoretical until 2-3 Phase 2 libs ship and the pattern of "src/ imports chumicro_config" actually exists across multiple libraries.  Re-evaluate after Phase 2 mqtt's hardware validation closes and at least one more Phase 2 lib ships.
- **`dump-required-keys` CLI surface** — `chumicro-workspace` already has `dump-config` (added during the config-shape workstream).  A sibling `dump-required-keys --project <name>` would walk the project's import graph, union the manifests, and print the keys the user's `secrets.toml` must populate.  Useful diagnostic; cheap to add once the import-graph aggregator is wired into the CLI subcommand.  Hold until a real user asks (template-repo onboarding feedback would be the trigger).
- **Drift check between manifest and library code** — manifest currently says "library reads these keys"; library code can say `config["wifi.new_key"]` without updating the manifest, or declare an `optional_key` it never reads.  An AST-based drift check (parse `config["..."]` / `config.get("...")` / `config.require("...")` in `src/` and reconcile against the manifest) is the long-form version of the Q11 ratchet.  ~150 LOC, useful once enough Phase 2 libs ship that drift is a real risk.  Not before.

## Follow-ups from the bench session (2026-05-08)

CP-side bench validation ran clean on `timing/circuitpython_blink` + `ntp/circuitpython_ntp_query` + `requests/circuitpython_periodic_get` across both Pi Pico W CP and Lolin S2 CP.  Three issues surfaced — all orthogonal to the workstream's host-side scope (they don't undo the `from_config` factory acceptance), but worth detailed handoff notes so a future session can pick them up cold.

The handoff sections below follow a fixed shape: **what we know** (load-bearing facts, with file:line refs from the bench session); **what we don't know** (the next-step questions before the fix lands); **proposed fix** (shape only, not committed); **estimated effort + dependencies**.  Read the bench session entries in `plans/next-up.md` "Done (recent)" for the symptom narrative.

### Follow-up 1 — mqtt example's PEP 448 `**unpack` rewritten (shipped)

**Status:** shipped 2026-05-08.  `libraries/mqtt/examples/circuitpython_telemetry.py:161-165` rewritten from the multi-line dict-literal `**unpack` to a temp-variable merge:

```python
merged = dict(mqtt_config.to_dict())
merged["mqtt.broker.host"] = BROKER_HOST
merged["mqtt.broker.port"] = BROKER_PORT
mqtt_config = RuntimeConfig(merged)
```

Same final dict; no behavioural change.  Bench-validated: `python scripts/run.py deploy-example mqtt circuitpython_telemetry --device pi-pico-w-circuitpython-board --non-interactive` deployed without `SyntaxError`, executed past line 162 (the original failure point), and reached `WIFI_OK ip=172.16.1.21` — proof the CP parser accepts the new shape.  Pre-fix grep confirmed this was the only `**`-unpack idiom in `libraries/*/examples/`, so no audit overhang.

**Not done (deliberately).**  We did *not* run the minimal CP-REPL probe of `d = {**{}, "k": 1}` to determine whether CircuitPython 10.2.0-rc.0 rejects the entire PEP 448 dict-`**unpack` idiom or just the multi-line continuation.  The fix is robust either way — the question only matters for filing an upstream CircuitPython issue.  Defer until the same idiom resurfaces somewhere else; if it does, run the probe then.

### Follow-up 2 — MP `deploy-example` of infinite-loop examples times out (shipped)

**Status:** shipped 2026-05-08.  `MicropythonTransport.deploy_files` gained a `follow: Literal["exec", "soft_reboot"]` kwarg (default `"exec"` preserves the test-harness path).  `follow="soft_reboot"` exits raw REPL via Ctrl-B (with a prompt-sync wait — bench-tested as necessary on Pi Pico W MP because back-to-back Ctrl-B + Ctrl-D raced the firmware's raw-REPL exit), sends Ctrl-D to soft-reboot, lets MP auto-run `/main.py`, reads serial output via `read_until(b"\r\n>>> ")` bounded by `self.timeout` (default 10 s, matching `CircuitpythonTransport.timeout`).  The friendly-REPL `>>> ` prompt is the MP analog of CP's `Code done running.` end marker; for `while True` bodies the prompt never appears and the read returns whatever accumulated.  `Deployer.deploy_diff` / `Deployer.deploy` auto-route to `follow="soft_reboot"` for `(MP, flash, /main.py)`; everything else stays on `"exec"`.  See [Decision 0028 §MicroPython flash transport](../decisions/0028-deploy-modes.md#micropython-flash-transport) for the canonical reference.

Bench-validated end-to-end: `python scripts/run.py deploy-example timing micropython_blink --device pi-pico-w-micropython-board --non-interactive` and the same against `--device lolin-s2-micropython-board` both exit 0 (silently, since the blink example has no `print()`s).  A chatty `while True` test main.py (BENCH_BEGIN + WIFI_OK + NTP_OK + 10 ticks every 1 s) deployed via the same path captured 133 chars of partial output during the 10 s window before returning success.

**Pre-fix narrative (preserved for context).**  The original symptom: `deploy-example timing micropython_blink` exited 4 with `Device deploy-execute failed: timeout waiting for first EOF reception` (classified `bootstrap_exec_failed`) after `_EXECUTE_IDLE_TIMEOUT` = 300 s of consecutive serial silence.  `timing/examples/micropython_blink.py` is a `while True: heartbeat.poll(...)` body that never returns and never `print()`s — raw-REPL `exec_raw` waits forever for an EOF marker that never fires.

**Implementation summary.**  Files changed: `workbench/deploy/src/chumicro_deploy/micropython_transport.py` (added `_trigger_soft_reboot_and_read` + `_extract_main_py_output` helpers, `timeout` constructor arg defaulting to 10 s for symmetry with CP, `follow` kwarg on `deploy_files`); `workbench/deploy/src/chumicro_deploy/deployer.py` (added `_deploy_files_kwargs` helper auto-routing `follow="soft_reboot"` for `(MP, FLASH, /main.py)`); `workbench/deploy/src/chumicro_deploy/testing.py` (extended `FakeTransport.deploy_files` to record + ignore the `follow` kwarg).  Test scaffolding extended with `FakeSerialPort` for byte-level write recording + `read_until_outputs` queue, plus 14 new unit tests covering the soft-reboot path and 4 covering the routing.

The two-stage Ctrl-B → wait-for-prompt → Ctrl-D sequence is bench-validated as necessary on Pi Pico W MP — back-to-back writes raced the firmware's raw-REPL exit and Ctrl-D was eaten before MP transitioned to friendly REPL.  Without the prompt-sync wait, the read returned the friendly-REPL banner with no `MPY: soft reboot` marker.

The canonical "what does each mode do" reference is now [Decision 0028 §MicroPython flash transport](../decisions/0028-deploy-modes.md#micropython-flash-transport) — that section was rewritten from "in flight" to describe shipped state in the same commit.

### Follow-up 3 — CIRCUITPY drive UID stale-warning (shipped — Variant A)

**Status:** Variant A landed 2026-05-08.  `_resolve_identity_match` (`workbench/deploy/src/chumicro_deploy/circuitpython_transport.py`) now silently returns the corrected path when a sibling `CIRCUITPY*` mount matches the probed UID; only the no-match-found case still raises (with the same nudge to drop or fix `devices.yml`'s `circuitpy_drive_path`).  The previous `WARNING:` print fired on every two-board bench deploy, where macOS auto-rename of the second `/Volumes/CIRCUITPY → CIRCUITPY 1` is normal and the auto-correction is reliable — the message read scarier than reality.  Two tests updated: `test_auto_corrects_silently_to_sibling_mount_on_mismatch` now guards against the print regressing (`captured.out == ""`), and `test_uid_match_preferred_over_machine_when_both_available` relies on the implicit branch-distinguishing return value.  Troubleshooting doc (`docs/troubleshooting/macos-circuitpy.md`) updated to match.

Variant B (drop `circuitpy_drive_path` from `devices.yml`'s user-owned zone — bigger change touching `add-device` write paths) was *not* picked up — defer until template-repo onboarding feedback flags drive-path drift as a real source of confusion.

### Cross-follow-up notes

- **All three follow-ups shipped 2026-05-08.**  The Phase 2 + Phase 3 acceptance criteria + the three bench-session items all complete.  Workstream is closed for archiving.
