# Workstream: Beginner On-Ramp UX

Status: **closed.**  Eight-step sequence shipped 2026-04-27 with Step 8.  The four follow-on beginner-onramp papercuts surfaced during the 2026-05-06 verification pass (F3 / F4 / F5 / F6) all shipped on 2026-05-06 in commits `8ecf728` / `f5539e9` / `3fde27c` / `224c489` respectively.  See **Findings from the 2026-05-06 review** below for per-finding detail.

## Purpose

A user who buys a random ESP32 online and clones the workspace template should reach a working, demoed-on-their-board state with one or two commands and minimal hand-holding — including the case where the board ships with old/wrong/no firmware.

The Phase 1–7 work shipped the *primitives* (probe, deploy, install-firmware, devices.yml, things/, mqtt+sockets+wifi end-to-end on real hardware).  This workstream bolts a beginner-grade UX over them and fills the two missing libraries (HTTP client, HTTP server) that the demo story needs to be interesting.

## Source: target user flow (verbatim user vision, 2026-04-26)

> 1. I buy an ESP32 online and plug it in. It has old MicroPython/CircuitPython, factory Arduino, or no firmware.
> 2. I clone the project workspace repo.
> 3. I go through an entry point.
> 4. I'm asked to set up devices if I want (or skip).
> 5. My device is discovered and added to config.
> 6. My device is found to be unsupported (wrong version or firmware — minimum MicroPython 1.27, CircuitPython 10.1.0).  Offer to upgrade.  If yes → fix the board.  If no → explain limits/risks.
> 7. Get everything else needed.
> 8. Offer to demo the example thing on their board so they can see how everything works (maybe a separate README step, not part of initial setup).
> 9. Example flashes an LED, or another deeper example runs HTTPS commands and connects to WiFi (pulling weather or something interesting).
> 10. Workspace is set up and ready.
> 11. User can make new things easily and deploy them.
> 12. If user only has one thing, deploy is simpler — they don't even have to provide a thing name.

## Findings from the 2026-05-06 review

The doc was written 2026-04-26 with status "proposed" + the audit verdict below ("we are not there yet").  All eight steps shipped between 2026-04-26 and 2026-04-27 (status log near the foot has the per-step detail).  Concrete state on disk now:

* **Step 1 — firmware floor.**  Decision 0039 (warn-not-block at registration) shipped; `chumicro_workspace.firmware_support` ships `MIN_MP_VERSION` / `MIN_CP_VERSION` constants + `FirmwareSupportStatus` enum + `check_firmware_supported` + `explain`; `firmware_version` now persists to `devices.yml` and `_cmd_add_device` warns on too-old.
* **Step 2 — single-thing deploy default.**  `_cmd_deploy` deploys the lone project when no positional given; zero / multiple → exit 2 with helpful message.
* **Step 3 — auto-runtime inference for `add-device`.**  `add-device --runtime` is optional now; `probe_with_runtime_inference` tries each candidate transport in order (`micropython`, `circuitpython`).
* **Step 4 — `chumicro-workspace bootstrap` wizard.**  Walks pick-port → probe → display-detected-runtime → firmware-floor-warn → pick-device-id → register → optional `--with-demo`.  Three flags (`--port`, `--device-id`, `--with-demo`) skip prompts for non-interactive use.
* **Step 5 — `chumicro-workspace demo`.**  Baked-in cross-runtime print-loop payload (`DEMO_PAYLOAD` constant) deploys to the active device + tails ~5s.  Stdlib-only so it works on any registered MP / CP board.
* **Step 6 — `chumicro-requests` library.**  Six slices (3a–3f) shipped end-to-end: plain HTTP GET → body decode → HTTPS → POST/PUT/PATCH/DELETE + JSON helper → redirects → chunked decode.  Live-board verified on Pi Pico W CP + MP.  Decision 0040 (chumicro-requests + factory helper pattern) is the design ADR.
* **Step 7 — `chumicro-http-server` library.**  Five slices (7a, 7b, 7d, 7t, 7-correction) shipped: scaffold + Decision 0041 + sockets `tcp_listening_socket` helper → routing decorator with `<param>` extraction → live-board verification across the four-board canonical matrix → TLS server investigation (works on MP rp2 + ESP32-S2 family on both runtimes; CP rp2 blocked at platform level).
* **Step 8 — two-thing demo + examples organization.**  `libraries/http_server/examples/circuitpython_two_thing_{server,sensor}.py` shipped — sensor POSTs sine-wave readings via `chumicro-requests` to a server displaying via `chumicro-http-server`.  Step 8's status log says: *"Step 8 closes out the beginner-onramp workstream's eight-step sequence."*

### Follow-on papercuts surfaced 2026-05-06 — all shipped same day

Four beginner-onramp papercuts surfaced during the verification pass that ran alongside the `config-shape-beginner-ergonomics` workstream.  They weren't part of the original eight steps — regressions / refinements caught only when a contributor walked the full clone-to-deploy path on real hardware with the post-config-shape changes in flight.  All four landed on 2026-05-06:

1. **Finding 3 — `add-device` firmware-version parser breaks on RC builds.**  Shipped in `8ecf728`.  Root cause was the probe stringifying `sys.implementation.version` as `'.'.join(str(p) for p in ...)` against CircuitPython RC's 4-tuple `(10, 2, 0, '')` — the empty release-level slot produced a `"10.2.0."` trailing dot, which `parse_version_tuple` rejected, surfacing as a "could not parse" warning + stripped-trailing-dot value in `devices.yml`.  Side effect: `requires_flash` floor checks silently disabled on every contributor running RC firmware.  Fix: walk the version tuple element-by-element, stop at the first non-int component before joining; same leading-int-run logic in `parse_version_tuple` so cached `devices.yml` entries from before the fix don't need migration.  Hardware-verified on Pi Pico W CP 10.2.0-rc.0.  Related to **Step 1** of this workstream (firmware floor).
2. **Finding 4 — `add-device` doesn't suggest IDs from probed `board_id`.**  Shipped in `f5539e9`.  Step 4's `bootstrap` wizard already derived a suggested id from the probed machine string; the standalone `add-device --address <port>` flow now reuses the same suggestion path when the positional id is omitted.  Related to **Steps 3 + 4** of this workstream.
3. **Finding 5 — `deploy <name>` should auto-detect boot-shim mode.**  Shipped in `3fde27c` (F5: simplify boot-shim — synthesise three-line code.py, drop multi-project layout).  When a project ships `app.py` with a `run()` callable, deploy auto-synthesises a three-line `code.py` (CP) / `main.py` (MP) entrypoint that calls `app.run()`, no flag required.  This was the highest-impact onramp papercut of the four — it eliminated the `ValueError: entrypoint '/code.py' not produced by directory walk` foot-gun every beginner was hitting.
4. **Finding 6 — mpremote orphan port-holders block subsequent deploys.**  Shipped in `224c489` (F6: surface the PID holding a serial port when deploy can't connect).  When the port-busy failure mode fires, deploy now reports the offending PID so the user can `kill <pid>` decisively.  Reframe during implementation: the original "kill them transparently" idea became "surface the PID with the error message" so the user retains agency over what to terminate.

### Reframe — what this workstream is now about

The original framing was *"deliver an eight-step on-ramp"*.  All eight steps shipped 2026-04-27.  Four follow-on papercuts shipped 2026-05-06.  Workstream is closed end-to-end.  The only items still loosely associated:

* **The two-thing-demo open question** about whether to ship a host-side server counterpart for users with only one board landed as "two CP boards" rather than "host-side server" (Step 8's `two_thing_server.py` is a CP server, not host).  If a user without two boards needs the demo to work, that's a follow-up not yet scoped — but it's an example-coverage item, not an onramp item.
* **Phase 8 OTA** remains explicitly out of scope here — tracked in [`ota.md`](ota.md).

A fresh agent picking this up should NOT re-do anything.  The body below is preserved for the design rationale (especially §"Library design notes" for `chumicro-requests` / `chumicro-http-server`, both now shipped under Decisions 0040 / 0041) and the verbatim user vision (§"Source") that drove the original framing.  This workstream is a candidate for archival the next time anyone passes through `plans/workstreams/`.

### Related decisions + workstreams

* [Decision 0039](../../decisions/0039-firmware-version-floor.md) — codified the firmware floor + warn-not-block policy this workstream proposed.
* [Decision 0040](../../decisions/0040-chumicro-requests.md) — `chumicro-requests` design (factory helper pattern).
* [Decision 0041](../../decisions/0041-chumicro-http-server.md) — `chumicro-http-server` design (runner-shaped non-blocking server).
* [`library-pipeline.md`](../library-pipeline.md) — references `chumicro-requests` + `chumicro-http-server` (both shipped) as Tier-A demo dependencies; future Tier B (input/pixels/tone) + `chumicro-presence` work would feed into the same beginner flow.
* [`archive/project-workspace.md`](project-workspace.md) — Phases 1–7 of the umbrella workstream this builds on (every phase complete).
* [`ota.md`](ota.md) — Phase 8 OTA, deferred from this workstream.

## Audit verdict (2026-04-26 — historical)

The original assessment that motivated the eight-step sequence.  Preserved as the "we are not there yet" framing the workstream solved; gaps 1–10 below all closed by Steps 1–8 except for the residual papercuts captured under "Follow-on papercuts" above.  Concrete gaps, ordered by impact:

1. **No firmware-version gate.**  `probe_device` returns a `version` string but nothing compares it to a minimum.  Threshold to codify: MicroPython ≥ 1.27, CircuitPython ≥ 10.1.0.  No code path warns on too-old, no path detects "wrong runtime entirely" (factory Arduino, blank chip).
2. **No automatic upgrade offer.**  `chumicro-workspace install-firmware` exists and works (UF2 + esptool, programmatic bootloader entry), but is never triggered by the workspace tool when a board fails a version check.  Users have to know to run it.
3. **No single-command on-ramp.**  Today the user sequences `discover` → `add-device --address … --runtime …` → maybe `install-firmware` → `deploy` → `repl`.  No `bootstrap` / `onboard` / wizard that does the chain.
4. **`discover` is read-only.**  Lists serial ports, doesn't auto-register.  The `add-device --auto` / `--from-port` enhancements are already on `next-up.md` as deferred — should be folded into this workstream.
5. **`deploy <name>` always requires a name.**  No "single thing → use it as default" affordance.
6. **No demo command / no LED-blink built into the workspace tool.**  Phase 7's `things/example_sensor/` lives in the external template repo and assumes a fully-set-up device.  No "see something work right now without setting up wifi" path.
7. **No HTTP client library.**  `chumicro-requests` does not exist.  Without it the "fetch weather over HTTPS" demo can't be written.
8. **No HTTP server library.**  `chumicro-http-server` does not exist.  Without it the "two-thing client + server demo" can't be written, and a host-side server fixture for the demo to talk to also doesn't exist.
9. **No two-thing example.**  The template repo carries `example_sensor` (single-board MQTT publisher).  Nothing demos board-to-board or board-to-host.
10. **No `examples/` folder convention in the template repo.**  Single-thing layout is fine for one example, but adding multiple curated demos needs a place to put them — alongside `things/` or under `things/_examples/`?  Open.

## Scope

**In scope:**

- A `chumicro-workspace bootstrap` (or equivalent — name TBD) interactive entry point that chains discovery → version-check → optional upgrade → first-deploy → REPL.
- Firmware-version validation: codify MP ≥ 1.27 / CP ≥ 10.1.0 floors as constants in `chumicro_workspace`, expose via `--check-firmware` and integrate into the bootstrap flow.
- "Wrong runtime / blank chip / factory Arduino" classification at probe time so we can give a useful message instead of a cryptic timeout.  `BoardState` enum already exists in `onboarding.py`; extend it.
- Single-thing deploy default: when `things/` has exactly one entry, `chumicro-workspace deploy` (no positional) deploys it.
- Folding `discover` enhancement (next-up.md item — option (c) `add-device --from-port <port>` minimum, ideally option (a) `add-device --auto` interactive sweep) into this workstream.
- New library: **`chumicro-requests`** — non-blocking HTTP/HTTPS client on top of `chumicro-sockets`.  Mirrors the runner-shaped `check`/`handle` pattern from `chumicro-mqtt`.  Goal: an LED can keep blinking while a request is in flight, even on timeout / bad connection scenarios.  See "Library design notes" below.
- New library: **`chumicro-http-server`** — non-blocking HTTP/1.1 server, same shape.  Subset: routing, query string parsing, JSON body, headers.  No sessions, no auth, no WebSockets in v1.
- A "two-thing" example pair in the template repo: a sensor that POSTs readings and a server that displays them.  Optionally a host-side counterpart so the demo runs without a second board.
- Demo / first-run command: `chumicro-workspace demo` runs a tiny LED-blink thing on the active device (no wifi, no setup beyond add-device).  Separate from the deeper "fetch weather" demo which assumes wifi credentials.

**Out of scope (this workstream):**

- Phase 8 OTA (`chumicro-update`) — separate, deferred.
- A full mqtt-broker host fixture for a board-to-board MQTT demo — nice-to-have, defer until requested.
- Web UI on the host (for served pages) — out of scope; demo serves over plain HTTP and the user's browser hits the device directly.

## Library design notes

### `chumicro-requests` (HTTP client)

Inspirations: CPython `requests` (API shape only), MicroPython `urequests` (existence proof on constrained runtimes), our own `chumicro-mqtt` (non-blocking + check/handle pattern + budget control).

Hard requirements:

- **Non-blocking by default.**  An LED blinking on the runner must not stall when a request is in flight, when DNS is slow, when TLS handshake is dragging, or when the server is unreachable.  Mirror `chumicro-mqtt`'s `check(now_ms)` / `handle(now_ms)` runner integration.  Some operations *can't* be non-blocking (e.g., a single `recv()` on a TLS socket that's mid-handshake) — accept that, document it, keep those windows tight.
- **Built on `chumicro-sockets`.**  TLS is solved.  Don't reimplement.
- **Per-request budgets.**  Timeout in ms, max body size in bytes, max redirects.  Same `WhenOversized` policy enum shape as mqtt.
- **Pre-allocated buffers in hot paths.**  Library code on a 256 KB / 2 MB-flash (~800 KB usable) board.

API sketch (subject to revision when implementation starts):

```python
from chumicro_requests import HttpClient, Request

client = HttpClient(sockets_factory=...)
request = client.get("https://api.example.com/weather", timeout_ms=5000)

# Runner integration:
while not request.done:
    runner.tick(monotonic_ms())

response = request.result  # raises on error
print(response.status_code, response.json())
```

Open questions deferred to implementation:

- Body streaming vs full-buffer.  Probably full-buffer in v1 with a configurable cap; streaming via callback in v2 if asked for.
- Header dict shape — case-insensitive mapping like CPython, or simple list-of-tuples?  Lean: case-insensitive, but pre-allocated.
- Connection reuse / keep-alive.  Lean: not in v1; one socket per request.  Adds quite a bit of state.
- gzip decode.  Lean: no in v1; require `Accept-Encoding: identity` from servers we control.

### `chumicro-http-server` (HTTP server)

Inspirations: `microdot`, `tinyweb`, BaseHTTPServer (API shape only).

Hard requirements:

- Same non-blocking + check/handle integration.
- Single port, multiple in-flight connections OK but bounded.
- Simple decorator-based routing: `@app.route("/sensor", methods=["GET", "POST"])`.
- Built on `chumicro-sockets`.

v1 surface:

- GET / POST routes; query-string parsing; JSON body; arbitrary headers.
- Static file from filesystem (small, blocking-acceptable case).

v1 non-goals:

- Sessions, cookies, auth.
- WebSockets, SSE.
- TLS (clients hit it over plain HTTP for v1 demos; revisit when there's a real privacy use case on a LAN board).

## Sequencing

Proposed ordering — each step is small enough to ship in one or two sessions:

1. **Codify the firmware floor.**  Add `MIN_MP_VERSION = "1.27"`, `MIN_CP_VERSION = "10.1.0"` constants in `chumicro_workspace`.  Add a `check_firmware_supported(probe_result) -> SupportStatus` function returning `SUPPORTED | OLD | WRONG_RUNTIME | UNKNOWN`.  Integrate into `add-device` and `deploy` as a warning.  No new commands, no UX surgery — just stops silent breakage.
2. **`chumicro-workspace deploy` defaults to the lone thing.**  Tiny CLI change.  When `things/` has exactly one subdir and no positional argument given, deploy that one.
3. **Auto-register from `discover`.**  Implement option (c) from the existing next-up entry: `add-device --from-port <port>` infers runtime from probe; `discover --register` does the full sweep.
4. **`chumicro-workspace bootstrap`.**  Interactive wizard that chains discover → register → version check → optional install-firmware → deploy a built-in LED-blink "demo thing" → tail.  Calls existing primitives — no new transport, no new flashing, just a glue command.
5. **`chumicro-workspace demo`.**  Subcommand that ships a baked-in LED-blink thing payload (no wifi) and deploys it to the active device.  Source lives in `chumicro_workspace/demo_things/blink.py` or similar.
6. **`chumicro-requests` library.**  New library under `libraries/requests/`.  Phase its own internal stages: GET-only over plain HTTP, GET over HTTPS (reuse sockets TLS), POST + bodies, redirects, full runner integration.  Add a "fetch weather" demo as a thing in the template repo once it's working.
7. **`chumicro-http-server` library.**  New library under `libraries/http_server/`.  Routing + GET/POST + JSON.  Add a "two-thing" demo: sensor publishes via `chumicro-requests`, server displays via `chumicro-http-server`.  Optional: a host-side counterpart in `workbench/` so the demo runs without two boards.
8. **Examples organization.**  Decide where multi-thing demos live in the template repo (`things/_examples/<name>/`?  separate `examples/` tree?).  Document.

Steps 1–5 are the on-ramp UX work.  Steps 6–8 are the new-libraries + richer-demos work — they extend the on-ramp story but are independently valuable.

Reasonable to do steps 1+2 immediately as a small, self-contained slice.  Step 3 has design choices (interactive prompts vs flags) worth a quick sync.  Steps 4–8 each warrant their own session.

## Open questions

- Bootstrap command name: `bootstrap`?  `onboard`?  `setup` (already taken — does `pip install -e .`)?  `start`?  `init` is taken.
- Demo thing: ship inside `chumicro-workspace` as data, or as a thing in the template repo that `bootstrap` deploys?  Lean: inside the tool, so it works pre-template-customization.
- ~~Firmware-version-floor enforcement strictness~~ — resolved by [Decision 0039](../../decisions/0039-firmware-version-floor.md): warn-not-block at registration, no hard error today.
- Two-thing demo with no second board: build a host-side server in `workbench/`, or assume the user has two boards?  Lean: host-side server — lower friction.
- Should `chumicro-requests` and `chumicro-http-server` get their own decision docs, or share one?  Lean: separate, since they have different design constraints (client buffering vs server lifecycle).

## Status log

- **2026-04-26** Step 1 shipped — Decision 0039 (firmware floor + warn-not-block policy), `chumicro_workspace.firmware_support` module (constants, `FirmwareSupportStatus` enum, `check_firmware_supported`, `explain`), `_cmd_add_device` wiring, `firmware_version` now persisted to `devices.yml` (probed-always slot was registered but unused before).  Workspace coverage 96 %.
- **2026-04-26** Step 2 shipped — `_cmd_deploy` defaults to the lone thing in the workspace when no positional is given.  Zero things → exit 2 with "create one with `new <name>` first".  Multiple things → exit 2 with the list.  Underscore-prefixed dirs (e.g. `things/_template/`) are filtered out by `WorkspaceLayout.list_things()`, so a fresh template-only workspace correctly reports zero things.  `nargs="+"` → `nargs="*"`.  Five new tests under `TestDeploySingleThingDefault`.  Workspace coverage 96 %.
- **2026-04-26** Step 3 shipped — `add-device --runtime` is now optional.  When omitted, `chumicro_workspace.onboarding.probe_with_runtime_inference` tries each candidate transport (default order: `("micropython", "circuitpython")`) and uses the first one whose probe returns a marker.  Truthful runtime comes from `info.implementation.name`, not the transport candidate (so an MP transport probing a CP board still registers as CP).  Both transports speak the same `sys.implementation` probe script, so the inference is robust.  New `RuntimeInferenceResult` dataclass + helper.  10 new tests under `TestProbeWithRuntimeInference` (onboarding) + `TestAddDeviceRuntimeInference` (CLI).  Workspace coverage 96 %.
- **2026-04-26** Step 5 shipped — `chumicro-workspace demo` deploys a baked-in cross-runtime print-loop payload (`DEMO_PAYLOAD` constant in `cli.py`) to the active device and synchronously surfaces its output.  Runtime-agnostic — only stdlib `import time` so the demo "just works" on any registered MP / CP board without picking a board-specific LED pin.  ~5 second wall-clock.  Same failure-surfacing shape as `deploy` (traceback in execute output → exit 1).  4 new tests under `TestDemo` plus expansion of the parser-registration EXPECTED_COMMANDS list.  An LED-blink variant is a future enhancement once the workspace lands a cross-runtime LED-pin abstraction; tracked in the workstream's open questions.
- **2026-04-27** Step 8 shipped — two-thing demo example pair in `libraries/http_server/examples/`.  `circuitpython_two_thing_server.py` runs the display side: `chumicro-http-server` with `GET /` (HTML status page), `GET /api/latest` (JSON), `POST /api/sensor` (JSON ingest) routes, in-memory latest-reading state.  `circuitpython_two_thing_sensor.py` runs the sensor side: `chumicro-requests`'s runner-shaped `HttpClient.post` posting a synthetic sine-wave reading to the server every 5 s.  Both files are runner-shaped — wifi check + http check + sleep loops cooperate so an LED can keep blinking.  Hardware-prefixed filenames (per Decision 0013) mark them as CP/MP-only — verify-examples skips the import-resolution check for `wifi` / `socketpool` modules that don't exist on host CPython.  Documented in the http_server README + guide; the guide includes a "Running the two-thing demo" section that explains the SSID/password/SERVER_HOST setup steps.  Step 8 closes out the beginner-onramp workstream's eight-step sequence.
- **2026-04-27** Step 7 slice 7d shipped — live-board HTTP server verification across the four-board canonical matrix.  All four boards run plain HTTP server end-to-end (3/3 routes verified per board: GET `/`, GET `/api/widgets/<id>` with path-param extraction, POST `/sensor` with JSON request + JSON response).  HTTPS combined with the slice 7t investigation gives a 3/4 grid: Pi Pico W MP (25 KB handshake heap), Lolin S2 ESP32-S2 MP (**1 KB** handshake heap — HW crypto acceleration), Lolin S2 ESP32-S2 CP (35 KB handshake heap) all work.  Only Pi Pico W CP remains blocked by the rp2-port post-handshake `OSError(32)` (EPIPE) issue documented in slice 7t.  `.scratch/run_http_server_acceptance.py` is the host-driven runner.  Verified live measurements: HTTP server uses ~4 KB heap per request on rp2-MP (139 KB → 135 KB across 3 requests + sustained server loop).
- **2026-04-27** Step 7 slice 7b shipped — `chumicro-http-server` routing.  `@server.route(path, *, methods=("GET",))` decorator + two-dict router (tinyweb pattern from Decision 0041 §3): `_explicit_routes: dict[(method, path), handler]` for `O(1)` exact matches; `_pattern_routes: list[(method, prefix, param_name, handler)]` for `/widgets/<id>`-shape routes (single trailing parameter; multi-param deferred to v2).  `Request.path_params` populated during dispatch.  Method handling: 404 for unrouted paths; 405 with `Allow:` header (RFC 7231 §6.5.5) for matched paths with unregistered methods; case-insensitive method matching.  Re-registration is last-wins.  Optional `handler=` constructor param remains as catch-all fallback (the slice-7a single-handler shape is a strict subset of the new routing API).  HttpServer's `_dispatch_request` is the single dispatch entry point routed through `_Connection`'s handler hook.  14 new `TestHttpServerRouting` cases (decorator registration, default-method-is-GET, multi-method, path-param extraction, query-with-path-param, 404-on-unrouted, 405-with-Allow on explicit + pattern routes, fallback-handler-routing, fallback-precedence, re-registration on explicit + pattern, lowercase-method-normalization).  Source grew ~150 lines.  95 % combined coverage; preflight green.
- **2026-04-27** Step 7 slice 7t correction — CP TLS server **does** work, on ESP32-S2 (and likely S3); my prior "blocked at platform level" claim was wrong.  User correctly pointed at adafruit_httpserver's working `https=True` path, and the breakthrough was the `ssl.create_default_context()` + `load_verify_locations(cadata="")` + `load_cert_chain(cert_path, key_path)` + `wrap_socket(server_side=True)` recipe.  CP gotcha: `load_cert_chain` requires *filesystem paths*, not in-memory bytes (raises `OSError(2)` on bytes).  New `chumicro_sockets.ssl_context_with_cert_and_key_paths(cert_path, key_path)` cross-runtime helper handles this — CP uses paths directly, MP+CPython read the files and route through the existing in-memory helper.  Live measurements on Lolin S2 ESP32-S2 / CP 10.2.0-rc.0: 6 KB context + 35 KB handshake heap cost; 1.99 MB free heap remaining; HTTPS GET round-trip from a host CPython client succeeded.  Pi Pico W rp2 / CP currently fails post-handshake with `OSError(32)` (EPIPE) — heap was 115 KB free at the failure, so not a memory issue; likely an rp2-port mbedTLS feature-flag difference vs ESP-IDF.  Filed as a follow-up; ESP32-family is the recommended CP HTTPS-server platform today.  Decision 0041 §8 + `plans/learnings.md` rewritten to correct the prior "CP can't host TLS server" framing.  2 new tests for the path-based helper (CPython real-cert load + CP routing).
- **2026-04-26** Step 7 slice 7t shipped — TLS server investigation on Pi Pico W (`chumicro-sockets` 0.1.7).  Adafruit's "limited to ESP32-S3 class" framing on `httpserver`'s `https=True` was too pessimistic for the MicroPython side; verified live that **Pi Pico W MicroPython 1.28.0 fits a TLS server** with 8 KB SSLContext + 25 KB handshake heap cost (130 KB free heap remaining).  Conditions: RSA-2048 cert + key in DER encoding (rp2's mbedTLS rejects ECC server keys with `invalid key`; PEM keys hit the same `MBEDTLS_PEM_PARSE_C`-disabled wall the CA-load path did).  CircuitPython 10.2.0-rc.0 is **not supported** — CP's `ssl` module deliberately omits `PROTOCOL_TLS_SERVER` (verified live: `dir(ssl)` exposes no `PROTOCOL_*` constants whatsoever; CP's `SSLContext()` is hard-wired client-side).  This is a CP-platform decision, not a heap constraint.  `chumicro-sockets` 0.1.7 ships `tls_listening_socket(host, port, *, context, backlog, radio)` + `ssl_context_with_cert_and_key(cert_pem, key_pem)` per-runtime helpers; CP adapter raises `UnsupportedSSLConfigError` with a clear explanation rather than the bare `AttributeError`.  Decision 0041 §8 rewritten with the verified outcome (was: "TLS server doesn't fit"; is now: "MP works, CP blocked at platform level"); `docs/guide.md` TLS section updated with the runtime-conditional pattern + `max_connections=1` recommendation; two new `plans/learnings.md` entries (CP `ssl` omits server protocols / MP TLS server fits + RSA-DER constraint).  4 new sockets routing tests (TLS listener routing on CP / MP / CPython + `ssl_context_with_cert_and_key` routing) + 2 cert-builder tests + 1 real CPython TLS handshake round-trip test.  97 % sockets coverage; preflight green.  `.scratch/run_tls_server_probe.py` is the live-board verification path.
- **2026-04-26** Step 7 slice 7a shipped — `chumicro-http-server` scaffold + Decision 0041 + `chumicro-sockets` 0.1.6 listener helper.  Decision 0041 captures the runner-shaped server design after a survey of the established MP/CP HTTP server libraries (microdot, tinyweb, picoweb, adafruit_httpserver) — all sync-blocking or asyncio-bound, none cooperative.  Genuine gap to fill.  Patterns lifted from prior art: tinyweb's two-dict router (slice 7b), per-tick budgets (Decision 0041 §4), bounded in-flight connection count.  Patterns rejected: per-connection task spawning, asyncio dependency, blocking accept, `bytes += slice` accumulation.  Reuses `chumicro_requests.CaseInsensitiveDict` / `parse_charset` / exception hierarchy — same wire format on both sides; documented (§5) as the `http_server → requests` dependency direction with extraction-to-`chumicro-http` deferred until a third consumer surfaces.  `chumicro-sockets` 0.1.6 adds `tcp_listening_socket(host, port, *, backlog, radio)` + per-runtime `listen_tcp` adapters (CP socketpool, MP socket, CPython stdlib).  Slice 7a implementation: `RequestParser` (request line + headers + Content-Length body), `HttpServer` runner-shaped with single user-provided handler, per-`_Connection` state machine (`WANT_REQUEST_LINE → WANT_HEADERS → WANT_BODY → DISPATCHING → WANT_SEND_HEADERS → WANT_SEND_BODY → DONE/ERROR`), `Request` / `Response` value objects, `build_response()` helper with text/html/json/body shortcuts, `encode_response()` writer.  74 tests at 95 % combined coverage; preflight green.  Source footprint: 4 files / ~1230 raw lines / ~45 KB device-shipped.  Slices 7b (routing decorator), 7c (bounded multi-conn), 7d (live-board verification), 7t (TLS server attempt) follow.
- **2026-04-26** Step 6 slice 3f shipped — `chumicro-requests` `Transfer-Encoding: chunked` decode.  Three new parser states (`CHUNK_SIZE`, `CHUNK_DATA`, `CHUNK_TRAILER`) extending the existing `STATUS → HEADERS → BODY → DONE` machine.  Detects chunked via the `Transfer-Encoding` header in `_enter_body_state`; takes precedence over `Content-Length` per RFC 7230 §3.3.3.  Chunk-extensions on the size line (`5;name=value\r\n`) are accepted and ignored; trailer headers between last-chunk and final empty CRLF are discarded.  Other `Transfer-Encoding` codings (`gzip`, `deflate`) rejected with `HttpProtocolError` rather than silently producing garbled bytes.  Chunk-size hex is enforced against `max_body_bytes` cap so a malicious server can't trickle past the limit.  EOF mid-chunk fails with `HttpProtocolError("peer closed mid-chunked-body")` — chunked encoding is self-terminating.  14 new tests under `TestResponseParserChunked` (single / multi / empty / drip-fed-byte-by-byte / chunk-extension / trailers / TE-precedence-over-CL / unsupported-TE-rejected / non-hex / empty-size / missing-CRLF-after-data / oversized / EOF-mid-data / TE-with-whitespace).  166 tests total at 97 % combined coverage; cross-runtime tests pass on MP + CP unix ports; preflight green.  Source grew ~150 lines / ~6 KB.  v1 of `chumicro-requests` complete.
- **2026-04-26** Step 6 slice 3e shipped — `chumicro-requests` redirect following.  301 / 302 / 303 / 307 / 308 followed automatically up to a per-request budget (default 5 from Decision 0040; overridable via `max_redirects=` per-call or `default_max_redirects=` per-client; `max_redirects=0` returns the 3xx as-is).  301/302/303 switch the next hop to GET-no-body; 307/308 preserve the original method + body (replay buffered at request start).  `Location` resolution handles absolute / absolute-path / path-relative shapes via new `resolve_redirect_url()` helper in `_wire.py` (publicly exported).  Refactored `_start_request` into `_start_request` (per-request setup: deadline, budget, original-request capture) + `_start_hop` (per-hop setup: encode + open socket + transition).  New `_close_socket_only()` keeps handle/deadline/budget intact between hops.  19 new tests across `TestResolveRedirectURL` (7 cases) + `TestHttpClientRedirects` (12 cases — 301/302/303/307/308 dispatch, max_redirects=0 / within-budget / over-budget, missing-Location-terminal, invalid-Location, per-call-override, factory-failure-during-redirect).  152 tests total at 97 % combined coverage; preflight green.  Source grew ~210 lines / ~9 KB.
- **2026-04-26** Step 6 slice 3d shipped — `chumicro-requests` POST + PUT + PATCH + DELETE + JSON helper.  `client.post(url, *, body=bytes|str, json=obj, headers=..., timeout_ms=...)` plus `put` / `patch` (same body/json semantics) and `delete` (no body in v1).  `body=` accepts `bytes` / `bytearray` / `str` (UTF-8 encoded); `json=` auto-encodes via `json.dumps` and sets `Content-Type: application/json` unless caller overrides.  `body=` and `json=` mutually exclusive (ValueError).  New private `_merge_default_header` helper handles the override-or-default logic for Content-Type.  Refactored `_start_request` to accept `body` + `json_body` kwargs and route through `encode_request`'s body path.  16 new tests across `TestHttpClientPost` (12 cases) + `TestMergeDefaultHeader` (4 cases).  133 tests total at 98 % combined coverage on the requests library; preflight green.  Source grew ~140 lines / ~5 KB.
- **2026-04-26** Step 6 slice 3c shipped — `chumicro-requests` HTTPS support + live-board verification on Pi Pico W CP + MP.  Lifted the `NotImplementedError` on `https://` URLs; the existing `chumicro_sockets_factory(ssl_context=...)` path Just Works once the underlying TLS stack does.  Live verification (`https://example.com/`, `CERT_REQUIRED` with a 3-cert CA chain bundle) returned status 200 + 540 body bytes on both boards.  Three live-only bugs surfaced + fixed during the slice: (1) CP 10.x's `bytearray` rejects `del buffer[:n]`; reassigned to `bytearray(buffer[n:])` (cross-runtime safe).  (2) MP's `bytearray` lacks `.clear()`; reassigned to `bytearray()`.  (3) `chumicro-sockets._adapters.mp._MpSocketWrapper.recv_into` was conflating "no data this tick" (`SSLSocket.recv()` returns `None`) with "clean peer close" (returns `b""`) — both became `0`.  Wrapper now raises `OSError(11)` (EAGAIN) on `None`, restoring the standard contract.  This is a `chumicro-sockets` 0.1.5 bump shipping alongside slice 3c.  Three live-board limitations documented in `docs/guide.md` + Decision 0040: HTTPS requires `--deploy-mode flash` on Pi Pico W (RAM-mode leaves < 50 KB heap for mbedTLS handshake → `OSError(12)`); SSL context must be CA-pinned (`ssl.create_default_context()` doesn't fit); RTC must be NTP-synced before TLS (boot RTC at 2021-01-01 → "cert validity starts in future" failure).  Three new learnings entries in `plans/learnings.md`.  117 host tests at 96 % combined coverage; preflight green at 94 % gate.  `.scratch/run_requests_acceptance.py` host-driven runner is the four-board live-verification path (gitignored alongside the wifi/sockets runners).
- **2026-04-26** Step 6 slice 3b shipped — `chumicro-requests` body decode.  `Response.encoding` (sniffed from Content-Type charset, default utf-8, settable for server-lies cases), `Response.text` (decodes via `bytes.decode(encoding)`, propagates `UnicodeDecodeError`), `Response.json()` (decodes through `.text` first then `json.loads`, propagates `ValueError`/`json.JSONDecodeError`); `parse_charset(content_type)` helper in `_wire.py` exposed publicly.  Constructor gained `encoding=` slot for manual overrides via the response builder.  15 new tests across `TestParseCharset` (8 cases — None/empty/explicit/quoted/uppercase/no-charset/multi-param/blank) + `TestResponseDecode` (7 cases — utf-8 default / charset header / constructor override / setter override / json round-trip / json invalid / decode-error).  115 tests total at 97 % combined coverage; preflight green.  Source grew by ~150 lines (~7 KB) across `_wire.py` + `client.py`.
- **2026-04-26** Step 6 slice 3a shipped — `chumicro-requests` library scaffolded (Decision 0040 accepted).  Plain HTTP GET against a fake transport: streaming response parser (`STATUS → HEADERS → BODY → DONE` state machine), case-insensitive header dict with multi-value join (RFC 7230 §3.2.2), runner-shaped `HttpClient` (`check(now_ms)` / `handle(now_ms)`), single-in-flight with `HttpBusyError` mirroring `MQTTBackpressureError`, per-request `timeout_ms` deadlines, `recv_budget_per_tick=1024` matching mqtt's tick-friendly default, three `WhenOversized` policies (drop-silent / drop-with-event / disconnect), `chumicro_sockets_factory()` convenience helper that lazy-imports the transport, `FakeHttpClient` host-only test fake for downstream consumers (excluded from device bundle by name).  100 tests at 96% combined coverage (`__init__.py` 100% / `_wire.py` 97% / `client.py` 96% / `testing.py` 100%); preflight green at 94% gate.  Source footprint: 3 device-shipped files / 1,303 lines / 46 KB — ~70% of `chumicro-mqtt`'s size for a comparable runner shape.  Slices 3b–3f (body decode → HTTPS → POST/JSON → redirects → chunked decode) sequenced for follow-on sessions.  Decision 0040 §1 single-in-flight is the load-bearing simplification — multi-in-flight + a queued pool can wait for a real consumer who needs it.
- **2026-04-26** Step 4 shipped — `chumicro-workspace bootstrap` integration command.  Walks the user through pick-port → probe (auto-runtime-inference) → display-detected-runtime → firmware-floor-warn → pick-device-id → register → optional `--with-demo`.  Three flags (`--port`, `--device-id`, `--with-demo`) skip the corresponding prompt — passing all three runs end-to-end non-interactively for testability.  Single port detected → silent auto-pick; multiple ports → numbered list + `prompt_func`.  Device id default suggestion is derived from the probed machine string (CP "Raspberry Pi Pico W with rp2040" → `raspberry-pi-pico-w`).  Reuses Steps 1-3+5 helpers — no second probe, no policy duplication.  16 new tests across `TestBootstrapHelpers` (10 cases: id-suggestion variants, port-resolution variants) + `TestBootstrapWizard` (5 cases: full-flow, inference-failure, old-firmware-warn, duplicate-id, with-demo-chain).  Workspace coverage 96 %.

## Cross-references

- `plans/workstreams/archive/project-workspace.md` — the umbrella workstream this builds on.  Phases 1–7 shipped; this is post-Phase-7 polish + new libraries.
- `plans/next-up.md` — `discover` enhancement entry should fold into Step 3 here.
- `plans/decisions/0038-workspace-template-pivot.md` — the template-repo bootstrap shape this layers UX onto.
- `libraries/mqtt/` — reference implementation for non-blocking + check/handle + budgets in `chumicro-requests` and `chumicro-http-server`.
- `libraries/sockets/` — TLS + transport that both new libraries sit on top of.
- `workbench/workspace/src/chumicro_workspace/onboarding.py` — `BoardState` enum that classifies probe-time board condition; extend rather than re-invent.
- `workbench/workspace/src/chumicro_workspace/firmware_url.py` — `derive_firmware_url()` already maps board IDs to download URLs; the auto-upgrade flow plugs into this.
