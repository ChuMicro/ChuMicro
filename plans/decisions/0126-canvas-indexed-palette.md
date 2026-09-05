# Decision 0126: The portable canvas is indexed-palette

Status: `accepted`
Date: `2026-08-24`
Summary: Portable canvas: framebuf vocabulary with palette indexes and `set_color`; GS8 framebuf on MicroPython, a 16-bit `displayio.Bitmap` streamed over SPI on CircuitPython, paced by `ScreenService`.
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
  channels in, backend-private conversion out, pre-swapped RGB565 on both
  runtimes. Raw color values (`color565`) are a MicroPython-native extra
  outside the protocol. On MicroPython a later `set_color` recolors every
  drawn pixel holding the index from the next flush; on CircuitPython it
  applies to later drawing only, because that frame holds colors rather
  than indexes.
- Backends: MicroPython is a GS8 `framebuf.FrameBuffer` expanded through a
  palette blit (the `GC9A01AIndexed` shape). CircuitPython is a 16-bit
  `displayio.Bitmap` drawn with `bitmaptools` in the panel's byte order and
  streamed strip by strip over `busio.SPI` from its own buffer, with the
  panel brought up and windowed by hand exactly as the MicroPython drivers
  do. displayio's refresh pipeline is not in the path: on an RP2040 it costs
  about 6 us per dirty pixel however the frame is chunked (318 ms for a
  whole 240x240 frame in one stall, 510 ms in tick-sized chunks), while the
  streamed frame crosses in 44 to 65 ms in strips under 4 ms; the
  hardware-traps field note carries the tables.
- One runner-shaped service on both runtimes: `ScreenService` drives the
  same `flush()` protocol everywhere, so `show()`, `check(now_ms)`,
  `handle(now_ms)`, and `next_deadline(now_ms)` are the loop contract on
  both, and app loop code is identical across runtimes. Apps that want
  displayio's scene graph use the displayio factories instead and take its
  refresh cost.
- Canvas primitives record their dirty bounds; refresh strategies consume
  them backend-side without app changes.
- The canvas's own `text` promises call-shape portability, not
  pixel-identical output: each backend renders its runtime's built-in font.
  Pixel-identical text is a converted font drawn through the font layer,
  [Decision 0128](0128-fonts-from-font-to-py-modules.md).
- Construction stays injected (bus and pin objects, Decision 0010); the
  [Decision 0127](0127-pins-by-gpio-number.md) resolvers shrink it to shared
  GPIO numbers, and full portability begins at the canvas.
- Runtime-native bonuses (full-RGB framebuf drawing, displayio scene graphs,
  `gifio`, `jpegio`) stay reachable beneath the canvas and are never wrapped.

Rejected alternatives:

- **Full-color values as the portable vocabulary** — drags byte order into
  app code, and on MicroPython a full-color frame excludes the 256 KB board
  class. Indexes are what apps speak on both runtimes; what the backend
  stores is its own business. The CircuitPython backend stores 16-bit
  pixels because the firmware offers no C-speed palette expansion outside
  displayio's pipeline, and a Pico W's larger CircuitPython heap holds the
  117 KB frame with about 43 KB to spare, driver code included, when it is
  allocated first.
- **Pacing displayio by chunked refresh** — a shadow bitmap copied into the
  displayed one about 480 pixels per advance fits the tick (4.1 ms mean on
  an RP2040) but takes 510 ms per frame and stores the frame twice, a
  quarter the speed of the streamed frame. Recorded in the field note.
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
- The CircuitPython backend's frame is the largest allocation an app makes
  on a 256 KB board, so it is constructed before anything else, the same
  rule `GC9A01AIndexed` already carries.
- Fonts, image loading, and dirty-window refresh each land once at the
  canvas level and serve both runtimes
  ([workstream](../workstreams/screens-capability-slices.md)).
- An app's drawing and loop code can be one shared file; examples stay
  runtime-prefixed wherever they construct hardware.
