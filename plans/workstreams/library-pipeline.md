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

What each surface needs before it can be called verified.  The macropad is not the gate for
most of it, and for one surface it is not sufficient:

| Surface | Hardware | Bench today |
|---|---|---|
| `Button`, `Buttons` | A pin and a wire to ground | Yes, on every registered board |
| `KeyMatrix` | A row-by-column grid, or wires plus diodes | No, wants the macropad or a breadboard |
| `Encoder` | A rotary encoder module | No, wants the macropad or a two-dollar module |
| `AnalogKnob` | A potentiometer on an ADC pin | No, and the macropad has none either |

So the single-button and multi-button paths, which are most of both libraries, can be verified
now: `keypad.Keys` on the CircuitPython boards and the `Pin.irq` capture on the MicroPython
ones.  The TinyPICO and FeatherS3 matter most there, because they are esp32 parts whose
`Pin.irq` takes no `hard=` and whose handler runs through the scheduler.  That path has only
ever been reasoned about.

##### Measured on a Pi Pico W, CircuitPython 10.2.0

A momentary switch straight from GP3 to ground, no debounce hardware, driven by hand.
`functional_tests/test_cp_adapter_on_device.py` carries what runs unattended; these are the
numbers behind it.

- **Ten presses produce about thirty falling edges.**  Bounce arrives in bursts of three to
  four edges that finish inside roughly 300 us, at the release as well as the press.  The
  release bounces because an opening contact closes again on the way apart, so a falling-edge
  counter sees both ends of a press.
- **Those thirty edges reach the library as exactly ten presses**, with `overflowed` staying
  false.  On CircuitPython the settle window is spent entirely inside the firmware scan, so
  the bounce never reaches Python.
- **The shortest hold that registered was 31 ms.**  A press shorter than `settle_ms` is
  rejected as bounce by design, so a 20 ms window sets the floor on a deliberate tap.
- **A tick costs nothing.**  Zero heap growth per 1000 `check()` calls after the first pass,
  which boxes one integer as the clock leaves the small-int range.  A tick loop ran at 236 us.

Measuring bounce at all took three instruments, and the first two lied:

- `keypad` with debouncing disabled reported **no bounce**, because its scan floor is 1 ms and
  the bursts are shorter than that.
- A `digitalio` poll loop at 11.7 us per read also reported **no bounce**, for the same reason
  one order of magnitude down.
- `countio.Counter` counts edges in hardware and found them immediately.  It is the only one of
  the three that cannot alias.  Two rp2040 constraints go with it: the pin must be on PWM
  channel B, which means an odd GPIO, and `Edge.RISE_AND_FALL` raises `NotImplementedError`, so
  a press has to be counted from one edge direction.

The lesson generalizes past this library: an instrument that samples cannot bound something
faster than its own sample rate, and reporting "no bounce" from one is a statement about the
instrument.

##### Measured on the same board reflashed to MicroPython 1.28.0

Same switch, same pin, so the two runtimes are directly comparable.
`functional_tests/test_mp_adapter_on_device.py` drives its edges from the chip; these came
from a finger.

- **The interrupt sees every edge the firmware scan was hiding.**  Ten presses put 68 edges
  through `Pin.irq`, against the roughly 30 falling edges `countio` counted for the same
  gesture.  On CircuitPython those never reach Python at all.
- **The ring is sized right.**  Peak backlog was 4 of 32 slots on ordinary presses and 9 of 32
  under 30 seconds of the fastest tapping a finger manages, which put 348 edges through.
  `overflowed` never fired.
- **The scheduled handler keeps up**, which is the evidence behind not passing `hard=` to
  `Pin.irq`.  It was never behind by more than a third of the ring.
- **A tick costs 489 us**, against 236 us for the same loop on CircuitPython.  That gap is the
  settle window being spent in Python rather than in C.

`settle_ms` is also the floor on the shortest press the library will report, which the docs
had backwards.  The guide claimed raising it "never costs you a press."  It costs a lot of
them.

Ground truth came from a bare `Pin.irq` handler stamping every edge into an array, with no
library and no debouncing, so closures could be counted without `settle_ms` in the way.
Thirty seconds of the fastest tapping a finger manages closed the contact **107 times**, and
**30 of those closures were shorter than 20 ms**.  The library reported 75 presses over the
same gesture, which is the 77 that clear the default window.  So the default silently
discards better than a quarter of fast tapping.

Getting there took one more instrument correction, and this time the bad instrument was the
press count itself.  348 raw edges against 75 reported presses is equally consistent with 75
taps that bounced and 150 taps that did not, so the first reading of it, that the default was
merely conservative, was a guess dressed as a measurement.  Counting closures independently
of the library is what separated the two.

The default moved to 10 ms as a result.  The closure durations say what each window costs on
this switch, and the library reports exactly the closures that clear its window:

| `settle_ms` | Closures dropped | Reported presses |
|---|---|---|
| 20 | 30 of 107 | 77 |
| 10 | 7 of 107 | 100 |
| 5 | 4 of 107 | 103 |

Nothing is given up at 10 on hardware like this, since the bounce settles inside 300 us and any
of the three filters it completely.  The default cannot be 5, because it also has to hold for
switches nobody measured: a big toggle or a worn microswitch can bounce for twenty
milliseconds, and a 5 ms window could believe a gap in the middle of that.  Ten keeps margin
against those while covering the tactile switches most buttons are.  Decision 0124 carries the
rule; the guide carries the per-window cost.

##### Measured on a Lolin S2 Mini, MicroPython 1.27.0

The esp32 port is a different capture path from rp2040, not just a different board: its
`Pin.irq` installs no hard handler and the ISR hands the callback to `mp_sched_schedule`, so
the handler runs when the VM next reaches a safe point.  That is the path the adapter was
written against and had only ever been reasoned about.

- **`hard=True` raises `TypeError: extra keyword arguments given`** on this port, confirmed on
  silicon.  An adapter that passed it unconditionally would fail at construction on every
  esp32 board.  This is why neither adapter passes it.
- **A starved loop loses nothing.**  Ticking once every 300 ms, so the loop was asleep for all
  but a sliver of the run, all ten presses and releases arrived and `held_ms` read 51 to 63 ms.
  Durations from the tick rather than the edge would have been multiples of 300.  The esp32
  scheduler drains through `time.sleep_ms`, so the queue never backed up.
- **The settle model is exact, not approximate.**  Spying on the ring from inside the interrupt
  gives ground truth and library output from one gesture: 13 contact closures, 12 of them
  lasting at least the 10 ms window, and 12 presses reported.  Prediction error zero.  Nothing
  was lost to the scheduler and no bounce was mistaken for a press.
- Peak ring backlog 3 of 32, no overflow, and zero heap growth per 1000 ticks.

The functional suite passes 9 of 9 here as it does on rp2040.  Its pin candidates had to be
narrowed to do so safely: the list must hold on every chip family, and the dangerous numbers
differ per family, so anything that is SPI flash, PSRAM, native USB, or a strapping pin on any
of them is out.  Driving one of those does not raise, it resets the board.

##### Knobs on real hardware, Lolin S2 Mini

`chumicro_knobs` had never run on a board.  Eight functional tests now cover the
CircuitPython contract with `rotaryio` and `analogio`, and a real KY-040 encoder wired to
IO3 and IO5 exercised the decode:

- **The decode is exact.**  Ten clicks one way and ten back gave ten `+1` events and ten
  `-1`, furthest position `+10`, final position `0`, every delta `1`.  No detent doubled and
  none dropped.
- **The encoder is 2 pulses per detent, and the default is 4.**  Nothing raises when they
  disagree; the count is just consistently off by a factor, which reads as a shaft that
  reports half the clicks.  `rotaryio`'s own default is 4 and panel-mount parts match it,
  but cheap modules commonly give 2.  The guide now carries a recipe for measuring it,
  since it cannot be guessed.
- **A module's `+` pin is not optional.**  Left unwired, the onboard pull-ups float and
  pulses drop at random: a steady two-per-detent became a mix of ones, twos and threes,
  with 16 pulses of movement netting `+4`.  Wiring it made every detent read exactly 2.

Spun far past the part's rating, the two runtimes were compared at matched speed, which took
three attempts to arrange because the first two had no valid speed measurement attached:

| Decode | Where | Travelled | Peak detents/sec | Drift |
|---|---|---|---|---|
| Rejecting table | CircuitPython rp2040, sampled by PIO | 284 | 1017 | 0.4 % |
| Rejecting table | MicroPython ESP32-S2, sampled by `Pin.irq` | 225 | 1050 | 2.2 % |
| Stateless edge count | CircuitPython ESP32-S2, PCNT | 240 | 1043 | 5.4 % |
| Rejecting table | MicroPython rp2040, sampled by `Pin.irq` | 329 | 497 | 0.3 % |

The first three rows are matched within three percent on speed, so they can be compared.  Both
decodes that hold state stayed at or under 2.2 %, and the one that does not drifted 5.4 %, more
than double the worst table result.  CircuitPython supplies both the best row and the worst,
on one encoder at one speed, so the runtime is not the variable and neither is hardware against
software.  What separates them is whether the decode can reject a transition a real shaft could
never make.

The fourth row ran at half the speed of the others and is supporting rather than comparable.
What it establishes on its own is that the interrupt path absorbed a peak of 5055 edges per
second, higher than either S2 run, and stayed within a third of a percent over 329 detents.

This one was called before it was measured, which is why it carries more weight than the
earlier comparisons here.  Reading `ports/raspberrypi/common-hal/rotaryio/IncrementalEncoder.c`
showed PIO sampling feeding `shared_module_softencoder_state_update`, the same rejecting table
`MpEncoderSource` carries, while the esp32 port counts edges of one line with the direction
taken from the other line's level and holds no state at all.  That predicted which way rp2040
CircuitPython would fall, and it fell that way.  It is still one run per cell, so the ordering
is the result and the magnitudes are approximate.

The Python decode drifted less than the hardware counter, which is worth recording because it
is the opposite of the expected result.  The mechanism fits: PCNT counts edges of one line with
the direction taken from the other line's level and holds no state, so it cannot reject a
transition a real shaft could never make, while the transition table maps both-pins-changed to
zero and throws it away.  An earlier MicroPython run saw 2.67 edges per detent and still
drifted nothing, which is that rejection working.

This is one matched pair rather than a distribution, and the gesture behind it is a human hand,
so treat the direction as suggestive and the magnitudes as approximate.  Both runtimes count
exactly at any speed a wrist produces; roughly 1000 detents per second is horsing around, and
the drift matters only where something motorized turns the shaft.  The `MpEncoderSource` note
that its table matches CircuitPython's `transitions[16]` entry for entry is the reason the two
disagree here at all: the table is upstream's own, and the esp32 PCNT path is what departs
from it.

Two instrument lessons came out of it, both the same shape as the buttons ones.  Reading a
count as "the library is wrong" when the encoder's detent size was never established is
inference, not measurement; the fix was to count raw pulses and group them by the gaps
between, which finds the detent boundaries without needing to know how far anyone turned.
And a rise-time check built from a Python polling loop resolves nothing under about 100 us,
because each pass of the loop costs 20, so the numbers it produced were noise presented as
evidence.

##### The key matrix on a real grid

A 4x4 membrane keypad, eight unlabelled pins wired to GP2 through GP9 in no particular order,
on a Pi Pico W under both runtimes.  `KeyMatrix` had never met a grid before this; everything
until now was fakes and host tests.

The pins were identified rather than guessed, which is worth keeping as a recipe.  Hold one key
and the row and column behind it short together, so driving each pin low in turn and reading
the rest names the pair.  Press every key in reading order and the sequence of pairs gives the
whole map: the pin common to the first four presses is the first row, the four it pairs with
are the columns in order, and the rest follow.  Here that came out as rows on GP5, GP4, GP3,
GP2 and columns on GP9, GP8, GP7, GP6, which is the keypad's own order reversed against the
header.

Row-major numbering holds, and it holds the same way on both runtimes.  Pressing all sixteen
keys in reading order reported indices 0 through 15 in exactly that sequence under MicroPython,
then again under CircuitPython on the same grid with the same wiring.  That is worth more than
either run alone: CircuitPython hands the scanning to the firmware's `keypad.KeyMatrix` in C
while MicroPython uses this library's own polled scan, so the two are separate implementations
agreeing rather than one being self-consistent.  A host test cannot reach this, because a fake
agrees with whatever it was written to agree with.  Hold times read 113 to 166 ms under
MicroPython and 80 to 116 under CircuitPython, which is a finger either way.

Rows and columns are interchangeable on a grid with no diodes, so the scan cannot tell which
set is which and does not need to: the choice only decides which way the numbering runs.  What
that hardware cannot do is three keys forming a rectangle, where a fourth reads as pressed.
That is the grid rather than the library, and it is why `keypad.KeyMatrix` carries a
`columns_to_anodes` argument for grids that do have diodes.

This surface stays bench-verified rather than covered by a suite.  The self-driving trick the
other suites use needs a pin to raise its own interrupt, and a matrix needs one pin shorted to
another, which no board can do to itself.

##### The analog knob on real potentiometers

A wiper across 3V3 into an ADC pin, on a Pi Pico W and a Lolin S2 Mini.  Every number below
is with the pot untouched, so any reported movement is the library inventing it.

Every row is the wiper parked between 44 and 53 percent of its travel, because noise on a
divider scales with the fraction of the supply being read and a measurement taken against a
stop is not comparable to one taken mid-sweep.  Three readings were discarded for exactly that
before this table settled.

| | Parked at | Noise, middle 90 % | Full spread | Unfiltered would report | Filtered |
|---|---|---|---|---|---|
| Pi Pico W, CircuitPython | 53 % | 656 | 672 | 2 steps, 132 movements per 15 s | 0 per 20 s |
| Pi Pico W, MicroPython | 44 % | 288 | 1217 | 2 steps | 0 per 20 s |
| Lolin S2, CircuitPython | 44 % | 338 | 2125 | 4 steps | 0 per 20 s |
| Lolin S2, MicroPython | 48 % | 608 | 4705 | 9 steps | 0 per 20 s |

Against a stop the same boards read very differently: the Pico W measured 944 counts at 99 %
under CircuitPython and 848 under MicroPython, against 656 and 288 mid-sweep.  That is the
ratiometric divider doing what it should, and it is why the position is in the table.

What the step wander follows is the tails, not the middle, which is why the source runs two
filters rather than one.  Divide each full spread by its middle ninety percent and the cells
line up: 1.0 on the Pico under CircuitPython, then 4.2, 6.3 and 7.7, and the steps an
unfiltered reading would have covered go 2, 2, 4 and 9 in the same order.  A cell can be noisy
in the middle and behave, or quiet in the middle and wander badly.

The two mechanisms need different answers.  The Pico under CircuitPython has almost no tails at
all, 672 of spread against 656 through the middle, but that noise is wide enough on its own to
walk the deadband's anchor across a step boundary and back, and only smoothing settles it.  The
S2 under MicroPython is no worse through the middle yet reaches 4705, so its damage comes from
occasional samples several steps out, which smoothing would average in and only a median throws
away.  Neither filter would have covered every board.

The regulator does show up, but against a stop rather than mid-sweep, where the reading tracks
the whole supply instead of a fraction of it.  There the Pico measured 944 and 848 counts
against the S2's zero, which is a switching regulator against an LDO.  Mid-sweep the ordering
does not survive, so the earlier reading of it as a board-level property was drawn from
measurements taken at different positions.

The two runtimes differ on one board as much as the two boards differ, and for a reason that
shows up in both directions.  CircuitPython converts through a calibration table and averages
two conversions, which halves the noise and caps the range; MicroPython scales the raw count
with neither, which keeps the range and leaves the noise.  On the S2 that is 338 counts against
608, and 2125 of spread against 4705, from one pot at one position with only the runtime
changed.

Sweeping tracks exactly on all three: 0 steps skipped anywhere, and move counts matching real
step crossings rather than chatter, 661 and 600 and 293 events for gestures of that size.

Two measurements had to be thrown away before those were trusted.  A knob parked against the
top stop on the S2 read zero counts of noise and looked like proof of a clean supply; it was a
saturated converter reporting a constant.  And a filter shift picked by replaying a captured
buffer offline predicted a setting that left 593 movements a second live, because samples
captured in a tight loop do not carry the correlation the noise has at the loop's own rate.
Both numbers came from measuring something other than what the claim was about.

An ESP32 cannot reach the top of a pot's travel at all, which is the converter and is already
known: Adafruit's board guides put the S2 and S3 ceiling near 51000 counts or 2.57 V, and
CircuitPython carries an open bug reporting 51157 on an S2 against a full 65535 on an RP2040.
Measured here, the same pot swept 1424 to 65535 on the Pico and 1440 to 49787 on the S2.  The
guide carries it because the failure pins rather than degrades, so the last quarter of a knob
does nothing while nothing raises.

##### The runtime and silicon matrix, and what each cell is worth

Both runtimes run green on both chip families, but the two suites do not prove the same thing
and the table should not be read as if they did:

| | CircuitPython 10.2.0 | MicroPython |
|---|---|---|
| Pi Pico W, rp2040 | 7 of 7, plus 10 presses by hand | 9 of 9, 1.28.0, plus presses by hand |
| Lolin S2 Mini, ESP32-S2 | 7 of 7, plus 11 presses by hand | 9 of 9, 1.27.0, plus presses by hand |

The MicroPython suite drives real edges, so it proves capture, debounce rejection, ring
overflow, and interrupt detach.  The CircuitPython suite generates no edge at all: it proves
that `keypad` accepts every interval and threshold `settle_ms` maps to, that the clock domains
agree, that `deinit` hands the pin back, and that a tick allocates nothing.  That is the
contract with the firmware, not the behaviour of a press.

The asymmetry is forced.  CircuitPython enforces exclusive pin ownership, so a `digitalio`
output cannot be opened on the pin `keypad.Keys` already holds, and the self-driving trick that
makes the MicroPython suite unattended is unavailable.  Driving edges under CircuitPython needs
a jumper between two GPIOs, one driven and one scanned, which is wiring a suite cannot assume.

So every cell needed a finger on a contact before it meant a button works, and every cell has
had one.  On the Pi Pico W, 30 hardware falling edges arrived as 10 clean press events.  On the
S2, 11 presses gave 11 press events and 11 releases with holds of 33 to 51 ms, no overflow, on
a 201 us tick.  Reading a green CircuitPython suite as proof that a press works is the mistake
to avoid here: it is proof that the library agrees with `keypad`, and nothing had pressed
anything.

`keypad` being present on the S2 build was checked rather than assumed, since `CIRCUITPY_KEYPAD`
rides `CIRCUITPY_FULL_BUILD` and a board that left it off would refuse at construction.

Two things about that CircuitPython run are worth keeping.  The board's filesystem had to be
reformatted first, because staging the library onto `/Volumes/CIRCUITPY` with `cp -r` tore the
FAT: the board auto-reloads the moment the drive changes, so it was rewriting the filesystem
while the host still was, and macOS added `._` AppleDouble files to the same directories.  The
entries survived as unstattable and unremovable, which failed every later deploy.  That is now
a pitfall in `AGENTS.md`, next to the existing rule about mount state.

The same hand-staging also cost a rarer observation.  The board came up 49 seconds from a
`supervisor.ticks_ms` wrap, which recurs only every 6.2 days and would have exercised the
wrap-safe arithmetic on real hardware for the first time.  Copying the library soft-reset the
board and zeroed the counter.  Observe first, deploy second, when the clock is the thing under
test.

Still open regardless of hardware:

- Neither `_adapters/cp.py` nor `_adapters/mp.py` has executed on a board.  AGENTS.md requires
  real-board verification for runtime-specific code.
- Neither library has a `functional_tests/` suite.
- How many edges a real bouncy switch emits per press, which decides whether the MicroPython
  ring depth is right before `overflowed` starts firing on ordinary presses.
- Whether row-major key numbering agrees between `keypad.KeyMatrix` and the MicroPython scan.
  Both sides claim it and nothing on a host can hold them to it.

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
