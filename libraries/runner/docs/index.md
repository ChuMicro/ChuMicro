# chumicro-runner

A tick-based task runner for CircuitPython, MicroPython, and CPython — no async required.

Components implement a `check(now_ms) -> bool` check that gates when a handler fires.  A `Runner` captures time once per tick, checks each service, and batch-fires all due handlers.

## Quick example

```python
from chumicro_runner import Runner

runner = Runner()
runner.add_periodic(lambda now_ms: print("one second"), period_ms=1000)
runner.add_periodic(lambda now_ms: print("five seconds"), period_ms=5000)

while True:
    runner.tick()
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — using fakes in your tests

---

[← All ChuMicro Libraries](https://chumicro.github.io/ChuMicro/)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · [PyPI](https://pypi.org/project/chumicro-runner/) · [Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · [Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)
