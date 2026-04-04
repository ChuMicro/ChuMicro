# Decision 0017: CircuitPython RingIO build bug — workaround and tracking

Status: `accepted`
Date: `2026-04-04`

## Context

Building the CircuitPython 10.1.4 unix port with `VARIANT=standard` fails with an
unresolved-symbol linker error for `_mp_type_ringio`.  This blocks the
`prepare-circuitpython` build step.

## Root cause

CircuitPython's `py/py.mk` is missing the `objringio.o` object file that
MicroPython v1.26.0 includes at line 176.  The CMake equivalent (`py/py.cmake`)
does list `objringio.c` at line 101 — only the Make-based build is affected.

The `standard` variant sets `MICROPY_CONFIG_ROM_LEVEL_EXTRA_FEATURES`, which
enables `MICROPY_PY_MICROPYTHON_RINGIO` by default (`mpconfig.h:1387`).
`modmicropython.c:217` then references `mp_type_ringio`, but the Makefile never
compiles the object file (`objringio.c`) that defines it, causing a linker error.

### Why CircuitPython CI doesn't catch it

1. **CI builds `VARIANT=coverage`, not `standard`.**  The actual CI workflow
   (`.github/workflows/run-tests.yml:48`) runs
   `make -C ports/unix VARIANT=coverage -j4`.
2. **The coverage variant explicitly disables RingIO.**
   `ports/unix/variants/coverage/mpconfigvariant.h:52` sets
   `MICROPY_PY_MICROPYTHON_RINGIO (0)` with the comment
   "CIRCUITPY-CHANGE: Disable things never used in circuitpython".
3. **`tools/ci.sh` is dead code** — inherited from the MicroPython fork but never
   referenced by any CircuitPython GitHub Actions workflow.

The bug only surfaces when building `VARIANT=standard`, which nobody in the
CircuitPython project does in CI.

### CircuitPython does not use RingIO

A full-tree search confirms that RingIO is never used anywhere in
CircuitPython-specific code:

- **`shared-bindings/`** — no references.
- **`shared-module/`** — no references.
- **`ports/`** — no references (only the coverage variant's disable).
- **`py/circuitpy_mpconfig.h`** — no mention of RingIO.
- **`py/circuitpy_defns.mk`** — no mention of RingIO.
- **`tests/`** — no RingIO test files.

The only RingIO code in the tree is inherited from upstream MicroPython:
`py/objringio.c`, `py/obj.h:893` (extern declaration), `py/modmicropython.c:216–217`
(conditional registration), and `py/py.cmake:101` (CMake source list).

RingIO is a MicroPython-only feature (`micropython.RingIO()`) — a lock-free,
single-producer/single-consumer ring buffer designed for ISR-to-main-loop
communication.  CircuitPython forbids ISR usage and has its own I/O abstractions,
so the type has no purpose in the CircuitPython ecosystem.

## Decision

### Workaround

Pass `-DMICROPY_PY_MICROPYTHON_RINGIO=0` via `CFLAGS_EXTRA` when building the
CircuitPython unix port.  This is the same mechanism the coverage variant uses
(header-level define) but applied from the command line.  Implemented in
`scripts/prepare_circuitpython.py::_build_env()`.

### Why not switch to `VARIANT=coverage`

The `standard` variant (`EXTRA_FEATURES` ROM level) is a better match for real
ESP32-S2/S3 board behavior than `coverage` (`EVERYTHING` ROM level):

- **Coverage disables `struct`** (`MICROPY_PY_STRUCT (0)`) because real boards
  provide it via shared-bindings.  The unix port has no shared-bindings, so
  `struct` would be entirely unavailable — but it works fine on real boards.
- **Coverage enables `EVERYTHING`-level features** (`namedtuple._asdict`,
  `marshal`, `re` match groups/spans, `memoryview.itemsize`, etc.) that are not
  available on real boards.  Tests passing under coverage could mask real
  incompatibilities.
- **Memory/perf profiling** (`gc.mem_alloc`, `micropython.mem_current/mem_peak`,
  `heap_lock/unlock`, `time.ticks_us`) is fully available on the `standard`
  variant — the coverage variant adds nothing meaningful for performance testing.

### Upstream tracking

This is a genuine bug in CircuitPython 10.1.4.  The fix is a one-line addition
to `py/py.mk` (add `objringio.o \` after the `objrangegen.o` line, matching
`py.cmake:101` and MicroPython's `py.mk:176`).  However, since CircuitPython
does not use RingIO and their coverage variant already disables it, the practical
impact is limited to anyone building `VARIANT=standard` from source.

If/when CircuitPython merges the fix upstream or we upgrade the pinned version,
our `CFLAGS_EXTRA` workaround is harmless — setting a flag that is already `0`
has no effect.

## Consequences

- `prepare_circuitpython.py` carries the workaround flag; no other code is affected.
- The workaround is self-removing: upgrading to a fixed CircuitPython version
  requires no changes on our side.
- We continue building `VARIANT=standard` for cross-runtime testing.

