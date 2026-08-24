# Workstream: screens capability slices

Status: **parked until the current display bench round lands** (user call
2026-08-24).  Planned during the GC9A01A matrix validation session so a cold
pickup has the shapes, the measured constraints, and the order.

## Why

The capability ledger against the display ecosystem, measured during the
matrix bench:

- **CircuitPython needs nothing from this file.**  `gc9a01a_displayio.make_display`
  returns a real `busdisplay.BusDisplay`, so the firmware and library
  ecosystem work unmodified: proportional fonts (`terminalio`,
  `adafruit_display_text`), automatic dirty-region partial refresh, `jpegio`
  and `gifio` decoders in core, and sprite-move animation.
- **MicroPython's comparable class** (pure-Python drivers on standard
  firmware) shares our drawing floor, framebuf's C primitives, and blocks the
  loop for the full refresh, which `ScreenService` exists to fix.  The real
  gaps against those libraries are fonts and partial updates.  Both are
  additive slices; the duck-typed panel protocol survives every phase below.

## Phase 1. Fonts on MicroPython (no viper)

Pre-converted glyph bitmaps blitted into `frame` through `FrameBuffer.blit`,
which runs in C; a mono glyph blits with a 2-pixel palette FrameBuffer in the
destination format, the same conversion trick `GC9A01AIndexed` ships.  Python
only orchestrates per-glyph placement, so a text line costs microseconds per
glyph.  Deliverable: a Writer-style helper over the duck-typed `frame`
(works for `GC9A01A`, `GC9A01AIndexed`, and future framebuf panels) plus a
host-side font converter.  Open choice at pickup: adopt the ecosystem's
font-to-py format for compatibility, or a chumicro-native format the
converter owns end to end.

## Phase 2. Dirty-window partial updates

Bookkeeping, no viper: the driver tracks one dirty rectangle (an explicit
`mark_dirty(x, y, width, height)` beats wrapping every drawing call) and
`flush()` sends only the strips covering it.  The strip machinery already
does windowed row sends; the new part is parametrizing the column window,
which is the constant `_FULL_WIDTH_WINDOW` today.  Bench gate on the Pico W:
a small-region update should land near the per-strip cost (a full frame is
123 ms there; a 40x40 region should cost a few ms), and the labeled card
must still render correctly after mixed partial and full flushes.

## Phase 3. Viper shipping carve-out (tooling; only if phase 4 proceeds)

Measured 2026-08-24 on 1.27.0: arch-neutral `mpy-cross` refuses viper code
(`SyntaxError: invalid arch`), so a viper-bearing module breaks the
`check-size` gate and cannot enter the bundle's `.mpy` channel
(plans/patterns.md records the trap).  Deploys ship `.py` and the rp2/esp32
on-device compilers have viper, so the carve-out is host-tooling only: teach
`check-size` to compile a marked module with `-march` (or measure it
source-only), and ship that module as source inside the `.mpy` bundle
channel.  Build this only when phase 4 is real; a speculative carve-out is
dead tooling.

## Phase 4. Eyes-class rendering demo (viper)

Displacement-map scanline compositing: every output pixel is an indirection
through two lookup tables (polar displacement plus texture), which `blit`
cannot express and viper runs at roughly 100 to 200 ns per pixel, about
10 ms of compositing per 240x240 frame.  The bus is the ceiling: 24 MHz SPI
on the Pico W moves a full frame in ~38 ms (26 fps absolute), 40 MHz on the
S2 in ~23 ms, and phase 2 lets only the moved region transfer.  Target: an
eye at 15+ fps on a Pico W.  Needs a host-side LUT generator for the iris,
sclera, and eyelid tables.  Deliverable is a demo, not library API, unless a
reusable compositor shape falls out.

## Phase 5 (optional). Palettized-BMP loader for GC9A01AIndexed

An 8-bit BMP maps onto the indexed driver with no per-pixel math: its color
table becomes `set_color` calls and its pixel rows `readinto` straight into
the GS8 frame (rows arrive bottom-up; target the buffer slices in reverse).
Small and fast even in pure Python.  Deferred by user call 2026-08-24; pick
up when a project actually wants on-device images.

## Rejected

- **JPG decode on MicroPython.**  Huffman plus IDCT is branchy bit-twiddling
  where viper's speedup still lands at seconds per image.  Offline
  conversion (raw RGB565 blobs, or phase 5's palettized BMP) is the answer;
  JPEG stays with custom C firmware, which Decision 0125 excludes.
- **GIF and video on MicroPython.**  No core decoder exists; the supported
  answer is the CircuitPython path (`gifio`), which the displayio slice
  keeps fully open.

## Validation history

- 2026-08-24: created and parked.  Planned from the GC9A01A matrix bench
  session (all four cells validated the same day); no slice code exists yet.
