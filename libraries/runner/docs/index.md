# chumicro-runner

**Tick-based scheduling for CircuitPython, MicroPython, and CPython — debuggable from `print()`.**

`runner.tick()` runs every registered service once on a shared timestamp.  Each service is one object with `check(now_ms)` + `handle(now_ms)`; your loop is six lines.  Every state change shows up in the order you wrote.

Every networked library in ChuMicro (`chumicro-wifi`, `chumicro-sockets`, `chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server`, `chumicro-websockets`) is shaped to register here — your LED can keep blinking through a TLS handshake, a slow HTTP response, or a stalled MQTT peer because every one of them gets the same fair share of every tick.

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

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · \
[PyPI](https://pypi.org/project/chumicro-runner/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
