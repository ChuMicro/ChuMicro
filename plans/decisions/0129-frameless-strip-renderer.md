# Decision 0129: The screens renderer paints strips from a scene and holds no frame

Status: `accepted`
Date: `2026-09-13`
Summary: `chumicro-screens` keeps no frame; a scene of bounded items is painted per dirty strip into one small buffer through each runtime's C primitives and streamed, replacing the Decision 0126 canvas.
Related: [Decision 0125](0125-display-libraries.md) (firmware layers and owned drivers; the shared surface it names), [Decision 0126](0126-SUPERSEDED-BY-0129-canvas-indexed-palette.md) (the canvas this supersedes), [Decision 0127](0127-pins-by-gpio-number.md) (pin references), [Decision 0128](0128-fonts-from-font-to-py-modules.md) (fonts, which become items), [Decision 0080](0080-runner-reactor.md) (tick budget), [Decision 0087](0087-generators-for-sequential-io.md) (generator I/O), [Decision 0092](0092-no-backwards-compat-before-publication.md) (pre-1.0 reshaping)

## Context

The Decision 0126 canvas owns a copy of the whole screen: 57,600 bytes at
8 bits or 115,200 at 16 on a 240 by 240 panel, and 460,800 at 16 bits on
a 480 by 480 one, which no board in the target class holds. Everything
built around it exists to fit that copy: the palette and its per-strip
expansion passes, the 16-bit opt-in with its allocation-order recipe, and
dirty bounds kept in Python subclass overrides. RAM grows with the panel,
and on a Pi Pico W the 16-bit frame fits only by getting ahead of the
heap's own growth (the hardware-traps field note carries the mechanism).

A panel over SPI holds its own frame and takes windowed writes, so the
library never needed a copy. A frameless spike on both Pico W cells (the
workstream carries the tables) painted the counter scene in 8-row strips
at 3.9 ms mean and 4.5 ms worst per strip on CircuitPython and 2.6 ms
mean and 2.8 ms worst on MicroPython, with 3.8 KB of buffer and 153 KB
and 181 KB free, where the canvas leaves a CircuitPython Pico W 45 KB.

## Decision

- **No frame.** The panel's memory is the frame. A panel driver is
  bring-up plus one write of `count` rows from a buffer at a row, and it
  draws nothing.
- **A scene of items.** An app builds items with bounds (`left`, `top`,
  `right`, `bottom`) and a `draw(strip)`; the library ships rectangles,
  sprites (a bitmap with a transparent value), text (rendered to a sprite
  when its string changes, in the built-in font or a Decision 0128 font),
  rings and arcs, and lines. Apps mutate items and mark them; they never
  draw.
- **One strip buffer.** `width` by `rows` pixels in the panel's own
  format, a `framebuf.FrameBuffer` on MicroPython and a 16-bit
  `displayio.Bitmap` drawn with `bitmaptools` on CircuitPython. RAM is
  the strip plus the scene, whatever the panel's size.
- **The flush is the Decision 0126 protocol.** `Screen.flush()` returns a
  generator: for each strip band the dirty rectangle touches, clear the
  strip, draw the items whose bounds cross the band, send one
  self-contained transfer, yield. `ScreenService` paces it unchanged. A
  first paint is elapsed time across ticks, never a stall.
- **One C call per item per strip.** That is the budget rule each item
  type meets: a rectangle is one fill, a sprite one blit, text one blit,
  a ring one or two polylines from vertex rows pre-shifted per band.
  Rows per strip is the only tuning knob. On an RP2040 a `bitmaptools`
  call costs about 120 us and a `framebuf` call about 30 us, and an
  8-row strip of a 240-wide panel spends about 2 ms on the bus.
- **Panel-native colors.** `color(red, green, blue)` returns the value
  the panel's format stores, pre-swapped for a 16-bit SPI panel, and an
  item holds it. There is no palette layer; a recolor sets the value and
  marks the item.
- **Firmware quirks stay inside the strip canvas.** `bitmaptools.draw_circle`
  clamps a center outside the bitmap, so curves are polylines. The mono
  OLED on CircuitPython keeps its displayio factory, since nothing in C
  packs its vertical byte order. The displayio factories remain the
  CircuitPython-native path per Decision 0125.

Rejected alternatives:

- **A frame in RAM at any depth.** A 4-bit or 1-bit frame still grows
  with the panel and still needs an expansion pass per strip.
- **Native layers per runtime with only the pacer shared.** The least
  library code, and every app carries two drawing idioms; the shared
  scene is what keeps one drawing file per app.
- **The shared scene rendered through displayio on CircuitPython.** Two
  renderers to keep in step, and displayio's refresh stalls the loop for
  the whole dirty area at about 6 us per pixel.
- **Whole polygons per strip for curves.** `draw_polygon` walks every
  edge for every strip, 2.9 ms for a 96-vertex ring; per-band arcs cost
  one or two calls and 848 bytes.

## Consequences

- `chumicro_screens` loses both canvases, `GC9A01AIndexed`, `GC9A01A`,
  `frame_bits`, `bitmap=`, and the expansion passes, and gains `Screen`,
  two strip canvases, and the item types, in one commit under Decision
  0092. The workstream carries the phases and the bench gates.
- `Font` draws into a text sprite instead of onto a frame.
- The SSD1306 on MicroPython becomes a page-strip panel under the same
  `Screen`; a wider SPI panel needs a driver and a wider strip, nothing
  else. RGB-interface panels stay out of scope: they take no window
  write, and CircuitPython's `dotclockframebuffer` covers them natively
  on boards with PSRAM.
- Apps describe a scene and mutate items; no app carries framebuf
  drawing calls, and none allocates a frame ahead of its imports.
