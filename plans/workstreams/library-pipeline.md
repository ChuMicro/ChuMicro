# Library pipeline — what to add next

**Status:** captured, no implementation yet. Awaiting batch selection and a dependency-policy decision.

**Origin:** strategy conversation 2026-04-27. Survey of the Adafruit bundle + micropython-lib + existing chumicro libraries to identify cross-runtime gaps worth filling. Folds in and widens the **LED / UX hooks for service state** open question from `plans/workstreams/archive/phase-7-integration.md` §"LED / UX hooks for service state".

## Context

Eleven libraries have shipped (`compat`, `config`, `http_server` (in flight), `kvstore`, `mqtt`, `msgpack`, `requests` (in flight), `runner`, `sockets`, `timing`, `wifi`).  Hardware on hand for validation:

- 4-device CPU matrix (CP + MP-ESP32 + MP-RP2 + CPython sim) — the bare minimum, always available
- Adafruit MACROPAD RP2040 (12 keys + 12 NeoPixels + SH1106 OLED + rotary encoder + speaker) — pluggable
- LoRa (RFM89x) chips on Pi Pico + Adafruit Feather — chips present, **antennas not yet**
- Lilygo boards with onboard GPS — **no CircuitPython port**, MicroPython only
- Stepper drivers — not yet wired

The pipeline below is shaped by what we can validate **today on bare CPUs** versus what needs a board on the bench.

## Tiers

### Tier A — bare 4-device CPU matrix, no extra hardware

| Library | Sketch | Why |
|---|---|---|
| **chumicro-logging** | Tiny levelled logger with a handler protocol; runner-friendly buffered handler; CPython stdlib `logging` as fake / passthrough. **Must NOT become a required dep of other chumicro libraries** — they accept an optional `logger` callable, default no-op. | Universal need.  CP `adafruit_logging` is minimal, MP `logging` is quirky, stdlib is overkill — chumicro can pick a small subset and unify. |
| **chumicro-ntp** | Non-blocking SNTP client on top of chumicro-sockets; emits a tick offset that timing helpers can consume. | High-leverage, ~150 lines. **First check whether chumicro-sockets exposes UDP** — Decision 0031 made it TCP+TLS-focused.  May need a small UDP add as a prereq slice. |
| **chumicro-events** | Runner-shaped pub/sub: `bus.publish("wifi.connected", payload)`, `bus.subscribe(topic, handler)`. Topic strings, not classes.  Bounded queue, drops oldest with a count.  **Must NOT become a required dep of other chumicro libraries** — services keep their existing direct callbacks; events sits beside them as an optional aggregator the *thing* opts into.  See "Device-feedback layer" below for the use case driving this. | Several services already publish state changes via ad-hoc callbacks (wifi → indicator, mqtt → app). A bus would cut boilerplate **for the consumer**, not the producer.  Risk: premature abstraction if no aggregator emerges — the device-feedback layer is the third consumer that justifies it. |

### Tier B — plug in the macropad to validate; libraries are board-agnostic

These cover the cross-runtime gaps the macropad happens to exercise simultaneously, but the libraries are not macropad-specific.  All use constructor-injected backends so a single button / Pi Pico breadboard / NeoPixel strip / Feather all work.

Macropad fact sheet (RP2040 + 8 MB QSPI):

| Subsystem | Hardware | CP support | MP support |
|---|---|---|---|
| 12 keys (3×4) | Cherry-MX, one GPIO each | `keypad.Keys` (built-in) | none — `machine.Pin` IRQ + debounce |
| 12 RGB LEDs | WS2812B chain | `neopixel` (built-in) | `neopixel` / `rp2.PIO` |
| 128×64 mono OLED | SH1106 | `adafruit_displayio_sh1106` | `ssd1306`/`sh1106` MP drivers |
| Rotary encoder | Quadrature + push button | `rotaryio` (built-in) | hand-rolled IRQ pair |
| Piezo speaker | One PWM pin | `pwmio` | `machine.PWM` |

| Library | Sketch |
|---|---|
| **chumicro-input** | Runner-shaped service over a constructor-injected pin/keymatrix backend.  Emits `press / release / long_press / repeat / chord` events plus a quadrature-encoder helper with optional acceleration.  Backends: `keypad.Keys` (CP), `machine.Pin`+IRQ (MP), CPython fake driving events from a script. |
| **chumicro-pixels** | Runner-shaped LED patterns: `Solid`, `Blink`, `Pulse`, `Fade`, `Chase`, `Flash`. Constructor-injected strip backend (CP `neopixel.NeoPixel`, MP `neopixel.NeoPixel`, single PWM pin, no-op).  Each pattern is a tick-driven generator; service composites them onto the strip. |
| **chumicro-tone** *(optional)* | Non-blocking tone scheduler: `tone.beep(440, 50)` queues a tick-driven pulse train; backends are PWM (CP `pwmio`, MP `machine.PWM`), no-op.  Small (~80 lines).  Gravy. |

### Tier C — defer until hardware is on the bench

- **chumicro-lora** (RFM89x) — wait for antennas; SPI-radio code without on-air verification is a debugging trap.
- **chumicro-gps** — NMEA parser is host-testable from logs; parser without a real fix to validate is dead code.  Wait until Lilygo or a NEO-6M breakout is wired.  Note: **MicroPython-only** if it lives on a Lilygo board.
- **chumicro-stepper** — needs an actual driver IC (A4988 / DRV8825 / TMC2209) wired up.
- **chumicro-display** — too much surface area, no clear MVP.  Existing per-runtime drivers + raw `displayio` / `framebuf` are good enough until widget ambitions materialize.
- **chumicro-mdns** — useful follow-up to http-server.  Defer until the first project asks for service discovery.
- **chumicro-ble** — large; runtime support is uneven (CP `_bleio` vs MP `bluetooth`).  Defer until a clear use case appears.

## Device-feedback layer (widened from StatusIndicator HAL)

The "thing wants to tell its operator something" problem is bigger than a status LED.  Same shape, multiple modalities:

- **System indicator LED.**  WiFi connecting → blue pulse.  Connected → solid green.  MQTT broker down (but wifi up) → amber blink.  Unhandled error → red flash.
- **Multi-purpose physical button.**  Short press: send status update over MQTT.  Double press: wake LCD / cycle screen.  Long press: drop into USB-storage mode.  Hold-on-boot: factory reset.  The *behavior* is the user's policy — the *button* is generic.
- **System status LCD.**  Top-row glyph for connectivity, body for current task, bottom-row for last error / heartbeat.  Same display the application uses for its own UI, but with a system-status overlay regime.
- **Audible feedback** (optional, via tone): startup chime, error chirp, button click.

These all share a contract: they consume state-change events from networking / storage / app code, and they produce an output the operator can perceive.  The contract is the value — the individual hardware drivers (`pixels`, `input`, `tone`, eventually `display`) are below it.

**Why existing built-ins don't cover this.** CircuitPython exposes `board.LED` on most boards as a pin alias — it tells you which pin the on-board LED is wired to, nothing more.  You still write the blink loop, decide the color vocabulary, and wire it to wifi/mqtt callbacks yourself.  MicroPython is more inconsistent — some board ports expose `Pin("LED")` (Pico) or onboard-LED helpers, others nothing.  Neither runtime gives you "named system roles with patterns" (`indicator.set("connecting")`, `indicator.flash_error()`), and neither gives you a cross-runtime mapping.  This workstream is one level up from `board.LED` — it builds *on* whatever pin/strip the board exposes, not as a replacement for it.

**Proposed shape — `chumicro-presence` (working name; alternates: `feedback`, `status`, `deviceui`):**

A small orchestrator library that:

1. Subscribes to a small vocabulary of well-known event topics (`wifi.state`, `mqtt.state`, `error`).
2. Applies a config-driven mapping (`{"wifi.connecting": {"led": "pulse:blue", "lcd_top": "WiFi…"}}`).
3. Drives the user-facing hardware via injected `pixels`, `input`, `tone`, `display` services — none of which it implements itself.
4. Exposes a tiny imperative API for the app: `presence.notify("backup-complete", level="ok")`.

**This is the third consumer that justifies `chumicro-events`** — wifi and mqtt are #1 and #2, the device-feedback layer is #3.  Without it, an events bus is over-engineered relative to today's two callback-shaped relationships.

**What `chumicro-presence` does NOT do:**

- It does **not** import wifi / mqtt / sockets directly.  It subscribes to events.  This keeps wifi and mqtt free of any UI concern and keeps presence from depending on the whole networking stack.
- It does **not** own pin/strip drivers.  It composes `chumicro-pixels`, `chumicro-input`, etc.  If a user has no LED, presence still works — those outputs are just absent.
- It does **not** define a fixed event vocabulary up front.  Topics are namespaced strings; the user's mapping decides which matter.

**Open shape question:** does presence subsume the StatusIndicator HAL (single library, the HAL is just one of its outputs), or coexist with it (StatusIndicator inside `chumicro-compat` for thin uses, presence for thick uses)?  Recommend subsume — fewer concepts, and the "thin use" is just `presence.set_led("connecting")` without configuring anything else.

## Dependency policy — open question

**The problem.** Today's libraries take dependencies via constructor injection (`MQTTClient(sockets=...)`).  Clean for testing, but creates an onboarding cliff:

> "What sockets lib?  You mean I have to download chumicro-sockets too?  Why didn't anyone tell me?"

The injected-only pattern is great for swapping transports and for host-side tests, but it offloads a discovery problem to the user.

**Three policies, ordered by friction:**

| Option | Behavior | Pro | Con |
|---|---|---|---|
| **A. Hard-injection (current)** | mqtt's constructor requires a `sockets` factory; user must `pip install chumicro-sockets` and pass it in. | Total decoupling.  Trivial to swap. | Confusing onboarding.  Every example has injection boilerplate. |
| **B. Lazy default with optional dep** | mqtt tries `from chumicro_sockets import default_factory` if nothing is passed; ImportError → friendly message ("install chumicro-sockets or inject your own"). | Works out-of-the-box if dep present.  Override still trivial.  No hard `pyproject.toml` link. | ImportError still surprises users who didn't read the README. |
| **C. Hard dep with override** | mqtt declares `chumicro-sockets` in `pyproject.toml`; default constructor uses it; user can still override by passing a factory. | Just works.  Single `pip install chumicro-mqtt` is enough.  Override path preserved. | Pulls in `chumicro-sockets` even if user wanted a wholly different transport.  Builds a chain (mqtt → sockets → wifi if sockets ends up needing wifi). |

**Recommendation: Option C for "core infrastructure" deps; Option B-with-no-fallback (i.e., callbacks only) for "decoration" deps.**

The split:

- **Core infrastructure** — sockets, runner, timing.  Without these, the library doesn't function.  Hard-dep + override pattern.  Adds ≤1 transitive package per dep, all small.
- **Decoration / observability** — events, logging, presence/feedback.  The library functions fine without them.  Library exposes optional callbacks / hooks.  Library *never* imports the optional package, so no soft-dep games.

Rules this implies:

1. `chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server` declare `chumicro-sockets` as a hard dep.  Override via constructor still works.
2. Any library with periodic work declares `chumicro-runner` and `chumicro-timing` as hard deps.
3. **No library declares `chumicro-events` or `chumicro-logging` as a dep.**  They expose `on_state_change` callbacks and an optional `logger` parameter.  The application wires events ↔ services itself (or uses presence to do it for them).
4. **No library declares `chumicro-presence` as a dep.**  Presence consumes other libraries; nobody depends on presence.

This keeps the dependency graph a strict DAG with `presence` and `events` and `logging` at the top, and `sockets` / `runner` / `timing` at the bottom.

**Decision needed.**  Once a policy is picked, this should land as a Decision file (`plans/decisions/NNNN-library-dependency-policy.md`) and the existing libraries' `pyproject.toml` files audited against it.  Tracked as an open question in `plans/open-questions.md`.

## Suggested batches

Three reasonable picks:

1. **Conservative.** A1 (logging) alone.  No new decisions, smallest risk.
2. **Balanced (recommended).** A1 (logging) + decide dependency policy.  Logging is the natural place to live-test the "decoration dep" rule (it must not become a required dep).
3. **Ambitious.** A1 + A3 (events) + start on presence/feedback skeleton + decide dep policy.  Three new libraries' worth of design at once — expect 2–3 decision files and a slower cycle.

Tier B (input, pixels) is gated on plugging in the macropad.  Tier C is gated on hardware.

## Critical files when implementation begins

- **`libraries/wifi/src/chumicro_wifi/`** — canonical example of constructor-injected adapter + per-runtime selection ladder + `testing.py` fake.  Mirror for `chumicro-input` backends.
- **`libraries/mqtt/src/chumicro_mqtt/`** — canonical runner-shaped service with check/handle and event callbacks.  Mirror for `chumicro-input` event emission.
- **`libraries/sockets/src/chumicro_sockets/__init__.py`** — confirm UDP availability before scoping `chumicro-ntp`; current scope is TCP+TLS per Decision 0031.
- **`plans/workstreams/archive/phase-7-integration.md` §"LED / UX hooks for service state"** — original StatusIndicator HAL idea; superseded by the device-feedback layer above when this workstream proceeds.

## Verification (per library, when implementation begins)

Each new library follows the established DNA:

- Constructor-injected adapter; per-runtime selection ladder via `sys.implementation.name`.
- `testing.py` fake; CPython tests cover the full surface without hardware.
- Runner-shaped if it has periodic work (`check(now_ms) -> bool` + `handle(now_ms)`).
- Coverage gate ≥ 94 % under `python scripts/run.py test --coverage-threshold 94`.
- Tier B libraries also ship a `functional_tests/` suite that runs against the macropad once plugged in.
- Bundle pipeline check: `__chumicro_runtimes__` markers on per-runtime adapter files (Decision 0037).
