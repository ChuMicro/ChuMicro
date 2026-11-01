# CircuitPython RingIO build failure

Contributors build the CircuitPython *unix port*, a desktop build of CircuitPython, to run the cross-runtime unit tests on a laptop. This failure belongs to that desktop build. CircuitPython on a board never meets it.

## The symptom

Building the unix port with `VARIANT=standard` fails:

- **CircuitPython 10.1.4 and earlier:** the link step fails with an undefined symbol, `_mp_type_ringio`.
- **CircuitPython 10.2.0:** the compile step fails in `py/objringio.c` with `use of undeclared identifier 'iget'` and similar errors.

## The fix

Build through the repository's task, which passes the workaround for you:

```bash
python scripts/run.py prepare-circuitpython
```

To build by hand, run from the CircuitPython source folder and turn RingIO off with a compiler flag:

```bash
CFLAGS="-DMICROPY_PY_MICROPYTHON_RINGIO=0" make -C ports/unix VARIANT=standard
```

CircuitPython never uses RingIO, so turning it off costs nothing. [Decision 0017](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0017-circuitpython-ringio-bug.md) records why this repository builds the `standard` variant with the flag instead of switching variants, and why the flag stays after an upstream fix.

## Why it happens

RingIO (`micropython.RingIO()`) is a MicroPython ring buffer for passing data from an interrupt handler to the main loop. CircuitPython inherited its source file, `py/objringio.c`, from MicroPython. CircuitPython's own ring-buffer code differs: its `ringbuf_t` lacks the `iget` and `iput` members, and its `py/ringbuf.{c,h}` lacks `ringbuf_avail` and `ringbuf_memcpy_get_internal`. `objringio.c` uses all four, so it fails to compile against CircuitPython.

The `standard` variant turns on `MICROPY_CONFIG_ROM_LEVEL_EXTRA_FEATURES`, which enables `MICROPY_PY_MICROPYTHON_RINGIO` by default. `py/modmicropython.c` then refers to `mp_type_ringio`.

- In 10.1.4 and earlier, `py/py.mk` leaves `objringio.o` out, so the file is never compiled and the linker finds no definition for the type.
- In 10.2.0, `py/py.mk` lists `objringio.o` again, so the compiler reaches the file and fails on it. `py/ringbuf.h` is identical in both versions: 10.2.0 exposed the existing compile bug rather than creating a new one.

## Why CircuitPython's own CI misses it

CircuitPython's CI builds the unix port as `VARIANT=coverage` (`make -C ports/unix VARIANT=coverage` in `.github/workflows/run-tests.yml`). That variant's `mpconfigvariant.h` sets `MICROPY_PY_MICROPYTHON_RINGIO (0)` with the note "CIRCUITPY-CHANGE: Disable things never used in circuitpython". `tools/ci.sh`, which builds other variants, came over from MicroPython, and no CircuitPython workflow runs it.

A search of the CircuitPython tree finds no RingIO use in `shared-bindings/`, `shared-module/`, `ports/`, `py/circuitpy_mpconfig.h`, `py/circuitpy_defns.mk`, or `tests/`. The only RingIO code is the inherited MicroPython source: `py/objringio.c`, its declaration in `py/obj.h`, its registration in `py/modmicropython.c`, and its entry in `py/py.cmake`.

## Fixing it upstream

An upstream fix either ports MicroPython's ring-buffer helpers into CircuitPython's `py/ringbuf.{c,h}`, or rewrites `objringio.c` against CircuitPython's smaller ring-buffer API.
