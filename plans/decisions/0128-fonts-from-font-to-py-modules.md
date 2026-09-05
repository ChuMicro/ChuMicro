# Decision 0128: Canvas fonts are font-to-py modules

Status: `accepted`
Date: `2026-09-05`
Summary: A canvas font is a font-to-py module drawn by `chumicro_screens.fonts.Font` through framebuf's read-only blit source and a 1-bit `displayio.Bitmap` sheet; no chumicro font format or converter.
Related: [Decision 0126](0126-canvas-indexed-palette.md) (the canvas this extends), [Decision 0125](0125-display-libraries.md) (the firmware-layer criterion), [Decision 0092](0092-no-backwards-compat-before-publication.md)

## Context

Decision 0126 left `text` as the one canvas method without pixel-identical
output: each backend renders its runtime's built-in font, framebuf's 8x8 on
MicroPython and `terminalio.FONT`'s 6x12 on CircuitPython, so a label laid
out on one runtime lands elsewhere on the other. Pixel-identical text needs
pre-converted glyph bitmaps and a host-side converter, and the open choice
was the format: the MicroPython ecosystem's font-to-py modules or a chumicro
one.

## Decision

- A font is a font-to-py module, the file `font_to_py -x <font> <height>
  <name>.py` writes: horizontally mapped glyph rows behind `height()`,
  `baseline()`, `max_width()`, `min_ch()`, `max_ch()`, and `get_ch()`. The
  module ships beside the app; `chumicro_screens.fonts.Font(module)` is the
  only chumicro surface, with `text(canvas, string, x, y, index)` and
  `width(string)`.
- Both backends blit that layout unchanged, in C. MicroPython's
  `FrameBuffer.blit` takes a `(buffer, width, height, MONO_HLSB)` sequence
  as a read-only source, so a glyph goes straight from the module's bytes
  through a two-entry palette whose background entry is the skipped key.
  CircuitPython loads the glyphs once, at construction, into a 1-bit
  `displayio.Bitmap` sheet, each through `bitmaptools.readinto` and one
  blit, and draws regions of it through `BitmapCanvas.blit_bits`, the
  scratch-and-recolor path the built-in `text` shares.
- A character the module lacks draws as the module's own substitute glyph
  on both runtimes, so text and `width` agree everywhere.
- There is no chumicro glyph format and no in-repo converter. The
  invariant: the library adds no format of its own for bits both firmwares
  already blit natively.

Rejected alternatives:

- **A chumicro glyph format with its own converter** — a second encoding
  of the same bits plus a freetype-dependent host tool to maintain, for no
  capability font-to-py's public functions lack.
- **BDF or PCF through `adafruit_bitmap_font`** — CircuitPython-only,
  parsed at runtime, and part of the displayio path Decision 0126 keeps
  outside the canvas.
- **Copying each glyph into a scratch `FrameBuffer` per draw** — framebuf
  reads a sequence source read-only, so the copy buys nothing.
- **Converting glyphs at draw time on CircuitPython** — a Python loop over
  bytes on every draw; the sheet moves that work to construction for 3 to
  4 KB of RAM on a 20-pixel ASCII font.
- **A wrapping canvas class on MicroPython so `frame.text` takes a font** —
  a Python call per primitive on the runtime where the frame is the C
  object itself. The font is an object that draws onto the canvas instead.

## Consequences

- `chumicro-screens` gains `fonts.Font` and `BitmapCanvas.blit_bits`; the
  canvas's own `text` keeps its per-runtime built-in font.
- Fonts convert on the host with the external tool (`pip install
  font_to_py`, which needs freetype). A font module checked in beside an
  example is the tool's output plus an attribution header and the lint
  suppressions its index lambda needs, so it can be regenerated.
- On MicroPython `Font` blits through a `GS8` palette, so it draws on the
  indexed frame only; the mono OLED frame and the 16-bit frame need a
  palette in their own format, which nothing ships yet.
