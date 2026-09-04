# Workstream: screens capability slices

Status: **active**, Phase 1 shipped and Phase 2 next.  Planned during the
GC9A01A matrix validation session so a cold pickup has the shapes, the
measured constraints, and the order.  The goal, set by the maintainer the
same day: one app's rendering and construction code runs on both device
runtimes with at most wiring-fact edits.
[Decision 0126](../decisions/0126-canvas-indexed-palette.md) pins the canvas
contract; [Decision 0127](../decisions/0127-pins-by-gpio-number.md) pins the
pin-reference contract.

## Why

The capability ledger against the display ecosystem, measured during the
matrix bench:

- **CircuitPython needs no new rendering capability.**
  `gc9a01a_displayio.make_display` returns a real `busdisplay.BusDisplay`,
  so the firmware and library ecosystem work unmodified: proportional fonts
  (`terminalio`, `adafruit_display_text`), automatic dirty-region partial
  refresh, `jpegio` and `gifio` decoders in core, and sprite-move animation.
  What CircuitPython lacks is the *shared surface*: Decision 0125 decided a
  framebuf-vocabulary protocol over `displayio.Bitmap` + `bitmaptools`, and
  only the MicroPython half exists.
- **MicroPython's comparable class** (pure-Python drivers on standard
  firmware) shares our drawing floor, framebuf's C primitives, and blocks
  the loop for the full refresh, which `ScreenService` exists to fix.  The
  real gaps against those libraries are fonts and partial updates.  Every
  phase below is additive; the duck-typed panel protocol survives all of
  them.

## Phase 1. Pin and bus resolvers by GPIO number (Decision 0127): shipped

`chumicro_compat.wiring` holds four resolvers.  `digital_output(gpio,
value=)` returns a callable-protocol pin on both runtimes: `machine.Pin` in
output mode on MicroPython, a callable wrap of `digitalio.DigitalInOut` on
CircuitPython.  `spi_bus` and `i2c_bus` return `machine.SPI` / `busio.SPI`
and `machine.I2C` / `busio.I2C`, carry the MicroPython controller id that
CircuitPython ignores, and apply the same baudrate and frequency on both
runtimes (`busio.SPI` is configured once under its lock; `i2c_bus` defaults
to 400 kHz where `busio.I2C` alone would default to 100 kHz).  `gpio_pin` is
the resolver the ADR did not name: `fourwire.FourWire` takes bare pin
identities for its command, chip-select, and reset lines, so the displayio
examples needed it.  CircuitPython lookup is `getattr(microcontroller.pin,
"GPIO%d")`, present on both the rp2 and espressif ports in 10.2.0, so
`board.*` alias vocabularies never enter.  Already-constructed objects pass
through unchanged (the stm32 escape hatch).  The seven screens and charlcd
hardware examples carry the same GPIO numbers on both runtimes, and
`compat/examples/blink.py` is the first example marked for both device
runtimes.  Compat bumped to 0.4.0.  A CPython host raises `RuntimeError`
from every resolver, and the 22 host-only tests drive both device branches
through `sys.modules` fakes on CPython and both unix ports.

## Phase 2. Canvas protocol and the CircuitPython backend (Decision 0126)

Next, in two slices.  The Pico W bench settled the backend: displayio's
refresh pipeline costs about 6 us per dirty pixel on the RP2040 however
the frame is chunked (318 ms for a whole frame in one stall, 510 ms in
480-pixel chunks that fit the tick, with the frame stored twice), while a
16-bit `displayio.Bitmap` drawn with `bitmaptools` in the panel's byte
order and streamed over `busio.SPI` from its own buffer crosses in 44 to
65 ms in strips of 1.5 to 3.9 ms, and its 117 KB frame fits a fresh Pico W
heap with 57 KB to spare.  The hardware-traps field note carries all three
tables.

**Phase 2a, the CircuitPython GC9A01A driver.**  `chumicro_screens.gc9a01a`
becomes cross-runtime: the panel bring-up, window commands, strip loop, and
`flush()` generator are already runtime-neutral, and the frame backend is
selected at construction, `framebuf` on MicroPython and a 16-bit
`displayio.Bitmap` on CircuitPython.  On CircuitPython the SPI bus is locked
once at construction (the resolver already configures it), strips are
pre-sliced 16-bit views of the bitmap's buffer, and the pins are the
callables `digital_output` returns.  `ScreenService` paces it unchanged, so
the loop code is the MicroPython loop code.  Gate: the labeled card and the
seconds counter on Pico W+CircuitPython and S2+CircuitPython, a strip
timing probe on each, and zero bytes per advance.

**Phase 2b, the canvas vocabulary.**  Palette indexes as colors and
`set_color(index, red, green, blue)` as the only color entry on both
backends.  On MicroPython the canvas is `GC9A01AIndexed.frame` itself
(framebuf's methods, GS8 storage, palette expansion at flush).  On
CircuitPython it is a thin class over the 16-bit bitmap mapping the same
method names to `bitmaptools`: `fill` and `fill_rect` to `fill_region`,
`line` to `draw_line`, `circle` to `draw_circle`, `poly` to `draw_polygon`,
`blit` to `blit`, `pixel` to item access, and `text` to `terminalio.FONT`
glyph blits until Phase 3 lands; `set_color` maps the index to a pre-swapped
RGB565 value that drawing writes, so a later `set_color` recolors on
MicroPython only, as Decision 0126 now states.  Canvas primitives record
their dirty bounds for Phase 4.  Verify at build: `draw_circle` against
`framebuf.ellipse(r, r)`, `draw_polygon` outline semantics, terminalio glyph
metrics.  Bench gate: one labeled-card app file drawing identically (font
metrics aside) on S2+CircuitPython, Pico W+CircuitPython, and
Pico W+MicroPython.

## Phase 3. Fonts over the canvas (no viper)

Pre-converted glyph bitmaps placed by one Python layer over two C blit
backends (`FrameBuffer.blit` with a 2-pixel palette; `bitmaptools.blit`).
Needs a host-side font converter; open choice at pickup: adopt the
ecosystem's font-to-py format or a chumicro-native one.  Landing this
retires Decision 0126's per-runtime-font caveat on `text`.

## Phase 4. Dirty-window partial updates

The canvas records the bounds of every primitive it executes, so this is
bookkeeping: the MicroPython flush sends only the strips covering the dirty
rectangle, which means parametrizing the column window (the constant
`_FULL_WIDTH_WINDOW` today); CircuitPython already refreshes dirty regions
in firmware.  Bench gate on the Pico W: a small-region update lands near the
per-strip cost (a full frame is 123 ms there), and the labeled card renders
correctly after mixed partial and full flushes.

## Phase 5. Viper shipping carve-out (tooling; only if phase 6 proceeds)

Measured 2026-08-24 on 1.27.0: arch-neutral `mpy-cross` refuses viper code
(`SyntaxError: invalid arch`), so a viper-bearing module breaks the
`check-size` gate and cannot enter the bundle's `.mpy` channel
(plans/patterns.md records the trap).  Deploys ship `.py` and the rp2/esp32
on-device compilers have viper, so the carve-out is host-tooling only: teach
`check-size` to compile a marked module with `-march` (or measure it
source-only), and ship that module as source inside the `.mpy` bundle
channel.  Build this only when phase 6 is real; a speculative carve-out is
dead tooling.

## Phase 6. Eyes-class rendering demo (viper)

Displacement-map scanline compositing: every output pixel is an indirection
through two lookup tables (polar displacement plus texture), which `blit`
cannot express and viper runs at roughly 100 to 200 ns per pixel, about
10 ms of compositing per 240x240 frame.  The bus is the ceiling: 24 MHz SPI
on the Pico W moves a full frame in ~38 ms (26 fps absolute), 40 MHz on the
S2 in ~23 ms, and phase 4 lets only the moved region transfer.  Target: an
eye at 15+ fps on a Pico W.  Needs a host-side LUT generator for the iris,
sclera, and eyelid tables.  Deliverable is a demo, not library API, unless a
reusable compositor shape falls out.

## Phase 7 (optional). Palettized-BMP loader at the canvas level

An 8-bit BMP maps onto the indexed canvas with no per-pixel math: its color
table becomes `set_color` calls and its pixel rows land by `readinto` into
the GS8 frame on MicroPython and `bitmaptools.arrayblit` on CircuitPython
(rows arrive bottom-up; target slices in reverse).  Small and fast even in
pure Python.  Deferred by user call 2026-08-24; pick up when a project
actually wants on-device images.

## Rejected

- **A shared base class for `GC9A01A` and `GC9A01AIndexed`.**  They repeat
  about 20 lines of constructor and the flush skeleton, and a base would
  save them at the cost of a class object, an MRO lookup per attribute, and
  a shared `__init__` whose two halves differ in every buffer.  Decision
  0126 makes the indexed shape the canvas and the full-color one a native
  extra, so they diverge further in Phase 2.  Two named classes stay.
- **Converging `_strip_bounds` and `_page_windows`, or hoisting the flush
  generator skeleton into `core.py`.**  The two chunking loops encode
  different wire formats, and a shared generator helper would take a
  callable per item, minting a bound method per frame and adding a Python
  call per advance to save four lines per driver.  Each driver keeps its
  own.
- **Sending the GC9A01A column window once per frame.**  CASET is constant
  and the memory-write-continue command would cut the per-strip fixed cost
  by roughly 60 %, about 5 ms of a 123 ms Pico W frame.  The
  self-contained-strip contract (a dropped frame leaves no half-set window)
  is what makes the paced protocol safe, and Phase 4's dirty window needs
  per-strip RASET again, so the strips stay self-contained.
- **`const()` shims in the two displayio modules.**  Each holds one or zero
  private integers read at construction only; the five-line shim costs more
  flash than the dict entries it removes.  `ssd1306.py` and `gc9a01a.py`
  carry the shim because their tables earn it.
- **A Python `__call__` pin wrapper on a CircuitPython framebuf path.**
  Phase 1's `digital_output` wraps `digitalio.DigitalInOut` in a callable,
  which costs a method lookup and a frame per call, about 20 us on an
  rp2040, and `_write_strip` makes eight pin calls per strip.  That is fine
  for the displayio path, which toggles no pins from Python, and moot while
  the framebuf drivers ship to MicroPython only.  A framebuf driver on
  CircuitPython would resolve the pin's `value` attribute once at
  construction instead of calling through the wrapper per strip.
- **JPG decode on MicroPython.**  Huffman plus IDCT is branchy bit-twiddling
  where viper's speedup still lands at seconds per image.  Offline
  conversion (raw RGB565 blobs, or phase 7's palettized BMP) is the answer;
  JPEG stays with custom C firmware, which Decision 0125 excludes.
- **GIF and video on MicroPython.**  No core decoder exists; the supported
  answer is the CircuitPython path (`gifio`), which the displayio slice
  keeps fully open.
- **A retained-mode portable surface.**  Rejected in Decision 0126:
  reimplementing displayio in Python is the slow path Decision 0125 exists
  to avoid.  Apps wanting scene-graph features accept a CircuitPython-only
  branch.

## Validation history

- 2026-08-24: created and parked.  Planned from the GC9A01A matrix bench
  session (all four cells validated the same day); no slice code exists yet.
- 2026-08-24: Decisions 0126 (indexed-palette canvas) and 0127 (pins by
  GPIO number) accepted; the pins phase added first and the canvas phase
  made the trunk the later phases hang from.
- 2026-09-04: Phase 1 shipped.  `chumicro_compat.wiring` (`gpio_pin`,
  `digital_output`, `spi_bus`, `i2c_bus`) with 22 host-only tests green on
  CPython and both unix ports; the seven screens and charlcd hardware
  examples and their guide snippets carry GPIO numbers on both runtimes;
  compat 0.4.0 at 1949 B of mpy against the old 1174 B ceiling, of which
  the new module is 1291 B.  No Pico W or S2 was on the bench during the
  session, so the migrated examples have not yet run on a board.
- 2026-09-04: five audits (embedded and code-quality on screens and
  charlcd, plus a first-principles runtime pass) applied in the same
  session.  Measured on the MicroPython unix port before and after: the
  frame's last `handle()` went from 64 B to 0 B through a two-argument
  `next()`; SSD1306 pages now leave in one `writeto` from a stride-laid
  buffer, which retires the 129-byte combined-buffer copy the rp2 port's
  `writevto` adaptor made per page (`extmod/machine_i2c.c`
  `mp_machine_i2c_transfer_adaptor`); a `gc.collect()` ahead of each
  GC9A01A frame allocation cut peak live heap by 8.8 to 15.6 KB in the
  example's import chain; `CharLcd.write` went from 96 B to 0 B per row.
  The two SSD1306 init tables now match command for command.
- 2026-09-04: bench, one screen and one board at a time.  SSD1306 on all
  four cells (S2 CircuitPython 10.2.0, S2 MicroPython 1.27.0, Pico W
  MicroPython 1.28.0, Pico W CircuitPython 10.2.1): clean `deploy-example`
  runs and a visual check of the border, labels, and counter or bar on each.
  On the Pico W MicroPython cell a probe over `mpremote run` timed the stride
  layout at 3.49 ms mean and 3.79 ms worst per page at 400 kHz, with 2288 B
  allocated across twenty frames, which is one generator per frame and
  nothing per advance.  `compat/examples/blink.py` ran clean on the same
  four cells, so the Decision 0127 resolvers hold on both chip families
  under both runtimes.  charlcd hello on the Pico W under both runtimes,
  both rows read.  The rp2 cells needed the examples' S2 numbers switched
  to GP4 and GP5 for the run and switched back, which is the per-board
  wiring edit Phase 1 leaves.  Not run: charlcd on the S2 cells (the wire
  traffic is byte-identical to the validated build, per the audit's
  equivalence probe and the tests).
- 2026-09-04: round TFT on the Pico W under both runtimes.  MicroPython
  1.28.0: the labeled card read right and the indexed counter ran; a probe
  over `mpremote run` timed 6-row strips at 3.07 ms mean and 3.37 ms worst,
  124 ms a frame, 133 B per frame (the generator), 69,584 B for the panel,
  126 KB free after.  CircuitPython 10.2.1: the displayio card and notch
  read right; the jitter probe (`.scratch/probe_cp_gc9a01a_jitter.py`,
  rebooted into with `.scratch/cp_reboot_and_tail.py` since the deploy path
  leaves auto-reload off) gave the table now in
  `plans/field-notes/hardware-traps.md`: 5.5 us per dirty pixel, 318 ms for
  a whole frame, 1.7 ms for a 16x16 notch.  Two more probes on the same
  board settled Phase 2's backend: chunked displayio refresh
  (`.scratch/probe_cp_paths.py`) costs 4.1 ms per 480 pixels and 510 ms a
  frame in any chunk shape, and a 16-bit bitmap streamed over `busio.SPI`
  by hand (`.scratch/probe_cp_direct.py`) crosses in 44 to 65 ms in strips
  of 1.5 to 3.9 ms with a correct card on the panel.  Decision 0126's body
  now names the streamed frame as the CircuitPython backend.  Not run: the
  round TFT on the S2 cells.
