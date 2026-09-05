# Workstream: screens capability slices

Status: **active**, Phases 1 to 3 shipped and Phase 4 next.  Planned during the
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

## Phase 2. Canvas protocol and the CircuitPython backend (Decision 0126): shipped

Shipped as one slice.  `chumicro_screens.gc9a01a` is cross-runtime: the
frame backend is chosen by whether `framebuf` imports, `GC9A01AIndexed`
speaks the same palette-index vocabulary on both runtimes, and on
CircuitPython its `frame` is `chumicro_screens.bitmap_canvas.BitmapCanvas`,
a CircuitPython-marked module so MicroPython boards never carry it.  The
streamed strips take a `busio` lock per transfer.  `ScreenService` selects
its advance once at import, because CircuitPython board builds leave the
two-argument `next()` out (the unix port has it, which is why no host lane
caught the `TypeError` the Pico W raised).  `gc9a01a_card.py` and
`gc9a01a_counter.py` are one file each for both runtimes.  Dirty-bounds
recording did not land with the canvas; it is Phase 4's own bookkeeping.
The Pico W bench settled the backend: displayio's
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

## Phase 3. Fonts over the canvas (no viper): shipped

`chumicro_screens.fonts.Font` wraps a font-to-py module
([Decision 0128](../decisions/0128-fonts-from-font-to-py-modules.md)
settled the format on the ecosystem's, with no chumicro converter) and
draws it at the same pixels on both runtimes: `text(canvas, string,
x, y, index)` and `width(string)`.  On MicroPython each glyph blits
straight from the module's read-only bytes, because `FrameBuffer.blit`
takes a `(buffer, width, height, MONO_HLSB)` list as its source, through
a two-entry GS8 palette whose background entry is the skipped key (the
key compares after the palette lookup).  On CircuitPython the glyphs are
loaded once at construction into a 1-bit `displayio.Bitmap` sheet, each
through `bitmaptools.readinto` into a stamp bitmap and one blit, and
drawn through `BitmapCanvas.blit_bits`, the three-call scratch path the
built-in `text` now shares.  `gc9a01a_font_counter.py`
plus `sans20.py` (DejaVu Sans at 20 px, font-to-py output checked in
beside the example so the deploy ships it) is the example.  The canvas's
own `text` keeps its per-runtime built-in font; Decision 0126 says so
and points at 0128 for pixel-identical text.

## Phase 3a. The 8-bit CircuitPython frame: shipped

The 16-bit CircuitPython frame left a Pi Pico W about 43 KB for
everything else, too little for a screen beside wifi and MQTT, and
made every module compiled ahead of the panel a threat to its 115 KB
block.  `GC9A01AIndexed` now defaults to an 8-bit `displayio.Bitmap`
on CircuitPython too (`frame_bits=8`; `frame_bits=16` keeps the
earlier shape), drawn with `bitmaptools` as indexes through a
`BitmapCanvas` whose `colors` is the identity, and expanded per strip
at flush: a raw `bitmaptools.blit` into a 16-bit strip bitmap, then one
`replace_color` pass per assigned color.  A color whose pre-swapped
value is below 256 could be mistaken for an index by a later pass, so
`_expansion_passes` moves such indexes to temporaries above 255 that no
color uses, maps the rest directly, and maps the temporaries last; an
index equal to its own color (black at 0) needs no pass, and the plan
is rebuilt once per frame after a `set_color`.  `set_color` therefore
recolors drawn pixels on CircuitPython as on MicroPython, and the
canvas's scratch bitmap now belongs to the canvas, sized to its frame's
depth and grown to the largest glyph drawn.  The default strip drops to
3 rows on that path.  `ulab`, the other candidate for the expansion,
allocates on every array operation (Decision 0126 records the
measurement), so it is out.

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
  wiring edit Phase 1 leaves.  The S2 charlcd cells keep their earlier
  pass: the rewrite's wire traffic is byte-identical to the validated
  build, per the audit's equivalence probe and the tests, so the rp2 runs
  close it.
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
  now names the streamed frame as the CircuitPython backend.  The S2 round
  TFT cells keep their earlier pass: the driver has no board branch, so
  the Pico W runs close both runtimes.
- 2026-09-04: Phase 2 shipped and benched on the CircuitPython Pico W.
  `gc9a01a_card.py` drew the labeled card right through `BitmapCanvas`
  (ring, bars, and text in the built-in font) and `gc9a01a_counter.py`
  counted under `ScreenService`; the first run raised `TypeError` from the
  two-argument `next()` the sentinel advance used, which the board build
  lacks, so `core.py` now picks its advance at import.  A probe through
  the shipped driver (`.scratch/probe_gc9a01a_timing_cp.py`) measured
  6-row strips at 1.43 ms mean and 1.95 ms worst across two runs, 62 ms
  a frame, 128 B per frame (the generator) and nothing per advance,
  129,200 B for the panel and 45 KB free after; the run straight after a
  USB write of the drive showed one 6 ms strip, the host servicing the
  drive.  65 tests on CPython, 53 on the MicroPython port, and 48 on the
  CircuitPython port.  The MicroPython branch is closed by the port tests,
  which drive it through a fake SPI, and by the earlier run on the
  MicroPython Pico W, whose pin and bus calls the refactor kept.
- 2026-09-05: Phase 3 shipped and benched on the CircuitPython Pico W
  (10.2.1).  The first deploy raised `MemoryError` allocating the frame,
  and so did the known-good `gc9a01a_counter.py` on the same board: the
  boot straight after a host write has about 50 KB less heap than the
  next soft reboot (hardware-traps.md carries the numbers), so every
  run below is the second boot after its write.  A probe through the
  shipped driver (`.scratch/probe_font_cp.py`, panel constructed before
  the font module is imported) measured `Font.text` on the 7-glyph
  "seconds" in DejaVu Sans 20 at 7.4 ms mean and 8.4 ms worst, 1.06 ms
  a glyph, 0 bytes per call; the sheet build took 157 ms once; the font
  cost 4,400 B plus 4,704 B for the module, with 32.5 KB free after the
  panel, canvas, and font.  Before two changes the same probe read
  9.7 ms mean, 5,200 B, and 305 ms: the sheet build went from 1,920
  row-slice copies to one `readinto` and one blit per glyph, and
  `blit_bits` recolors in one pass unless the text is black.  Importing
  `chumicro_screens.fonts` and the 17 KB `sans20.py` ahead of the panel
  left no 115,200-byte block even on a clean boot (a heap probe with the
  same imports and a collection between each found the block, so it is
  the compile garbage interleaving with the next module's objects); with
  both imports after the panel the example ran on three consecutive
  boots, and the guide and docstring carry that order.  82 tests on
  CPython, 63 on the MicroPython port (real framebuf drawing the
  list-form source), and 58 on the CircuitPython port.
- 2026-09-05: Phase 3 benched on the MicroPython Pico W (1.28.0).
  `deploy-example` ran `gc9a01a_font_counter.py` clean, nine frames in
  the capture, and the panel read right on both cells.  The probe
  (`.scratch/probe_font_mp.py` over `mpremote run`) measured the same
  7-glyph `Font.text` at 3.96 ms mean and 4.20 ms worst, 0.57 ms a
  glyph, 560 B per call (80 B a glyph: the module's `get_ch` returns a
  tuple and a memoryview slice, and the string iteration a character),
  the font object at 592 B plus 4,768 B for the module, construction
  37 ms (96 `get_ch` calls for the width table), and 117.7 KB free
  after the panel and font.
- 2026-09-05: Phase 3a shipped and benched on the CircuitPython Pico W
  (10.2.1), every probe staged through `chumicro-deploy deploy` after
  the session's hand copies were found to leave `._code.py` on the
  drive and a smaller boot heap (hardware-traps.md).  The standalone
  expansion probe (`.scratch/probe_expand_cp.py`) put the raw 8-bit to
  16-bit strip copy at 1.98 ms for 6 rows and 1.07 ms for 3, each
  `replace_color` pass at 0.83 ms and 0.43 ms, a 4-bit frame's copy
  slower than 8-bit, and `ulab`'s mask expansion at 6.7 ms and 12 KB of
  allocation for seven colors on a 6-row strip.  Through the shipped
  driver (`.scratch/probe_indexed8_cp.py`, three warm-up frames) the
  default 3-row advance measured 2.5 ms mean and 3.4 ms worst with
  black and white (209 ms a frame), 4.4 and 5.4 ms with four more
  colors (358 ms), 6.1 and 6.9 ms with seven (492 ms), 0 bytes across
  ten advances every time; the panel took 70.9 KB and left 97.8 KB
  free, the 20-pixel font 5.4 KB more, and a `set_color` recolored the
  ring and count on the panel without a redraw.  The counter example's
  import chain plus a 16-bit frame allocated on the deploy's own boot
  with 30 KB free, so the earlier first-boot failures stay unexplained
  and the font example imports at the top again.  93 tests on CPython,
  63 on the MicroPython port, 58 on the CircuitPython port.
