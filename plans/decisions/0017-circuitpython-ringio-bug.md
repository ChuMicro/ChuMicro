# Decision 0017: CircuitPython RingIO build workaround — `standard` + flag, not the coverage variant

Status: `accepted`
Date: `2026-04-04`
Summary: Build CircuitPython unix-port as `VARIANT=standard` with `-DMICROPY_PY_MICROPYTHON_RINGIO=0` to dodge the upstream RingIO build bug; the workaround is self-removing on upstream fix.
Related: Decision 0014 (runner — heartbeat consumes the timing slice this affects)

## Context

Building the CircuitPython unix port with `VARIANT=standard` fails: an inherited-from-MicroPython `objringio.c` can't compile (or link) against CP's diverged, narrower ringbuf API.  We need a CP unix port to run the cross-runtime test tier, and the build has to be reliable.  The full forensic detail — version-dependent failure modes, why CP's CI never hits it, why RingIO is dead code in CP — is in [`docs/troubleshooting/circuitpython-ringio.md`](../../docs/troubleshooting/circuitpython-ringio.md); only the decision and its reasoning belong here.

## Decision

Build `VARIANT=standard` and pass `-DMICROPY_PY_MICROPYTHON_RINGIO=0` via `CFLAGS_EXTRA`.  This is the same mechanism CP's own coverage variant uses (a header-level define), applied from the command line.  Implemented in `scripts/prepare_circuitpython.py::_build_env()`.

The flag is harmless when the upstream bug is eventually fixed: setting a value that is already `0` has no effect, so the workaround is self-removing — upgrading to a fixed CP version needs no change on our side.

### Why not switch to `VARIANT=coverage`

`coverage` would sidestep the bug (it disables RingIO already), but it is a worse match for real ESP32-S2/S3 board behavior than `standard`:

- **Coverage disables `struct`** (`MICROPY_PY_STRUCT (0)`) — real boards provide it via shared-bindings, but the unix port has none, so `struct` would be entirely unavailable while working fine on hardware.
- **Coverage enables `EVERYTHING`-level features** (`namedtuple._asdict`, `marshal`, `re` match groups/spans, `memoryview.itemsize`, …) absent on real boards — tests passing under coverage could mask real incompatibilities.
- **Memory/perf profiling** (`gc.mem_alloc`, `micropython.mem_current/mem_peak`, `heap_lock/unlock`, `time.ticks_us`) is fully available under `standard`; coverage adds nothing here.

The build matching production semantics is worth carrying a one-line, self-removing flag.

## Consequences

- `prepare_circuitpython.py` carries the workaround flag; no other code is affected.
- The workaround is self-removing — a fixed CircuitPython version requires no change here.
- We continue building `VARIANT=standard` for cross-runtime testing.
- Operational forensics live in the troubleshooting doc, kept out of this ADR so it stays a decision record, not a postmortem.
