# Workstream: library `from_config` factories — config-aware constructors across the six networking libs

Status: **open — Phases 0 (manifests) + 1 (pytest-device validation hook) + 2-mqtt + 2-ntp shipped host-side; remaining Phase 2 libs (requests, http_server, websockets) and Phase 3 (`deploy-example` CLI, ADR queued) still to do.  mqtt + ntp Phase 2 host-side tests pass at ≥94 % coverage; four-board hardware sweep confirming both refactored examples (`circuitpython_telemetry`, `circuitpython_ntp_query`) is queued for a single bench session paired with Phase 3's first consumer (see "Recommended pairing with hardware validation" below).**

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
* **requests, http_server, websockets — not started.**  Each follows the same pattern.  Suggested order: `requests` → `websockets` → `http_server`.

**Hardware validation is mandatory before each library's Phase 2 closes.**  Each refactor must pass the four-board canonical matrix (Pi Pico W CP/MP + Lolin S2 CP/MP).  CPython unit tests don't catch on-device config-load failure modes.  mqtt's host-side tests at 95 % coverage and the example imports clean — that's necessary but not sufficient.

### Phase 3 — `python scripts/run.py deploy-example <lib> <name>` (mono-repo)

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

- **`requests.now_utc_tuple`** — used by tests + examples to seed the RTC for TLS cert validation on hardware without a real-time clock.  Belongs in `chumicro-requests`'s manifest as a forward-looking "library knows how to seed RTC if asked" knob, or stays as test-infrastructure outside the manifest?  Today: outside the manifest.  Revisit during Phase 2 when the `from_config` factory design lands.
- **TLS material paths in `http_server`** (`http_server.tls.cert_path`, `http_server.tls.key_path`) — declared optional today.  `from_config` factory should know how to construct an `ssl.SSLContext` from these paths for the listener.  Worked out during Phase 2.
- **Per-lib refactor parallelism** — Phase 2 can be done one lib per session with hardware validation in the loop, or batched across multiple libs in one session.  Probably one-lib-at-a-time given the mandatory four-board sweep.

## Future cleanups (lower priority)

- **Q11 ratchet** — a `scripts/check_config_manifest.py` lint that fails CI when a library's `src/` imports `chumicro_config` without declaring a `[tool.chumicro.config]` block in its `pyproject.toml`.  Would catch manifest-drift after-the-fact: a contributor who adds `from chumicro_config import config` to a library and forgets to declare the keys it reads.  Today: zero violations (only `chumicro-wifi` imports `chumicro_config` in `src/`, and it has a manifest), so the ratchet would ship green from day one.  Not high-priority since the failure mode it prevents is theoretical until 2-3 Phase 2 libs ship and the pattern of "src/ imports chumicro_config" actually exists across multiple libraries.  Re-evaluate after Phase 2 mqtt's hardware validation closes and at least one more Phase 2 lib ships.
- **`dump-required-keys` CLI surface** — `chumicro-workspace` already has `dump-config` (added during the config-shape workstream).  A sibling `dump-required-keys --project <name>` would walk the project's import graph, union the manifests, and print the keys the user's `secrets.toml` must populate.  Useful diagnostic; cheap to add once the import-graph aggregator is wired into the CLI subcommand.  Hold until a real user asks (template-repo onboarding feedback would be the trigger).
- **Drift check between manifest and library code** — manifest currently says "library reads these keys"; library code can say `config["wifi.new_key"]` without updating the manifest, or declare an `optional_key` it never reads.  An AST-based drift check (parse `config["..."]` / `config.get("...")` / `config.require("...")` in `src/` and reconcile against the manifest) is the long-form version of the Q11 ratchet.  ~150 LOC, useful once enough Phase 2 libs ship that drift is a real risk.  Not before.
