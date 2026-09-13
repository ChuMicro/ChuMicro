# Workstream: screens frameless renderer

Status: **active**, Phases 0, 1, and 3 shipped, Phase 2 folded into
Phase 1 for the OLED's MicroPython half, Phase 4 waiting on a panel.
[Decision 0129](../decisions/0129-frameless-strip-renderer.md) pins the
design: no frame in RAM, a scene of bounded items painted per dirty
strip into one small buffer through each runtime's C primitives and
streamed under `ScreenService`.  It replaces the canvas that
[screens-capability-slices.md](screens-capability-slices.md) built in its
Phases 2 to 4; that workstream's pin resolvers (Phase 1) and font format
(Phase 3) stand.

## Why

The maintainer's ask, restated at the planning session: a library that
works with the runner's tick and generator cadence, supports pixel
panels of several kinds on MicroPython and CircuitPython, and stays
maintainable.  The canvas failed the last two.  It owned a whole frame,
so its RAM grew with the panel (a 480 by 480 panel at 16 bits is
460,800 bytes), and everything around it existed to fit that copy: the
palette with its per-strip expansion passes, the 16-bit opt-in that
only fit a Pi Pico W through allocation-order recipes, dirty bounds
kept in Python subclass overrides at 140 us a call.  A panel over SPI
holds its own frame and takes windowed writes, so the copy was never
needed.  A first paint that takes elapsed time is fine; the loop stays
live through it.

## Measured

Spike `.scratch/spike_strips3.py` (staged with `.scratch/build_stage.py`,
CircuitPython through `chumicro-deploy deploy --directory`, MicroPython
through `mpremote run`), Pi Pico W under CircuitPython 10.2.1 and
MicroPython 1.28.0, 8-row full-width strips of a 240-wide 16-bit panel,
nothing wired (the bus timing does not depend on a panel answering;
the visual check is Phase 1's gate).  The scene is the counter's ring,
caption, and count.

| Case | CircuitPython | MicroPython |
|---|---|---|
| full paint, 3 items | 30 advances, 3.9 ms mean, 4.5 ms worst, 116 ms | 30 advances, 2.6 ms mean, 2.8 ms worst, 77 ms |
| count band, 56 by 12 | 2 advances, 4.5 ms mean, 9 ms | 2 advances, 2.8 ms mean, 5 ms |
| full paint, 23 items | 4.1 ms mean, 5.9 ms worst, 122 ms | 2.7 ms mean, 4.1 ms worst, 82 ms |
| allocated per frame | 5,024 B | 128 B |
| free with the scene | 153 KB | 181 KB |

The strip buffer is 3,840 bytes and the ring's per-band arcs 848 bytes
on CircuitPython.  For comparison the canvas's 16-bit frame streamed
6-row strips at 1.6 ms and a frame in 64 ms from 115 KB, and its 8-bit
frame 3-row strips at 3.5 ms and a frame in 282 ms from 57.6 KB, with
the count band at 4.1 ms and 13.5 ms.

The cost model the design rests on: the bus takes about 2 ms of every
8-row strip at 24 MHz, a `bitmaptools` call about 120 us and a
`framebuf` call about 30 us on this RP2040.  The first spike pass drew
the ring as 16 span fills per strip and each glyph through three calls,
and read 4.5 ms mean and 8.2 ms worst; the second drew the ring as one
96-vertex `draw_polygon` per strip, which walks every edge every time,
and read 5.9 ms mean; the third keeps per band only the arcs whose
edges cross it and renders text into a sprite once per change, one
call each per strip.  The 5 KB CircuitPython allocation per frame is
about 170 bytes per strip of unknown origin, likely the keyword
arguments of `bitmaptools.blit`; MicroPython's 128 bytes is the
generator.

## Design

- **Panel.** Bring-up plus `write_rows(row, count, buffer)` as one
  self-contained transfer (window commands, then pixel data), later a
  windowed variant for narrow dirty rectangles.  No drawing.
- **Strip canvases.** `FramebufStrip` on MicroPython and `BitmapStrip` on
  CircuitPython hold `width` by `rows` pixels in the panel's format and
  a `top` row, and expose one primitive set: `clear`, `fill_rect`,
  `blit` of a sprite with a transparent value, `polyline`, and built-in
  `text`.  The runtime split lives here and nowhere else.
- **Items.** One class per type on both runtimes, each with `left`,
  `top`, `right`, `bottom` as attributes and `draw(strip)`: `Rect`,
  `Sprite`, `Text` (built-in font or a Decision 0128 `Font`, rendered to
  a sprite when the string changes), `Ring` (per-band arcs; `ellipse` on
  MicroPython), `Line`.  Each costs one C call per strip it crosses.
- **Screen.** Holds the items, the dirty union, and the strip;
  `flush()` is the `ScreenService` protocol.  Marking is explicit
  (`mark_item`, `mark`) in the spike; Phase 1 decides whether item
  setters mark old and new bounds themselves.
- **Colors.** `color(red, green, blue)` per panel format, pre-swapped
  for 16-bit SPI panels.  No palette.
- **Mono panels.** The SSD1306 on MicroPython is a page-strip panel: the
  strip is one 128 by 8 `MONO_VLSB` page of 128 bytes.  On CircuitPython
  it stays on the displayio factory, since nothing in C packs the
  vertical byte order.

## Phase 0. Spike on both Pico W cells: shipped

The three passes above on CircuitPython and one on MicroPython.
Decision 0129 accepted, Decision 0126 superseded, Decision 0125's
canvas paragraph edited in place.

## Phase 1. The library: shipped

`Screen` with `Rect`, `Box`, `Line`, `Ring`, `Text`, and `Sprite`;
`FramebufStrip` and `BitmapStrip`; `gc9a01a.GC9A01A` reduced to
bring-up plus `write_strip`; `ssd1306.SSD1306` as a page-strip panel
on MicroPython under the same `Screen` (the OLED half of Phase 2,
pulled forward because that panel was on the bench first); `Font`
drawing into a strip on MicroPython and into a `Text` sprite on
CircuitPython.  `framebuf_canvas.py`, `bitmap_canvas.py`,
`GC9A01AIndexed`, the old full-color `GC9A01A`, `frame_bits`,
`bitmap=`, the expansion passes, and `micropython_gc9a01a_round.py`
are gone.  The examples are scenes, the guide and README describe the
scene, `plans/patterns.md` carries the strip-canvas entry in place of
the framebuf-subclass one, and screens is 0.4.0.  Two design rules
came out of the bench: rendering that costs C calls per glyph or per
vertex happens at mark time (`prepare_text`, `prepare_ring` on the
strip), so an advance is the bus plus one call per item; and the
CircuitPython strip clears with `displayio.Bitmap.fill`, since
`bitmaptools` costs per pixel touched rather than per call.  Bench
gate: by-eye checks on the OLED and the round TFT on both Pico W
cells, recorded in the validation history.

## Phase 2. The mono OLED on CircuitPython

Open only if a C packer for the panel's vertical byte order appears;
until then the displayio factory is the CircuitPython path.

## Phase 3. Narrow flushes: shipped

`Screen.flush` windows every strip to the dirty rectangle's columns:
`strip.window(left, right)` at the start of a flush and
`write_strip(top, count, left, right)` per strip.  `FramebufStrip`
built `narrowable=True` lays a `FrameBuffer` of the window's width
over the same bytes, so its `view` is the whole transfer and
`machine.SPI.write` sends it as it is, one `FrameBuffer` and one view
per narrow flush; `BitmapStrip` paints full width and `GC9A01A` on
CircuitPython sends each row through `busio.SPI.write`'s `start` and
`end`, allocating nothing.  The page panels ignore the columns, since
their page bytes sit behind a control byte in one buffer and a column
window would cost a copy per page.  The allocation floor turned out
to be the timing probe's own `monotonic_ns` integers: the shipped
flush allocates its generator and nothing per advance on either
runtime.  A `PCD8544` driver for the Nokia 5110 LCD, the SSD1306's
shape over SPI with six 84-byte banks, is written with its example and
tests and parked in `.scratch/pcd8544_pending/` until its module is on
the bench, since Decision 0125 ships a driver only once it has passed
on hardware.

## Phase 4. A second SPI TFT

A 320 by 240 or 480 by 320 TFT (ST7789, ILI9341, ILI9488) when one is
on the bench: a driver of bring-up plus `write_strip`, a strip width
from the panel, and the same scene.  ILI9488 over SPI takes 18-bit
pixels, so its strip is a third wider and its `color565` packs
differently.  No such panel is on the bench, so this phase waits.

## Rejected

- **A frame at any depth, a displayio adapter for the shared scene, and
  native layers per runtime.**  Decision 0129 records each.
- **DMA background writes** (`rp2.DMA` on MicroPython, `rp2pio`
  background writes on CircuitPython) to take the bus time off the tick.
  Port-specific and a second transport per runtime; a later accelerator
  if a project needs more than the strip budget gives, not part of the
  base design.

## Validation history

- 2026-09-13: created from the from-scratch planning session.  The
  three heap runs first (hardware-traps.md), then the spike in three
  passes on the CircuitPython Pico W (4.5 and 8.2 ms, 5.9 and 6.7 ms,
  3.9 and 4.5 ms mean and worst per strip) and once on the MicroPython
  Pico W (2.6 and 2.8 ms).  Phase 0 closed; Decision 0129 accepted.
- 2026-09-13: Phase 1 shipped and benched.  MicroPython Pico W
  (1.28.0), SSD1306 on GP4 and GP5, through `mpremote run`: the
  counter and the font counter ran clean for twelve frames each; the
  probe (`.scratch/probe_oled_strips_mp.py`) measured 8 pages at
  4.07 ms mean and 4.22 ms worst, 32 ms a frame, the count line at 2
  pages and 8 ms, 144 bytes a frame and nothing per advance.  Round
  TFT through the shipped package (`.scratch/probe_gc9a01a_screen.py`,
  nothing wired): MicroPython 2.6 ms mean and 2.9 ms worst per 8-row
  strip, 78 ms a frame, count strips 2 at 2.9 ms, the eleven-item
  card at 2.9 and 3.3 ms, 144 bytes a frame; CircuitPython (10.2.1,
  staged through `chumicro-deploy deploy --directory`) 2.8 and 3.7 ms,
  84 ms, count strips 2 at 3.5 ms, the card at 3.6 and 4.7 ms, 176
  bytes a frame by the step probe (`.scratch/probe_strip_alloc_cp.py`;
  the timing probe's own `monotonic_ns` integers add 5 KB).  The
  per-call probes (`.scratch/probe_strip_cost_cp.py`, `_mp.py`) gave
  the cost model in the patterns entry: `bitmaptools` per pixel
  (`fill_region` 1,330 us for a 240 by 8 clear against 130 us for
  `Bitmap.fill`), `framebuf` 60 to 370 us a call, the bus 1.2 to
  1.6 ms per strip.  Two CircuitPython quirks found on the way:
  `fill_region` and `blit` raise on coordinates past the bitmap, so
  the strip clips in Python, and the first pass rendered text and cut
  arcs inside the first flush (8 to 14 ms worst), which moved to mark
  time.  88 tests on CPython, 85 on each unix port.
- 2026-09-13: Phase 3 shipped and the bench closed on both cells.
  Column windows on the round TFT, `PCD8544` as a second page-strip
  panel, the strip write's lock inlined, screens back to 0.1.0 as the
  version of first publication (the branch had laddered 0.2.0 to
  0.4.0 across phases on a package never released).  97 tests on
  CPython, 95 on each unix port.  By eye, the maintainer's read:
  MicroPython Pico W with the OLED on GP4 and GP5 and the TFT on
  GP6 to GP10 at once, the card's labels each on their own color in a
  white ring, the counter ticking inside a steady ring, the font
  counter's digits centered in the 20-pixel face, the OLED counters
  right; the TFT counter then deployed as `main.py` through
  `chumicro-deploy deploy --transport micropython` and counting from
  flash.  CircuitPython Pico W (10.2.1) with the TFT moved over, the
  same three through `chumicro-deploy deploy --directory`, all clean
  to frame 19 in their tails, the counter read by eye, the font
  counter's 20-pixel text the same bitmaps and its built-in tag
  narrower and taller as documented.  The PCD8544 driver waits in
  `.scratch/pcd8544_pending/` for its module to be wired.
