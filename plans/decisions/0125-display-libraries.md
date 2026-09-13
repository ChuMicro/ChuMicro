# Decision 0125: Display libraries delegate to firmware and own their drivers

Status: `accepted`
Date: `2026-08-23`
Summary: Displays ship as `chumicro-screens` (a frameless strip renderer) and `chumicro-segments`; drivers are first-party, MIT-credited where copied; no external Python dependencies.
Related: [Decision 0042](0042-library-dependency-policy.md) (intra-chumicro dependency classes; this adds the external-package axis), [Decision 0124](0124-buttons-and-knobs-libraries.md) (per-family device libraries, no base library), [Decision 0129](0129-frameless-strip-renderer.md) (the shared surface), [Decision 0080](0080-runner-reactor.md) (tick budget), [Decision 0087](0087-generators-for-sequential-io.md) (generator I/O), [Decision 0010](0010-library-testability.md) (constructor injection), [Decision 0090](0090-deploy-strips-docstrings-and-comments.md) (attribution placement)

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
  layers model it. The shared surface is a scene painted per strip with no
  frame in RAM, pinned in [Decision 0129](0129-frameless-strip-renderer.md):
  the strip is a firmware `framebuf.FrameBuffer` on MicroPython and a
  `displayio.Bitmap` drawn with `bitmaptools` on CircuitPython, and the
  flush is a generator that yields between strip writes so each resume fits
  the tick budget. The displayio factories stay the CircuitPython-native
  path, where flush costs the library nothing under background refresh: the
  firmware repaints from its background hook, which stalls the app loop for
  the whole transfer (11.4 ms at worst on a 128x64 OLED at 400 kHz, 29.8 ms
  at 100 kHz), so an app that keeps the 5 ms tick passes
  `auto_refresh=False` and refreshes from a handler of its own. Full-RGB
  scene-graph work on CircuitPython stays native `displayio` code, outside
  the shared surface.
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
- **Rendering the shared surface through `displayio`**: its refresh repaints
  every dirty pixel in one stall, about 6 us per pixel on an RP2040, so the
  shared surface paints strips itself and displayio's scanline renderer
  stays reachable through the factories.
- **A base display library** — Decision 0124 already rejects the shape for
  device families; protocols are documented duck typing.

## Consequences

- The two libraries enter `libraries/` through the `new-library` skill once
  the bench hardware list exists; every panel streams windowed strip writes
  from one small buffer, whatever its resolution.
- Consumers on any install channel need nothing beyond chumicro packages, and
  the workspace deploy stages everything it ships.
- Both budget numbers are bench-measured: CircuitPython refresh jitter under
  `auto_refresh` is the stall above, and one MicroPython SSD1306 page at
  400 kHz flushes in 3.7 ms mean and 3.9 ms worst, inside the tick.
