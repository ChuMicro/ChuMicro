# Decision 0017: CircuitPython RingIO build bug — workaround and tracking

Status: `accepted`
Date: `2026-04-04`
Re-verified: `2026-05-03` (CP 10.2.0)

## Context

Building the CircuitPython 10.1.4 unix port with `VARIANT=standard` fails with an
unresolved-symbol linker error for `_mp_type_ringio`.  This blocks the
`prepare-circuitpython` build step.

CP 10.2.0 (2026-05) added `objringio.o` to `py/py.mk`, which fixes the
*linker* error — but `objringio.c` itself still doesn't compile in CP because
the `ringbuf_t` struct is missing the `iget` / `iput` members and the
`ringbuf_avail` / `ringbuf_memcpy_get_internal` helper functions that
the file references.  CP-side ringbuf evolution diverged from MP's.
Net effect: the `-DMICROPY_PY_MICROPYTHON_RINGIO=0` workaround is still
needed in 10.2.0 — the failure mode just shifts from linker to compiler.

## Root cause

CircuitPython's `py/py.mk` is missing the `objringio.o` object file that
MicroPython v1.26.0 includes at line 176.  The CMake equivalent (`py/py.cmake`)
does list `objringio.c` at line 101 — only the Make-based build is affected.

(In CP 10.2.0 the Makefile entry was added but the source file's compile
errors were not fixed; see Context above.)

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

This is a genuine bug in CircuitPython 10.1.4 — and still in 10.2.0.

* **CP 10.2.0** added `objringio.o` to `py/py.mk` (matching `py.cmake:101`
  and MicroPython's `py.mk:176`).  Linker is happy.  But `objringio.c`
  itself still references `ringbuf_t` members (`iget`, `iput`) and
  helpers (`ringbuf_avail`, `ringbuf_memcpy_get_internal`) that don't
  exist in CP's diverged ringbuf implementation.  Compile fails.
* **A complete fix** would require either back-porting MP's ringbuf
  helpers (`iget`/`iput` + the helper functions) into CP's `py/ringbuf.h`
  + `py/ringbuf.c`, or replacing `objringio.c` with CP-compatible code.
  Both are CP-side patches.

Since CircuitPython does not use RingIO and their coverage variant already
disables it, the practical impact is limited to anyone building
`VARIANT=standard` from source.  Our workaround stays in place.

If/when CircuitPython fully fixes the bug upstream (compile + link) or we
upgrade to a CP version that does, our `CFLAGS_EXTRA` workaround is
harmless — setting a flag that is already `0` has no effect.

## Consequences

- `prepare_circuitpython.py` carries the workaround flag; no other code is affected.
- The workaround is self-removing: upgrading to a fixed CircuitPython version
  requires no changes on our side.
- We continue building `VARIANT=standard` for cross-runtime testing.
