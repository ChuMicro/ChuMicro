# chumicro-abstractions

Shared abstractions and test fakes for the ChuMicro workspace.

This is **workspace infrastructure** — it is not published as a library.
It provides injectable time sources for support packages (`support/`)
and scripts tests (`scripts/tests/`).

## Available exports


### `FakeTime`

Deterministic seconds-domain time source for host-side tests.
Inject it wherever production code accepts a `time` parameter to
eliminate wall-clock waits.

```python
from chumicro_abstractions import FakeTime

fake = FakeTime()
service = MyService(time=fake)

fake.advance(5.0)  # simulate 5 seconds passing
```

## Why not in a published library?

These abstractions wrap Python's `time` module — that's host-side
CPython infrastructure.  They do not belong in a published library
like `chumicro-timing`, which ships `FakeTicks` for the tick-domain
contract that runs on CircuitPython and MicroPython boards.
