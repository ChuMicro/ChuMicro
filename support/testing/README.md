# chumicro-testing

Shared test fakes and helpers for the ChuMicro workspace.

This is **workspace infrastructure** — it is not published as a library.
It provides deterministic fakes that are useful across multiple support
packages (`support/`) and scripts tests (`scripts/tests/`).

## Available fakes

### `FakeTime`

Deterministic seconds-domain time source that bundles `monotonic()` and
`sleep()` into a single injectable object.  Inject it wherever production
code accepts a `time` parameter to eliminate wall-clock waits in tests.

```python
from chumicro_testing import FakeTime

fake = FakeTime()
transport = SomeTransport(time=fake)

fake.advance(5.0)  # simulate 5 seconds passing
```

## Why not in a published library?

`FakeTime` fakes Python's `time` module — that's host-side CPython
infrastructure.  It does not belong in a published library like
`chumicro-timing`, which ships `FakeTicks` for the tick-domain contract
that runs on CircuitPython and MicroPython boards.

