# Consumer-angle review: ChuMicro-Workspace-Template vs monorepo main

Date: 2026-07-03
Reviewer angle: the template is the consumer face — users clone it to write chumicro
projects. Read the sibling `ChuMicro-Workspace-Template` checkout (last commit
`c4b69f6`, 2026-05-24) against this mono-repo's main
(`80760e7a`), which has taken a 394-commit June–July wave since the template synced.

Both repos were read-only. Evidence is `file:line`; template paths are under
`ChuMicro-Workspace-Template/`, monorepo paths under `chumicro/`.

---

## 1. Drift inventory

### 1a. Breaking changes on main since 2026-05-24 (from `git log` + decisions)

Enumerated from the monorepo log, then checked against template usage below:

- **Decision 0092** (`73568121`, `69ce2a64`; `plans/decisions/0092-…md`): no backwards
  compatibility before publication. Breaking renames land freely and *every* consumer
  (libs, demos, examples, tests, docs) is migrated in the same commit. The template is a
  separate repo, so it was **not** carried along — this is the root cause of every hard
  break below.
- **runner**: `run_until(handle)` + convenience (`0aa0a126`, `59e7d8ab`), event-wait
  `Signal` (`0cfe5cbb`, `0091`). The two-callable `add(check, handler)` shape was
  **removed** — it now raises `ValueError` (`chumicro/libraries/runner/src/chumicro_runner/core.py:316-321`).
- **mqtt 0.20.0**: `next_message()` receive-stream generator (`b0819ab9`); the
  QoS-ack/callback cascade was dropped (`972525c1`, `9356698d`).
- **requests**: `connector_factory` kwarg + `sockets_factory` submodule (`a6ddf8c7`;
  and the template's own last commit `c4b69f6` migrated requests).
- **Decision 0093** transport-factory contract (`aee5fc45`; `plans/decisions/0093-…md`).
- **deploy**: clean-slate default per **0077** (`60d463e9`, `ce8ae960`); `repl` retired
  into `deploy --tail`; `deploy-example` collapsed to a thin front-end; low-level
  `chumicro-deploy` CLI folded onto one `deploy_diff`.
- **install-libraries removed** → `library add` per **Decision 0078** (dated 2026-05-18,
  i.e. already stale at the template's last commit).

### 1b. HARD BREAKS — committed template code that will not run on current libraries

- **`projects/example_sensor/app.py:151-155`** — the flagship "canonical reference"
  (README.md:160-163) constructs `MQTTClient(socket_factory=socket_factory, …)`. The
  current constructor `chumicro/libraries/mqtt/src/chumicro_mqtt/client.py:262-266` takes
  `socket=` / `connector_factory=` and has **no `socket_factory` parameter** → `TypeError`
  at construction. Worse than a rename: `_make_socket_factory` (app.py:111-127) returns a
  *live socket* via `tcp_client_socket`/`tls_client_socket`, but the new `connector_factory`
  must return a **connector** (non-blocking connect state machine, Decision 0093 shape #3 +
  0081), so the whole closure pattern is obsolete, not just the kwarg. The canonical path is
  now `MQTTClient.from_config(config, radio=wifi.adapter.radio)`
  (`chumicro/demos/mqtt_pub_sub/app.py`).
- **`examples/telemetry_publisher/app.py:92-96`** — identical `MQTTClient(socket_factory=…)`
  break; identical obsolete `_make_socket_factory` (app.py:58-74).

These are the only two hard-broken committed files, but one of them is the reference the
README, the `add-new-project` skill (SKILL.md:42-44), and `examples/README.md:42-44` all
point new authors at.

### 1c. Verified NON-breaks (checked so the inventory doesn't over-claim)

- `from chumicro_mqtt.client import ProtocolState` (example_sensor:20, telemetry_publisher:17)
  still resolves — `ProtocolState` is defined in `client.py` and re-exported
  (`chumicro/libraries/mqtt/src/chumicro_mqtt/__init__.py:23`). Non-canonical (demos import
  it top-level) but not broken.
- `from chumicro_sockets import tcp_client_socket, tls_client_socket` still exported
  (`chumicro/libraries/sockets/src/chumicro_sockets/__init__.py:60,63`).
- Wifi surface is stable: `wifi.connected` / `wifi.state` / `wifi.last_error` / `wifi.ip` /
  `WifiState.*` all present (`chumicro/libraries/wifi/src/chumicro_wifi/service.py:103-104,124-126`).
  So the wifi bring-up loop used in 6 files still works verbatim.
- `HttpClient(connector_factory=chumicro_sockets_connector_factory())`
  (periodic_get:77, two_board client:112) matches the current requests shape — constructor
  kwarg stayed `connector_factory=`, submodule stayed `sockets_factory`
  (`chumicro/libraries/requests/src/chumicro_requests/client.py:451-462`,
  `sockets_factory.py`). Only nit: no `radio=` (see 1d).
- `HttpServer(listener_factory=_make_listener_factory(…))` (two_board server:117) — the
  `listener_factory=` kwarg is preserved (`chumicro/libraries/http_server/src/chumicro_http_server/server.py:631-634`);
  `tcp_listening_socket` still exported. Likely functional (verify `@server.route` /
  `build_response` separately — not covered here).

### 1d. STALE-BUT-FUNCTIONAL — runs, but drifted from the current idiom

- **Busy-spin loops (all 6 apps).** `while True: runner.tick()` with **no `runner.wait()`**:
  example_sensor:170-171, wifi_only:64-68, periodic_get:86-88, telemetry_publisher:107-109,
  two_board server:122-123, two_board client:122-123. Canonical is now
  `while True: now = runner.tick(); runner.wait(now)`
  (`chumicro/libraries/runner/docs/guide.md:81-84`) or `runner.run_until(handle/predicate)`
  (`core.py:630`). Omitting `wait()` never parks the CPU — a real on-device power cost, not
  just style. Every current demo uses `run_until` (`chumicro/demos/mqtt_pub_sub/app.py`,
  `chumicro/demos/requests_fetch/app.py:56`).
- **Hand-rolled periodic tick objects.** `_HeartbeatPublisher`, `_PeriodicFetcher`,
  `_StatusBeacon`, `_PeriodicPoster` each reimplement scheduling with
  `ticks_ms`/`ticks_add`/`ticks_diff`. `Runner.add_periodic(fn, period_ms=…)`
  (`core.py:400`) now owns this.
- **requests factory called with no `radio=`** (periodic_get:77, two_board client:112).
  Current demos pass `radio=wifi.adapter.radio` (`chumicro/demos/requests_fetch/app.py:31`).
  `radio` defaults to `None` → `wifi.radio` singleton fallback on CircuitPython, so probably
  still works, but it is no longer the shown form. Verify on a CP board.

### 1e. CONFIG / CLI / DOC drift

- **`install-libraries` removed** (Decision 0078) but referenced at README.md:144, 234, 238,
  259 (the entire step-6 install flow + the dry-run tip). Confirmed absent from the current
  CLI — the only surviving reference in the monorepo is a CHU014 test asserting it is *gone*
  (`chumicro/workbench/checks/tests/test_chu014.py:121`). Replacement is `library add <name>`
  (`chumicro/workbench/workspace/src/chumicro_workspace/cli/library.py:531`).
- **`repl` as deploy-then-follow** (README.md:149-151; `add-new-project` SKILL.md:101-113;
  `deploy-and-debug` SKILL.md:23-28). `repl` still exists but no longer deploys — it "never
  stages code to a board" (`chumicro/…/cli/repl.py:1-6`). Deploy-then-watch is now
  `deploy <project> --tail`, which explicitly "Replaces the old `repl <project>`
  deploy-then-watch shortcut" (`chumicro/…/cli/deploy.py:938-940`).
- **`set-default` is not a command.** `register-board` SKILL.md:78 runs
  `python run.py set-default --runtime micropython …`; no such subcommand exists (defaults are
  written by `add-device` and live in `devices.yml`'s `defaults:` block, devices.yml:14-18).
- **Clean-slate deploy default is undocumented in the template.** Deploy now wipes anything
  not in the payload or the keep-set `{boot.py, boot_out.txt, _chu_kv.msgpack}` and evicts a
  board-resident `settings.toml` (`chumicro/…/cli/deploy.py:876-899`, Decision 0077). The
  template README:31-37 still sells "atomic deploys" with no mention that the default now
  *removes* board files — which directly conflicts with its own README:144
  install-libraries-then-deploy flow (circup-installed `/lib` would be at risk under a
  clean-slate flat deploy).
- **Stale generated cruft**: committed `__pycache__/app.cpython-314.pyc` under every example
  and `_generated/runtime_config.msgpack` under scratch projects. Not consumer breaks, but
  they ship stale bytecode in a "clone-and-go" starter.

### 1f. Commands the template uses that are still valid (no drift)

`setup`, `new`, `add-device`, `deploy`, `dump-config`, `projects`, `test`, `lint`,
`doctor`, `status`, `discover`, `probe`, `devices`, `rename`, `install-firmware`,
`upgrade-firmware` all still register (`chumicro/…/cli/__init__.py:56-90`).

---

## 2. Project-authoring friction (writing a NEW project today)

`python run.py new <name> --from examples/<x>` copies an example verbatim, so the examples
*are* the starting boilerplate. Measured from them:

**Per-project boilerplate a user copies and owns:**
- **Wifi bring-up block, ~7 lines, repeated verbatim in 6 files** (example_sensor:140-148,
  wifi_only:58-63, periodic_get:66-75, telemetry_publisher:81-90, two_board server:103-112,
  two_board client:100-109): build `WifiService(WifiConfig.from_config(config))`, `runner.add`,
  then `while not wifi.connected: runner.tick(); if wifi.state == FAILED: raise SystemExit(…)`.
  There is no library-blessed "block until link up or fail" helper, though the demos already
  express it as `yield from wait_for(link_up)` via `Signal`
  (`chumicro/demos/requests_fetch/app.py:29`).
- **Transport-factory closure** (mqtt: ~17 lines of `_make_socket_factory`) — now redundant
  with `from_config(config, radio=…)`.
- **Periodic scheduling plumbing** — every tick object hand-writes `_next_at = ticks_ms()`,
  a `check()` doing `ticks_diff`, and a `handle()` doing `ticks_add` — redundant with
  `add_periodic`.
- **Manual loop + `KeyboardInterrupt` handling** in every `run()`.
- **example_sensor only**: a module-global `_SHUTDOWN_REQUESTED` + `request_shutdown()`
  (app.py:34-40) invented because there is no blessed "run until told to stop" — `run_until(predicate)`
  now fills exactly this.

**Concepts a user must learn for even the smallest networked project:**
- The Runner tick/`check`/`handle` protocol *and* monotonic-ticks math (`ticks_ms`/`ticks_add`/
  `ticks_diff`, 32-bit wrap — spelled out in a docstring at wifi_only:33-36) just to do
  something every N ms.
- The `WifiService` state machine (enum + `connected`/`state`/`last_error`/`ip`).
- Three config access styles with no single idiom: `config.require("mqtt.broker")`,
  `config.get("mqtt.tls", False)`, and `config["mqtt.broker.host"]` (demo form) all coexist.
- The two-file merge (`secrets.toml` + `project_config.toml` → flat `/runtime_config.msgpack`,
  neither file lands on device) — explained well at `add-new-project` SKILL.md:72-78.
- The transport-factory contract if they touch mqtt/requests/websockets/http_server: **three
  kwarg spellings across four libraries** — `connector_factory` (requests/websockets),
  `socket_factory` (ntp), `listener_factory` (http_server), `socket=` override (mqtt)
  (`chumicro/plans/decisions/0093-…md:38`). This is a genuine learning tax.

**Error paths that coach badly:**
- Wifi failure is `raise SystemExit(f"wifi failed: {wifi.last_error}")`, hand-rolled in every
  example — on-device this just halts `run()` with a bare string; no retry/backoff guidance.
- mqtt publish failure is a broad `except Exception` that prints and reschedules
  (example_sensor:99-101, telemetry_publisher:52-55) — no coaching, swallows real bugs.
- **Counter-example (a strength):** deploy-time errors coach *very* well — layout/entrypoint
  mismatches name the exact fix (`chumicro/…/cli/deploy.py:190-281`), `async def run()` is
  rejected with a pointer to the tick pattern (deploy.py:246-258), and boot-reachable hard
  resets are refused (deploy.py:284-311). The template inherits all of this for free.

---

## 3. Integrate vs port (feeds the pending DI decision) — facts, both angles

Dep-graph tooling: `chumicro/scripts/render_dep_graph.py` (strict edges from each
`pyproject.toml` `[project.dependencies]`; dashed DI edges hand-curated in `DI_DEPS`),
rendering `chumicro/support/docs/dependency-graph.svg`; a `check-dep-graph` preflight task
fails CI on un-regenerated drift.

**Core fact:** all four networked libraries have **zero unconditional (import-time) chumicro
sibling imports**. Every sibling is reached only through the lazy `sockets_factory` submodule
or a lazy `ticks` DI fallback. `chumicro_sockets` is a pure leaf (its `pyproject.toml` has no
`dependencies` key at all).

Minimal closures (which siblings importing lib X actually pulls):

| Library | `from_config` (ergonomic) path | BYO transport + inject `ticks=` | BYO transport, default ticks |
|---|---|---|---|
| `chumicro_sockets` | `{}` (leaf) | `{}` | `{}` |
| `chumicro_mqtt` | `{config, sockets, timing}` | `{}` | `{timing}` |
| `chumicro_websockets` | `{sockets, timing}` | `{}` | `{timing}` |
| `chumicro_requests` | `{sockets, timing}` (also via `generators` submodule) | `{}` | `{timing}` |

Evidence: mqtt factory-only imports at `client.py:288-303` + `sockets_factory.py`; ticks
fallback `client.py:472`. requests factory at `client.py:421-436`; ticks `client.py:539`.
websockets `client.py:140`/`server.py:352`. mqtt is the only one that pulls `chumicro_config`,
and only via the factory. (Full evidence in the dep-closure dossier gathered for this review.)

**Angle A — standalone adoption is realistic.** A consumer who supplies their own transport
(`connector_factory=` / `socket=` / `listener=`) *and* injects a `ticks=` source drops the
chumicro closure to **empty** for mqtt, websockets, and requests. The `sockets_factory` module
can be physically stripped from a deploy via `__chumicro_skip_factories__` (Decision 0062/0093),
and the library degrades gracefully — `from_config` lazily imports the factory and, if absent,
raises a `RuntimeError` naming the exact param to pass (`client.py:293-299`). The injection
seams already exist and are stable by design (0093:14-16).

**Angle B — port-into-chumicro is the path of least resistance.** The *ergonomic* entry
(`from_config`), which is what adopters reach for, pulls the full declared set (2–3 siblings).
Reaching the empty closure means the adopter re-implements the transport-factory contract
themselves — for requests/websockets a per-call `(host, port, use_tls) -> connector`; for mqtt
a zero-arg `() -> connector` — *plus* a ticks source. And "bring your own transport" is not a
thin shim: `chumicro_sockets` is a real cross-runtime (CP/MP/CPython) non-blocking TCP+TLS
connect state machine (Decision 0081). `chumicro_timing` is tiny but is the one sibling you
almost always inherit unless you deliberately inject ticks.

**For the DI decision:** the clean standalone seam already exists (`connector_factory` /
`socket` / `ticks` injection + skip-factories + a graceful `RuntimeError`). The two frictions
that currently nudge users toward porting rather than integrating are (1) the `ticks` fallback
*silently* pulls `chumicro_timing` unless injected, and (2) the three factory-kwarg spellings
across four libraries raise the cost of "just integrate one." A single documented DI recipe
("pass `connector_factory=<yours>` and `ticks=<yours>`; strip `sockets_factory` from the
deploy") would make empty-closure standalone adoption a first-class, discoverable path. Absent
that recipe, `from_config`'s 2–3-sibling closure is the default gravity well.

---

## 4. What consumers reveal about the libraries

**Capabilities the template hand-rolls that a library should own (several already grew the
capability; the template just predates it):**
- **"Block until wifi is up, or fail."** Reimplemented in 6 files. The library already has the
  `Signal` + `wait_for` primitive (`chumicro/demos/requests_fetch/app.py:29`) — a
  `wifi`-level convenience (or a documented one-liner) would delete the most-copied block in
  the template.
- **Periodic scheduling.** Hand-rolled per tick-object; `add_periodic` (`core.py:400`) owns it
  now — the examples teach the heavier `check`/`handle` object protocol for the common
  "do X every N ms" case.
- **Transport/connector construction + self-heal-on-drop.** The template's `_make_socket_factory`
  closures and their "self-heal" docstrings (telemetry_publisher:2-8) duplicate what
  `from_config(config, radio=…)` and the client's own reconnect backoff
  (`chumicro/libraries/mqtt/src/chumicro_mqtt/client.py:119`) now own.
- **"Run until told to stop."** example_sensor invents a `_SHUTDOWN_REQUESTED` global because
  there was no blessed entry/exit contract; `run_until(predicate)` (`core.py:630`) is that
  contract now.
- **Payload encoding.** JSON built by f-string with manual braces (example_sensor:90-94,
  telemetry_publisher:46) vs `json.dumps` in the demo — a `publish(..., json=…)` convenience
  could own encoding. Minor.

**API shapes that read awkwardly at the project level:**
- **Config access has no one idiom** — `require()` vs `get(default)` vs `["dotted"]` all appear;
  a reader can't tell which is "correct."
- **Factory-kwarg naming is inconsistent across siblings** — `connector_factory` /
  `socket_factory` / `listener_factory` / `socket=` (0093:38). It is defensible per-transport,
  but at the project level it reads as four names for one idea, and it is exactly where the
  template's mqtt examples broke.
- **The removed two-callable `add(check, handler)`** (`core.py:316-321`) leaves the
  object-with-`check`/`handle` as the only non-periodic registration shape; the template's many
  hand-rolled tick classes are evidence that for the common periodic case users want
  `add_periodic`, and the object protocol is the heavyweight fallback, not the default.

---

## Appendix: suggested template follow-ups (not applied — both repos read-only)

1. Migrate `projects/example_sensor/app.py` + `examples/telemetry_publisher/app.py` off
   `MQTTClient(socket_factory=…)` to `MQTTClient.from_config(config, radio=wifi.adapter.radio)`
   and delete `_make_socket_factory` (hard break — do first).
2. Replace `while True: runner.tick()` with `runner.run_until(...)` (or add `runner.wait(now)`)
   across all examples; replace hand-rolled tick objects with `add_periodic` where they are
   pure periodics.
3. README + skills: `install-libraries` → `library add`; `repl` deploy-follow → `deploy --tail`;
   drop `set-default`; document the clean-slate deploy default and its interaction with
   hand-installed board files.
4. Repoint `add-new-project` SKILL.md:42-44 at a working reference and off the
   `_SHUTDOWN_REQUESTED` pattern.
5. Add a documented "integrate one library standalone" recipe (connector_factory + ticks +
   skip-factories) to unblock the DI decision's standalone path.
