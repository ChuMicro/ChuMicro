# CircuitPython unix-port RingIO build failure

Covers why building the CircuitPython unix port with `VARIANT=standard` fails out of the box, and why `scripts/prepare_circuitpython.py` passes a workaround flag.  The decision rationale (*why* we build `standard` with the flag rather than switching variants) lives in [Decision 0017](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0017-circuitpython-ringio-bug.md); this page is the forensic detail behind it.

This only matters if you build the CP unix port from source (the cross-runtime test path does).  Nothing here affects on-device CircuitPython.

## Symptoms

The build fails, and *how* it fails depends on the CP version:

- **CP 10.1.4 and earlier**: `objringio.o` is missing from `py/py.mk`, so `objringio.c` is never compiled and the compile bug stays hidden.  But `py/modmicropython.c:217` references `mp_type_ringio`, so the **linker** fails with an undefined-symbol error for `_mp_type_ringio`.
- **CP 10.2.0**: `objringio.o` was added back to `py/py.mk`, so the build system compiles `objringio.c` and the long-standing **compile** bug surfaces directly as a `clang` error (`use of undeclared identifier 'iget'`, etc.).

The 10.2.0 change exposed a pre-existing compile bug; it didn't create a new one or fix anything.  Verified by diffing `py/ringbuf.h` between the two versions: identical.

## Root cause

CircuitPython's ringbuf API has diverged from MicroPython's.  CP's `ringbuf_t` doesn't expose the `iget` / `iput` members, and CP's `py/ringbuf.{c,h}` doesn't provide `ringbuf_avail` / `ringbuf_memcpy_get_internal`.  CP's `objringio.c` was inherited from MicroPython and references all four, so it cannot compile against CP's narrower ringbuf API without first back-porting the missing surface or rewriting `objringio.c`.

The `standard` variant sets `MICROPY_CONFIG_ROM_LEVEL_EXTRA_FEATURES`, which enables `MICROPY_PY_MICROPYTHON_RINGIO` by default (`mpconfig.h:1387`).  `modmicropython.c:217` then references `mp_type_ringio`, but the Makefile never compiles the object file that defines it, hence the linker error on older CP, and the compile error once `py.mk` compiles the file again.

## Why CircuitPython CI doesn't catch it

1. **CI builds `VARIANT=coverage`, not `standard`**: `.github/workflows/run-tests.yml:48` runs `make -C ports/unix VARIANT=coverage -j4`.
2. **The coverage variant explicitly disables RingIO**: `ports/unix/variants/coverage/mpconfigvariant.h:52` sets `MICROPY_PY_MICROPYTHON_RINGIO (0)` with the comment "CIRCUITPY-CHANGE: Disable things never used in circuitpython".
3. **`tools/ci.sh` is dead code**: inherited from the MicroPython fork, never referenced by any CircuitPython GitHub Actions workflow.

The bug only surfaces when building `VARIANT=standard`, which nobody in the CircuitPython project does in CI.

## CircuitPython does not use RingIO

A full-tree search confirms RingIO is never used in CircuitPython-specific code: no references in `shared-bindings/`, `shared-module/`, `ports/` (only the coverage variant's disable), `py/circuitpy_mpconfig.h`, `py/circuitpy_defns.mk`, or `tests/`.  The only RingIO code in the tree is inherited from upstream MicroPython: `py/objringio.c`, `py/obj.h:893` (extern declaration), `py/modmicropython.c:216-217` (conditional registration), and `py/py.cmake:101` (CMake source list).

RingIO is a MicroPython-only feature (`micropython.RingIO()`), a lock-free single-producer/single-consumer ring buffer designed for ISR-to-main-loop communication.  CircuitPython forbids ISR usage and has its own I/O abstractions, so the type has no purpose in the CircuitPython ecosystem.

## Upstream status

This is a genuine CircuitPython bug in both 10.1.4 (linker surface) and 10.2.0 (compile surface).  A complete upstream fix would require either back-porting MP's ringbuf helpers (`iget` / `iput` + `ringbuf_avail` / `ringbuf_memcpy_get_internal`) into CP's `py/ringbuf.{c,h}`, or rewriting `objringio.c` against CP's narrower ringbuf API.  Both are CP-side patches.  No upstream fix yet.

Because CircuitPython doesn't use RingIO and its coverage variant already disables it, the practical impact is limited to anyone building `VARIANT=standard` from source.  When CircuitPython fixes this upstream (or we move to a CP version that does), the workaround flag becomes a no-op (setting a value that is already `0` has no effect), so no cleanup is needed on our side.
