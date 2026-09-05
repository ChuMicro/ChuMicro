# Decision 0127: Pins are referenced by GPIO number

Status: `accepted`
Date: `2026-08-24`
Summary: Apps name pins by MCU GPIO number; `chumicro-compat` resolvers turn the number into the runtime's pin or bus object; physical-pin numbers and board alias names are out of scope.
Related: [Decision 0126](0126-canvas-indexed-palette.md) (the canvas whose construction seam this shrinks), [Decision 0010](0010-library-testability.md) (constructor injection), [Decision 0007](0007-cross-platform-dependency-strategy.md) (runtime shims live in compat)

## Context

The same wire has three names: MicroPython's `machine.Pin(6)`, CircuitPython's
`board.GP6` (or `board.IO6`, or `board.D6`, varying per board definition), and
the physical header position. Moving an app between runtimes means editing
every pin reference even though the MCU GPIO number never changed. The
maintainer's call (2026-08-24): the GPIO number is the pin's identity;
physical-pin numbers and board alias names ("neopixel", "button") are
explicitly not wanted.

## Decision

- `chumicro-compat` grows pin and bus resolvers taking MCU GPIO numbers. The
  contract, with exact names fixed at build time: a digital-output resolver
  returns an object satisfying chumicro's callable pin protocol (`pin(1)`
  drives high) on both runtimes; SPI and I2C resolvers return the runtime's
  native bus objects.
- MicroPython resolution is `machine.Pin(number)`, which is already callable.
- CircuitPython resolution is `getattr(microcontroller.pin, "GPIO%d")` — the
  canonical name table both the rp2 and espressif ports publish, so board
  alias vocabularies (`GP6` / `IO6` / `D6`) never enter the code path. The
  output resolver wraps `digitalio.DigitalInOut` in a callable.
- Bus resolvers take the MicroPython controller id plus GPIO numbers;
  CircuitPython ignores the id because `busio` derives the controller from
  the pins.
- Every resolver passes an already-constructed runtime object through
  unchanged. That is the escape hatch for ports whose pin namespace is not a
  flat integer (stm32's PA/PB names).
- Libraries stay injection-only per Decision 0010: resolvers are app-side
  composition and never appear inside `libraries/*/src`.

Rejected alternatives:

- **Physical-pin numbering** — board-revision-dependent and rejected by the
  maintainer; the bench mis-wiring it invites (3V3_EN one position from
  3V3 OUT) is documented in the field notes.
- **Board alias names** (`"neopixel"`, `"button"`, `board.D6`) — locks apps
  to one board's vocabulary; rejected by the maintainer.
- **A registry mapping logical names to pins in config** — configuration
  indirection for a constant; the GPIO number in the source is the truth.

## Consequences

- Hardware examples keep their runtime-prefixed filenames (they still
  construct buses), but their pin references become the same numbers on both
  runtimes, and an app's construction block shrinks to wiring facts.
- `chumicro-compat` bumps minor when the resolvers land; screens and charlcd
  examples migrate to them in the same change.
- Ports outside rp2 and espressif join by the pass-through escape hatch
  until someone needs more.
