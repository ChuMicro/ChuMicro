# Workstream: Beginner On-Ramp UX

Status: `proposed` (2026-04-26) — captures the target user flow + library gaps surfaced during the post-Phase-7 audit.  Not yet sequenced; awaiting prioritization against `rename-to-chippy` and the deferred Phase 8 OTA work.

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

## Audit verdict (2026-04-26)

We are **not there yet**.  Concrete gaps, ordered by impact:

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
- The ChuMicro → ChipPy rename — separate workstream.
- A full mqtt-broker host fixture for a board-to-board MQTT demo — nice-to-have, defer until requested.
- Web UI on the host (for served pages) — out of scope; demo serves over plain HTTP and the user's browser hits the device directly.

## Library design notes

### `chumicro-requests` (HTTP client)

Inspirations: CPython `requests` (API shape only), MicroPython `urequests` (existence proof on constrained runtimes), our own `chumicro-mqtt` (non-blocking + check/handle pattern + budget control).

Hard requirements:

- **Non-blocking by default.**  An LED blinking on the runner must not stall when a request is in flight, when DNS is slow, when TLS handshake is dragging, or when the server is unreachable.  Mirror `chumicro-mqtt`'s `check(now_ms)` / `handle(now_ms)` runner integration.  Some operations *can't* be non-blocking (e.g., a single `recv()` on a TLS socket that's mid-handshake) — accept that, document it, keep those windows tight.
- **Built on `chumicro-sockets`.**  TLS is solved.  Don't reimplement.
- **Per-request budgets.**  Timeout in ms, max body size in bytes, max redirects.  Same `WhenOversized` policy enum shape as mqtt.
- **Pre-allocated buffers in hot paths.**  Library code on a 256 KB / 4 MB board.

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
- ~~Firmware-version-floor enforcement strictness~~ — resolved by [Decision 0039](../decisions/0039-firmware-version-floor.md): warn-not-block at registration, no hard error today.
- Two-thing demo with no second board: build a host-side server in `workbench/`, or assume the user has two boards?  Lean: host-side server — lower friction.
- Should `chumicro-requests` and `chumicro-http-server` get their own decision docs, or share one?  Lean: separate, since they have different design constraints (client buffering vs server lifecycle).

## Status log

- **2026-04-26** Step 1 shipped — Decision 0039 (firmware floor + warn-not-block policy), `chumicro_workspace.firmware_support` module (constants, `FirmwareSupportStatus` enum, `check_firmware_supported`, `explain`), `_cmd_add_device` wiring, `firmware_version` now persisted to `devices.yml` (probed-always slot was registered but unused before).  Workspace coverage 96 %.

## Cross-references

- `plans/workstreams/project-workspace.md` — the umbrella workstream this builds on.  Phases 1–7 shipped; this is post-Phase-7 polish + new libraries.
- `plans/next-up.md` — `discover` enhancement entry should fold into Step 3 here.
- `plans/decisions/0038-workspace-template-pivot.md` — the template-repo bootstrap shape this layers UX onto.
- `libraries/mqtt/` — reference implementation for non-blocking + check/handle + budgets in `chumicro-requests` and `chumicro-http-server`.
- `libraries/sockets/` — TLS + transport that both new libraries sit on top of.
- `workbench/workspace/src/chumicro_workspace/onboarding.py` — `BoardState` enum that classifies probe-time board condition; extend rather than re-invent.
- `workbench/workspace/src/chumicro_workspace/firmware_url.py` — `derive_firmware_url()` already maps board IDs to download URLs; the auto-upgrade flow plugs into this.
