# Workstream: screens frameless renderer

Status: **active**, Phase 0 shipped, Phase 1 next.
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

## Phase 1. The library

`Screen`, `FramebufStrip`, `BitmapStrip`, the five item types, and
`gc9a01a.GC9A01A` reduced to bring-up plus `write_rows`.  Delete
`framebuf_canvas.py`, `bitmap_canvas.py`, `GC9A01AIndexed`, the old
`GC9A01A`, `frame_bits`, `bitmap=`, and the expansion passes; `Font`
renders into a `Text` sprite on both runtimes.  Tests on CPython through
fakes and on both unix ports through the real primitives.  Rewrite
`gc9a01a_card.py`, `gc9a01a_counter.py`, and `gc9a01a_font_counter.py`
as scenes, the guide and README with them, and drop the framebuf
subclass entry from `plans/patterns.md`.  Screens bumps to 0.4.0.  Gate:
the card and the counter by eye on both Pico W cells with the panel
wired, per-strip timing within the spike's numbers, zero bytes per
advance on MicroPython, and the CircuitPython per-strip allocation
named.

## Phase 2. The mono OLED as a page-strip panel

`ssd1306.SSD1306` on MicroPython under the same `Screen` with a 1-bit
strip, `micropython_ssd1306_font_counter.py` as a scene, the displayio
factories unchanged.

## Phase 3. Narrow flushes and the allocation floor

Window each strip to the dirty rectangle's columns (row-wise `busio`
writes on CircuitPython, a re-laid strip on MicroPython, as the canvas
did), and take the CircuitPython per-strip allocation to zero.  Document
`rows` with the cost model so an app with many items per strip knows
which way to turn it.

## Phase 4. A second SPI panel

A 320 by 240 or 480 by 320 TFT (ST7789, ILI9341, ILI9488) when one is
on the bench: a driver of bring-up plus `write_rows`, a strip width from
the panel, and the same scene.  ILI9488 over SPI takes 18-bit pixels, so
its strip is a third wider and its `color` packs differently.

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
