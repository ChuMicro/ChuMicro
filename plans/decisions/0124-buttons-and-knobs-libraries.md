# Decision 0124: `chumicro-buttons` and `chumicro-knobs`, no shared base

Status: `accepted`
Date: `2026-08-21`
Summary: Physical input ships as `chumicro-buttons` and `chumicro-knobs`, no base library and no cross-dep; each adapter captures edges however its runtime allows, with no user-facing knob.
Related: [Decision 0014](0014-runner-pattern.md) (runner contract, which named buttons), [Decision 0051](0051-runner-shaped-as-project-policy.md) (runner-shape as project policy), [Decision 0010](0010-library-testability.md) (constructor injection, `testing.py`), [Decision 0042](0042-library-dependency-policy.md) (dependency policy), [Decision 0037](0037-runtime-file-marking.md) / [Decision 0044](0044-deploy-time-runtime-filtering.md) (runtime marking + deploy filtering), [Decision 0065](0065-device-library-scaffolding-cost.md) (no pure-passthrough `@property`), [Decision 0049](0049-three-runtime-trinity.md) (CPython is the test seam), `plans/workstreams/library-pipeline.md` §"Tier B".

## Context

Decision 0014 named buttons as one of the libraries its `check(now_ms)` / `handle(now_ms)` contract was designed for, and `library-pipeline.md` §"Tier B" sketched a single `chumicro-input` covering buttons, matrix, encoder, and analog together.  Two facts since then argue against that shape.

The first is install cost.  Decisions 0044 and 0062 already keep unreached modules off a device on the workspace deploy path, but `circup install` and `mip install` copy the whole package.  A one-button project on those paths would carry quadrature decode and ADC smoothing it will never call.

The second is that the runtimes diverge on the one thing that matters most for a button: catching a tap that lands between two passes of the loop.  CircuitPython's built-in `keypad` scans in the runtime's C, debounces there, and queues timestamped events.  MicroPython ships no equivalent, so the only mechanism that does not lose the tap is `machine.Pin.irq()`.  Getting that right means an allocation-free handler, a preallocated buffer, and debounce kept out of interrupt context, which is exactly the set of details a beginner gets wrong.

CircuitPython users are not starting from nothing.  `keypad`, `rotaryio`, `countio`, `analogio`, and `digitalio` are C modules compiled into the firmware image, so a CircuitPython project gets capture-quality input at no cost in user flash.  Where the firmware stops is meaning: `keypad` publishes an event stream and a key count, so "is key 3 held right now" and everything built on duration — long press, repeat, multi-click — is state the application reconstructs for itself.  MicroPython 1.27 ships none of the five and offers only `machine.Pin.irq`.

## Decision

### Two libraries, no base

`chumicro-buttons` owns every input that reads as on or off: `Button` (one pin) and `Buttons` (several) in `core.py`, `KeyMatrix` (rows by columns) in `matrix.py`.  All three produce the same events, so press, release, long press, repeat, and double press are implemented once.

`chumicro-knobs` owns every input that reads as a position: `Encoder` (quadrature, `detent_steps=4` default, optional `bounds` and `wrap`) in `encoder.py`, `AnalogKnob` (ADC with deadband and step quantization) in `analog.py`.  Both publish `delta` and `just_moved` and both are runner-shaped, but the reading itself is named for the device: an encoder reports `position` because it counts movement from wherever it started, and an analog knob reports `value` because it points somewhere absolute.  Their `on_change` arity follows the same split, carrying the delta for one and the value for the other.  Forcing one name across both would be false symmetry.

Neither library depends on the other, and no base library sits under them.  What a base would hold is a three-line settle-window compare, an adapter-selection ladder the workspace already duplicates by policy across `sockets`, `wifi`, and `kvstore`, and a duck-typed runner contract that needs no import at all.  `chumicro-timing` is the only shared dependency, declared per [Decision 0042](0042-library-dependency-policy.md) Class 1.

An encoder's push switch is a `Button` from the other library.  The two are wired together by the application, never by a cross-dep.

### The matrix is a source, not a library

A matrix key's events are button events; only the scan differs.  Splitting the matrix into `chumicro-keypad` would mean writing the long-press and repeat layer twice, or hoisting it into the base library this decision rejects.  It lives in `chumicro-buttons` as its own module so the deploy walker drops it from projects that never construct one.

### The library owns the interrupt, the user never writes one

A press that outlives no pass of the loop is still a press the user made, so the library captures it.  Where the runtime captures in C, that is what the adapter uses.  Where it does not, the library installs the interrupt itself and hides it, because the alternative is every user hand-rolling the same handler and getting the allocation rules wrong.

| | CircuitPython | MicroPython |
|---|---|---|
| `Button` / `Buttons` | `keypad.Keys` | `Pin.irq(hard=True)` into a preallocated ring |
| `KeyMatrix` | `keypad.KeyMatrix` | polled scan |
| `Encoder` | `rotaryio.IncrementalEncoder` | `Pin.irq(hard=True)` + transition table |
| `AnalogKnob` | polled ADC | polled ADC |

CircuitPython needs no Python-level interrupt: `keypad` and `rotaryio` run in the runtime's C, and `keypad`'s event timestamps are already in the `supervisor.ticks_ms` domain [Decision 0014](0014-runner-pattern.md) requires, so long-press timing uses the real edge time rather than the tick that noticed it.  Where a build ships without `keypad`, the adapter falls back to polled `digitalio` and says so in its docstring, since that path gives up the between-ticks guarantee.

The MicroPython handler is bound by four conditions, and they are the contract, not advice:

1. **It allocates nothing.**  The ring is an `array.array` sized at construction, the handler stores small ints into existing slots, and the bound method is registered once so no callable is built per edge.
2. **It captures, it does not decide.**  Raw edge state and `ticks_ms` go into the ring.  Debounce, repeat, long press, and every callback run in `check(now_ms)` and `handle(now_ms)`, in normal context, on the shared tick.
3. **No user code runs in interrupt context.**  `on_press` and its family are dispatched from `handle`.  A user callback that allocates, prints, or raises stays harmless.
4. **Overflow is bounded and flagged.**  A full ring drops the newest edge and sets `overflowed`, which is `keypad.EventQueue.overflowed`'s exact semantic, so the attribute means one thing on both runtimes.  A counter is not available: CircuitPython's queue only publishes a boolean, and the cross-runtime surface is the intersection.  This condition binds handlers that queue.  A handler that folds each edge straight into a counter, which is what quadrature decoding does, has nothing to drop and publishes no such flag; an impossible transition decodes as no movement instead.

There is no knob for any of this.  No `capture=` argument, no interrupt mode, no opt-out.  Catching the press someone actually made is the behavior of a button library, not a setting, and a switch would only hand the user back the question the library exists to answer.

Polling remains correct in two places and is not a fallback there.  A matrix scan is inherently polled, and driving rows against column interrupts invites ghosting for nothing.  An ADC has no missed-edge concept at all.

`countio.Counter` is rejected for buttons.  It has no debounce, so one bouncy press lands as several counts, and it cannot separate press from release.

This narrows the blanket "No ISRs" line in `AGENTS.md` §"Library code rules".  What that rule protects is the cooperative model: no application control flow in interrupt context, nothing that can preempt the tick loop into an inconsistent state.  A capture handler meeting the four conditions above takes nothing away from it.

### The CircuitPython adapter stays thin

The adapter drains `keypad`, tracks the per-key level `keypad` does not publish, and hands events to the shared semantic layer.  It does not scan, debounce, or time anything itself.  Anyone tempted to "improve" it by reimplementing that work should read this paragraph instead.

Firmware built-ins are fair game and bundle libraries are not.  Reaching for `keypad` or `rotaryio` costs nothing and is how capture is done correctly on that runtime.  The semantic layer is written here rather than taken as a dependency, because anything available on only one runtime would mean long press and multi-click behaving one way on CircuitPython and another on MicroPython, with two implementations to keep honest.  One semantic layer, written here, shared by all three runtimes, is the thing that makes the API mean the same thing everywhere.

This means the library is not sold to a CircuitPython user as better input handling, because on CircuitPython alone it mostly is not.  A project that will only ever run CircuitPython, with a loop that never stalls, is well served by the firmware modules and the existing bundle ecosystem and should use them.  Three things justify this library instead, and the guide leads with them rather than with a comparison:

1. **The same code moves between runtimes.**  Every other layer of a ChuMicro application already ports; the button is the hole in that.  Filling it is the project's second rule, not a feature.
2. **Input logic is testable on a laptop.**  The scripted CPython fake makes a long-press or multi-click state machine a host unit test, which is [Decision 0049](0049-three-runtime-trinity.md)'s test seam applied to input and which neither CircuitPython option offers.
3. **Capture and semantics arrive together.**  Never missing a tap and knowing what the tap meant currently require two libraries that do not compose.  That gap is invisible on a fast loop and obvious on one that stalls for a socket read or a flash write, which is the shape of the applications this project is for.

### One debounce knob

`settle_ms=20` is the default and `settle_ms=0` means the signal is already clean, which is the setting a hardware-debounced button uses.  On CircuitPython it maps onto `keypad`'s scan interval and debounce threshold; on MicroPython it is the window applied when the ring is drained.  There is no mode enum.

Wiring and hardware debouncing are documented in the library guide with schematics, including RC values, the charge and discharge asymmetry, the SPDT latch, and when software debounce is enough.  `settle_ms=0` is the setting that section exists to explain.

### Per-tick state is plain attributes

`check(now_ms)` updates `pressed`, `just_pressed`, `just_released`, and `held_ms` in place, and `handle(now_ms)` dispatches the `on_press` family.  The flags are valid for the current tick, which costs no allocation and needs no consume semantics.  They are public attributes, not properties, per [Decision 0065](0065-device-library-scaffolding-cost.md).

## Consequences

`library-pipeline.md` §"Tier B" loses its `chumicro-input` row and gains these two.  Both need entries in `size-budgets.toml` before the size gate can hold them, and both need a `functional_tests/` suite, which stays hardware-gated on the macropad exactly as Tier B already was.

The MicroPython adapter carries the weight, and that is the point rather than a regret.  Measured at first release, `_adapters/mp.py` is 18.1 KB against `cp.py`'s 11.8 KB in buttons, where it is also the largest module in the library, and 6.0 KB against 2.6 KB in knobs, where `encoder.py` is larger still.  CircuitPython users are buying a thin pass over `keypad` and `rotaryio`; MicroPython users are buying the interrupt handler and the quadrature decode they would otherwise write wrong.  The asymmetry in the source is what makes the API symmetric for the user, and it is what earns these libraries their place next to a fifteen-line `digitalio` snippet.  Whole-library cost lands at 28.0 KB stripped for buttons and 9.3 KB for knobs, which is why they are two installs rather than one.

The interrupt conditions need a test that actually holds them.  Allocation-free is measurable with the `gc.mem_alloc()` bracket the workspace already uses for the per-tick budget, and the `overflowed` flag gives the overflow path an assertion instead of a hope.

A knob with a push switch means two installs.  That is the price of keeping the dependency graph a DAG, and it teaches the right idea: the click is a button.

The CircuitPython claims above are read from the 10.2.0 source in `.tools/` rather than assumed, and the MicroPython absences from 1.27.0 in the same place.  `keypad.Keys(pins, *, value_when_pressed, pull=True, interval=0.020, max_events=64, debounce_threshold=1)` and `keypad.KeyMatrix(row_pins, column_pins, *, columns_to_anodes=True, interval=0.020, max_events=64, debounce_threshold=1)` give `settle_ms` both halves of its mapping, and `debounce_threshold` is the counted-sample debounce the firmware already implements, documented as emitting an event only after a key holds a state that many scans running.  `settle_ms` stays the one knob and picks that value internally rather than exposing a second.  `Event.timestamp` is documented as `supervisor.ticks_ms`, and `shared-module/keypad/__init__.c` stamps it from `supervisor_ticks_ms()` in the background scan, so it is [Decision 0014](0014-runner-pattern.md)'s tick base with no conversion.  `rotaryio.IncrementalEncoder` defaults `divisor=4` and documents `1` for encoders without detents, which is where `detent_steps` gets its default.  `countio.Counter(pin, *, edge, pull)` has no debounce parameter at all.

Keypad availability is a build flag, not a version question.  `CIRCUITPY_KEYPAD` tracks `CIRCUITPY_FULL_BUILD`, which defaults to on, and neither default moved between the 2023 source and current `main`.  `CIRCUITPY_ROTARYIO` is on unconditionally, so `Encoder` needs no fallback at all.  Boards without a full build are atmel-samd, which [Decision 0015](0015-board-architecture-support.md) already puts outside the supported class, and a handful of supported-port boards switch `keypad` off by hand.  That handful is what the polled `digitalio` fallback covers.  No firmware floor is named here on purpose: the flag defaults decide this, and they are stable.
