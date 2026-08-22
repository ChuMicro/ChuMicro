# Library pipeline — what to add next

**Status:** Tier A + dep-policy + UDP all shipped between 2026-04-27 and 2026-05-06; Tier B (macropad-validated libs) and the device-feedback layer (`chumicro-presence`) are the open slices.  See **Findings from the 2026-05-06 review** below for what's actually pickup-able vs. still hardware-gated.

**Origin:** strategy conversation 2026-04-27. Survey of the Adafruit bundle + micropython-lib + existing chumicro libraries to identify cross-runtime gaps worth filling. Folds in and widens the **LED / UX hooks for service state** open question from `plans/workstreams/archive/phase-7-integration.md` §"LED / UX hooks for service state".

## Findings from the 2026-05-06 review

The body below was written 2026-04-27 when the doc said "captured, no implementation yet."  Most of Tier A and the prereqs have shipped since.  Concrete state:

* **Tier A — all three libraries shipped:**
  * `chumicro-logging` — shipped, then removed before the public release: it never gained a consumer and was never published.  The optional-callable-injection rule it proved out survives as Decision 0042.
  * `chumicro-ntp` — VERSION 0.1.1.  Runner-shaped SNTP client over an injected UDP socket; cross-runtime.
  * `chumicro-events` — VERSION 0.1.0.  Runner-shaped pub/sub event bus (bounded, drop-oldest); zero chumicro deps and no other library imports it (per [Decision 0042](../decisions/0042-library-dependency-policy.md)).
* **Dependency policy resolved as [Decision 0042](../decisions/0042-library-dependency-policy.md)** (`proposed`, 2026-04-27).  The "core infrastructure = hard dep + factory helper" / "decoration = optional callback" split this workstream proposed is now the formal contract.  `chumicro-requests` (Decision 0040) had already established the workable shape: hard `chumicro-sockets` dep + `chumicro_sockets_factory(radio=…)` helper + explicit constructor parameter.  Each new library starts under the right rules.
* **UDP for sockets shipped as [Decision 0043](../decisions/0043-chumicro-sockets-udp.md)** (`accepted`).  The "first check whether sockets exposes UDP" prereq the workstream flagged for ntp is closed — `chumicro_sockets.udp_socket` exists and ntp consumes it.
* **`presence` / device-feedback layer — still open.**  The orchestrator described in §"Device-feedback layer" hasn't been started.  No events bus consumer beyond wifi → mqtt indirection has materialized; the third-consumer trigger the workstream named hasn't fired yet.
* **Tier B (input / pixels / tone) — still hardware-gated** on the macropad.  The libraries themselves don't depend on the macropad — they're constructor-injected backends — but the validation matrix needs the board plugged in to land them with a functional-test floor.  Macropad isn't on the bench in the current setup.
* **Tier C — still hardware-gated.**  Antennas not yet for LoRa, no GPS hardware wired, no stepper drivers.

### What's actually pickup-able now

In rough priority order:

1. **Plug in the macropad and ship Tier B.**  `chumicro-buttons` + `chumicro-knobs` + `chumicro-pixels` + (optional) `chumicro-tone`.  The libraries are board-agnostic — macropad is just the dev fixture for functional tests.  Each follows the established DNA (constructor-injected adapter, per-runtime selection ladder, `testing.py` fake, runner-shaped service).  The input split, the capture-interrupt contract, and the debounce surface are settled in [Decision 0124](../decisions/0124-buttons-and-knobs-libraries.md); the rest is implementation.
2. **`chumicro-presence` (device-feedback layer)** — the third-consumer trigger to make `chumicro-events` valuable beyond its current zero-consumer state.  Open shape question still in §"Device-feedback layer" below: subsume the StatusIndicator HAL or coexist?  Recommended subsume.  Pickable now without macropad — `chumicro-pixels` is the only dependency for the LED output, and a no-op pixels backend works for testing.
3. **Promote Decision 0042 from `proposed` → `accepted`.**  The libraries shipping under it (logging, events, ntp) confirm the policy works; no edits needed, just the status flip after a quick review pass.  Trivial.
4. **Audit existing libraries' `pyproject.toml` against Decision 0042.**  Check that `mqtt` / `requests` / `http_server` declare `chumicro-sockets` as a hard dep (they do, per Decision 0040) and that no library accidentally hard-depends on the decoration set (events / logging / future presence).  Quick verification, not redesign.
5. **Tier C as hardware arrives.**  Antennas for LoRa, a GPS module, a stepper driver — when any of these land on the bench, the corresponding library's research-then-ship slice unblocks.

### Reframe — what this workstream is now about

The original framing was *"survey + tier picks + dep-policy decision"*.  The survey paid out, the dep-policy decision shipped, Tier A is done.  Remaining workstream slice is:

* **Macropad picks (Tier B)** when the macropad is on the bench.
* **`chumicro-presence`** as the next net-new library, pickable without hardware.
* **Tier C** as hardware arrives, library by library.
* **Decision 0042 status flip** to `accepted` (housekeeping).

A fresh agent picking this up should NOT re-do the Tier A surveys — they shipped.  The body below is preserved for the macropad design notes (§"Tier B"), the device-feedback layer design (§"Device-feedback layer"), and the dependency-policy rationale (§"Dependency policy") which is now codified in Decision 0042 but still useful as the why-we-decided-this-way source.

### Related workstreams + decisions

* [Decision 0042](../decisions/0042-library-dependency-policy.md) — codifies the dep-policy split this workstream proposed.
* [Decision 0043](../decisions/0043-chumicro-sockets-udp.md) — UDP support that ntp consumes.
* [Decision 0040](../decisions/0040-chumicro-requests.md) — earlier-shipped pattern that Decision 0042 generalised.
* [`archive/phase-7-integration.md`](archive/phase-7-integration.md) §"LED / UX hooks for service state" — original StatusIndicator HAL idea that the device-feedback layer here supersedes.
* [`archive/beginner-onramp.md`](archive/beginner-onramp.md) — references `chumicro-requests` and `chumicro-http-server` (both shipped) as part of the demo story; future Tier B / presence work would feed into the same beginner flow.

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
| **chumicro-logging** | Tiny leveled logger with a handler protocol; runner-friendly buffered handler; CPython stdlib `logging` as fake / passthrough. **Must NOT become a required dep of other chumicro libraries** — they accept an optional `logger` callable, default no-op. | Universal need.  CP `adafruit_logging` is minimal, MP `logging` is quirky, stdlib is overkill — chumicro can pick a small subset and unify. |
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
| **chumicro-buttons** | SHIPPED.  `Button`, `Buttons`, `KeyMatrix`.  See "Buttons and knobs as built" below. |
| **chumicro-knobs** | SHIPPED.  `Encoder`, `AnalogKnob`.  See "Buttons and knobs as built" below. |
| **chumicro-pixels** | Runner-shaped LED patterns: `Solid`, `Blink`, `Pulse`, `Fade`, `Chase`, `Flash`. Constructor-injected strip backend (CP `neopixel.NeoPixel`, MP `neopixel.NeoPixel`, single PWM pin, no-op).  Each pattern is a tick-driven generator; service composites them onto the strip. |
| **chumicro-tone** *(optional)* | Non-blocking tone scheduler: `tone.beep(440, 50)` queues a tick-driven pulse train; backends are PWM (CP `pwmio`, MP `machine.PWM`), no-op.  Small (~80 lines).  Gravy. |

#### Buttons and knobs as built

Shaped by [Decision 0124](../decisions/0124-buttons-and-knobs-libraries.md); this section carries what the ADR deliberately does not.

How each reading is captured:

| | CircuitPython | MicroPython |
|---|---|---|
| `Button` / `Buttons` | `keypad.Keys` | `Pin.irq` into a preallocated ring |
| `KeyMatrix` | `keypad.KeyMatrix` | polled scan |
| `Encoder` | `rotaryio.IncrementalEncoder` | `Pin.irq` plus a transition table |
| `AnalogKnob` | polled ADC | polled ADC |

Facts read from the CircuitPython 10.2.0 and MicroPython 1.27.0 trees in `.tools/` rather than assumed:

- `keypad.Keys(pins, *, value_when_pressed, pull=True, interval=0.020, max_events=64, debounce_threshold=1)`, and `KeyMatrix(row_pins, column_pins, *, columns_to_anodes=True, ...)` with the same timing arguments.  `settle_ms` maps onto `interval` and `debounce_threshold` together.
- `keypad.Event.timestamp` is stamped from `supervisor_ticks_ms()` in the background scan, so it is already Decision 0014's tick base with no conversion.
- `rotaryio.IncrementalEncoder` defaults `divisor=4` and documents `1` for encoders without detents, which is where `detent_steps` gets its default.
- `countio.Counter` has no debounce parameter, which is why it is not used for buttons: one bouncy press lands as several counts and it cannot separate press from release.
- `CIRCUITPY_KEYPAD` tracks `CIRCUITPY_FULL_BUILD`, which defaults on.  Boards without it are atmel-samd, already outside the class Decision 0015 supports, so there is no polled fallback.
- Neither MicroPython adapter passes `hard=` to `Pin.irq`.  The scheduled handler the default gives is enough: the VM drains pending callbacks at every jump and call, so in a tick loop the queue empties far faster than contact bounce fills it.  Skipping it also sidesteps the esp32 port, whose `Pin.irq` takes no `hard=` at all.
- The knobs MicroPython quadrature table matches CircuitPython's own `transitions[16]` in `shared-module/rotaryio/IncrementalEncoder.c` entry for entry, verified by parsing both.  That is deliberate: a shaft turned one way has to report the same sign on either runtime.  The code carries no reference to it, because a comment naming an upstream repo path is forbidden by the code-comment rules; this is its home.

First-release sizes: buttons 28.0 KB stripped, knobs 9.3 KB.  Whole-library cost is why they are two installs rather than one.

Still open, and gated on the macropad:

- Neither `_adapters/cp.py` nor `_adapters/mp.py` has executed on hardware.  AGENTS.md requires real-board verification for runtime-specific code.
- Neither library has a `functional_tests/` suite.
- How many edges a real bouncy switch emits per press, which decides whether the MicroPython ring depth is right before `overflowed` starts firing on ordinary presses.
- Whether row-major key numbering actually agrees between `keypad.KeyMatrix` and the MicroPython scan.  Both sides claim it and nothing on a host can hold them to it.

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
- It does **not** own pin/strip drivers.  It composes `chumicro-pixels`, `chumicro-buttons`, etc.  If a user has no LED, presence still works — those outputs are just absent.
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

**Historical — what was actually picked.** Of the three options below (drafted 2026-04-27), the project ended up shipping option 3 ("ambitious") incrementally rather than as a single batch: logging shipped first, then ntp + UDP-for-sockets together, then events alongside Decision 0042.  Three new libraries + one ADR landed across the next ~10 days without overwhelming the cycle.

Three reasonable picks (preserved as the original survey):

1. **Conservative.** A1 (logging) alone.  No new decisions, smallest risk.
2. **Balanced.** A1 (logging) + decide dependency policy.  Logging is the natural place to live-test the "decoration dep" rule (it must not become a required dep).
3. **Ambitious.** A1 + A3 (events) + start on presence/feedback skeleton + decide dep policy.  ← *what shipped.*

Tier B (input, pixels) is still gated on plugging in the macropad.  Tier C is still gated on hardware.

## Critical files when implementation begins

- **`libraries/wifi/src/chumicro_wifi/`** — canonical example of constructor-injected adapter + per-runtime selection ladder + `testing.py` fake.  Mirror for `chumicro-buttons` / `chumicro-knobs` adapters.
- **`libraries/mqtt/src/chumicro_mqtt/`** — canonical runner-shaped service with check/handle and event callbacks.  Mirror for `chumicro-buttons` event emission.
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
