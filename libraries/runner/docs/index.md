# chumicro-runner

A tick-based task runner for CircuitPython, MicroPython, and CPython — no async required.

Components implement a `check(now_ms) -> bool` check that gates when a handler fires.  A `Runner` captures time once per tick, checks each service, and batch-fires all due handlers.

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — using fakes in your tests

