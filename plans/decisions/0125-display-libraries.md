# Decision 0125: Display libraries delegate to firmware and own their drivers

Status: `accepted`
Date: `2026-08-23`
Summary: Displays ship as `chumicro-screens` (framebuf-shaped protocol over firmware layers) and `chumicro-segments`; drivers are first-party, MIT-credited where copied; no external Python dependencies.
Related: [Decision 0042](0042-library-dependency-policy.md) (intra-chumicro dependency classes; this adds the external-package axis), [Decision 0124](0124-buttons-and-knobs-libraries.md) (per-family device libraries, no base library), [Decision 0080](0080-runner-reactor.md) (tick budget), [Decision 0087](0087-generators-for-sequential-io.md) (generator I/O), [Decision 0010](0010-library-testability.md) (constructor injection), [Decision 0090](0090-deploy-strips-docstrings-and-comments.md) (attribution placement)

## Context

Both target runtimes carry a C display layer in firmware: `framebuf` on
MicroPython, `displayio` on CircuitPython. The Python drivers around them are
external packages that no chumicro channel can express: pip, circup, and mip
share no dependency language, and the clean-slate deploy removes any board file
outside the payload and keep set, so a board-side `circup`/`mip` install does
not survive a deploy. The stock MicroPython drivers also block for the full bus
transfer in `show()` (~20 ms for a mono 128x64 frame over 400 kHz I2C), which
breaks the Decision 0080 tick budget.

## Decision

A runtime display layer is used when it is firmware-resident and cooperates
with the tick budget. Everything else is written first-party under house
standards.

- **`chumicro-screens`** covers pixel-addressable panels; monochrome and color
  are one library with pixel format as an axis, matching how both firmware
  layers model it. The drawing protocol adopts `framebuf`'s method vocabulary
  rather than inventing a new API; its portable color contract is
  indexed-palette, pinned in [Decision 0126](0126-canvas-indexed-palette.md). On MicroPython the surface is a firmware
  `framebuf.FrameBuffer` and the flush is a generator that yields between page
  writes so each resume fits the tick budget. On CircuitPython the same surface
  is implemented over a `displayio.Bitmap` with `bitmaptools` ops and
  `terminalio.FONT`, and flush costs the library nothing under background
  refresh: the firmware repaints from its background hook, which stalls the
  app loop for the whole transfer (11.4 ms at worst on a 128x64 OLED at
  400 kHz, 29.8 ms at 100 kHz), so an app that keeps the 5 ms tick passes
  `auto_refresh=False` and refreshes from a handler of its own.
  Full-RGB scene-graph work on CircuitPython stays native `displayio` code,
  outside the protocol.
- **`chumicro-segments`** covers segment controllers (TM1637, HT16K33, MAX7219
  class): plain owned drivers with a `show(str)`-shaped surface, since no
  firmware layer exists for them. Character-cell LCDs are a third family,
  named when first built.
- **No external Python dependencies.** Display libraries declare only
  chumicro dependencies under Decision 0042. Upstream driver code is absorbed
  first-party: datasheet first, reference drivers consulted for off-datasheet
  quirks, and any verbatim copy carries the upstream copyright line in the
  library's LICENSE file, which ships in every channel and survives the
  Decision 0090 comment stripping. Each absorbed file gets a per-file license
  check; non-MIT sources are clean-roomed from the datasheet, never copied.
- **Validated-only drivers.** A controller driver ships only after bench
  validation on real hardware; the supported-controller list never exceeds the
  validated list.

Rejected alternatives:

- **One drawing API spanning segment and pixel devices** — collapses to a
  lowest common denominator or grows capability probes; the families share no
  addressable surface.
- **Wrapping external driver packages** (as dependency or injected object) —
  nothing can stage them: no cross-channel dependency declaration exists and
  the deploy wipe deletes board-side installs.
- **A cross-channel external-dependency mechanism** (pinning, mirroring,
  deploy staging, template and CI support) — a full workstream serving files
  of ~100 lines each. Revisit only for a need absorption cannot meet.
- **Bypassing `displayio` for one cross-runtime driver body** — discards the
  C-level scanline rendering that makes color panels viable in the 256 KB
  board class.
- **A base display library** — Decision 0124 already rejects the shape for
  device families; protocols are documented duck typing.

## Consequences

- The two libraries enter `libraries/` through the `new-library` skill once
  the bench hardware list exists; each MicroPython color panel picks a RAM
  strategy (full RGB565 buffer, indexed buffer converted at flush, or windowed
  writes) from its actual resolution.
- Consumers on any install channel need nothing beyond chumicro packages, and
  the workspace deploy stages everything it ships.
- Both budget numbers are bench-measured: CircuitPython refresh jitter under
  `auto_refresh` is the stall above, and one MicroPython SSD1306 page at
  400 kHz flushes in 3.7 ms mean and 3.9 ms worst, inside the tick.
