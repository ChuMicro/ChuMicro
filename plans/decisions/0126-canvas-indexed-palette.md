# Decision 0126: The portable canvas is indexed-palette

Status: `accepted`
Date: `2026-08-24`
Summary: The portable canvas speaks framebuf vocabulary with palette indexes; `set_color` owns color; backends are GS8 framebuf (MicroPython) and indexed `displayio.Bitmap` + `bitmaptools` (CircuitPython).
Related: [Decision 0125](0125-display-libraries.md) (the firmware-layer criterion and the protocol this refines), [Decision 0080](0080-runner-reactor.md) (tick budget), [Decision 0051](0051-runner-shaped-as-project-policy.md) (runner shape), [Decision 0092](0092-no-backwards-compat-before-publication.md) (pre-1.0 reshaping), [Decision 0127](0127-pins-by-gpio-number.md) (portable pin references)

## Context

Decision 0125 decided the shared drawing protocol (framebuf's method
vocabulary, implemented over `displayio.Bitmap` with `bitmaptools` on
CircuitPython) but left the color model and the loop shape open. The shipped
MicroPython drivers exposed the gap: `GC9A01A.frame` takes pre-swapped RGB565
from `color565`, a byte-order detail no CircuitPython app should see, while
`GC9A01AIndexed` and `displayio.Palette` both already speak indexed color.
App drawing code cannot run unchanged on both runtimes while colors differ
per runtime.

## Decision

- The portable surface (the canvas) is framebuf's method vocabulary with
  **palette indexes as the color arguments**: `fill`, `pixel`, `fill_rect`,
  `rect`, `line`, `circle`, `poly` (outline), `blit`, `text`. The protocol
  admits only methods with C backing on both runtimes; `bitmaptools`
  (`fill_region`, `draw_line`, `draw_circle`, `draw_polygon`, `blit`) fixes
  today's set.
- `set_color(index, red, green, blue)` is the only color entry point: 8-bit
  channels in, backend-private conversion out (pre-swapped RGB565 on
  MicroPython, `displayio.Palette` on CircuitPython). Raw color values
  (`color565`) are a MicroPython-native extra outside the protocol.
- Backends: MicroPython is a GS8 `framebuf.FrameBuffer` expanded through a
  palette blit (the `GC9A01AIndexed` shape); CircuitPython is an 8-bit
  indexed `displayio.Bitmap` with a `displayio.Palette` in a full-screen
  `TileGrid`.
- One runner-shaped service facade on both runtimes: `show()`,
  `check(now_ms)`, `handle(now_ms)`, `next_deadline(now_ms)` are the loop
  contract everywhere, near-no-ops on CircuitPython where the firmware
  refreshes. App loop code is identical across runtimes.
- Canvas primitives record their dirty bounds; refresh strategies consume
  them backend-side without app changes.
- `text` promises call-shape portability, not pixel-identical output: each
  backend renders its runtime's built-in font until a cross-runtime font
  layer lands.
- Construction stays injected (bus and pin objects, Decision 0010); the
  [Decision 0127](0127-pins-by-gpio-number.md) resolvers shrink it to shared
  GPIO numbers, and full portability begins at the canvas.
- Runtime-native bonuses (full-RGB framebuf drawing, displayio scene graphs,
  `gifio`, `jpegio`) stay reachable beneath the canvas and are never wrapped.

Rejected alternatives:

- **Full-color RGB565 as the portable baseline** — excludes the 256 KB
  minimum board class and drags byte order into app code; indexed is the
  model both firmware layers implement natively. A PSRAM-class full-color
  canvas may arrive later as an extra, never as the baseline.
- **A retained-mode (scene graph) portable surface** — reimplements
  displayio in Python on MicroPython, the slow path Decision 0125 exists to
  avoid.
- **Capability probes on one canvas class** — protocols are duck-typed per
  Decisions 0124 and 0125; a backend either implements the canvas or is not
  a canvas.

## Consequences

- `chumicro-screens` grows the canvas protocol and its CircuitPython
  backend; `GC9A01AIndexed` is already the MicroPython shape. Pre-1.0
  surfaces reshape freely under Decision 0092.
- Fonts, image loading, and dirty-window refresh each land once at the
  canvas level and serve both runtimes
  ([workstream](../workstreams/screens-capability-slices.md)).
- An app's drawing and loop code can be one shared file; examples stay
  runtime-prefixed wherever they construct hardware.
