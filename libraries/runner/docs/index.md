---
title: "chumicro-runner: run many services in one loop on CircuitPython and MicroPython"
---

# chumicro-runner

**Tick-based scheduling for CircuitPython, MicroPython, and CPython, debuggable from `print()`.**

Your main loop is the two calls below: `runner.tick()` runs every registered service once on a shared timestamp, then `runner.wait()` idles the CPU until the next deadline or socket event.  Each service is one object with `check(now_ms)` and `handle(now_ms)`, so every state change happens in the order you wrote and a `print()` shows it.  Every networked library in ChuMicro (`chumicro-wifi`, `chumicro-sockets`, `chumicro-mqtt`, `chumicro-requests`, `chumicro-http-server`, `chumicro-websockets`) is shaped to register here, so your LED keeps blinking through a TLS handshake, a slow HTTP response, or a stalled MQTT peer: each of them gets the same share of every tick.

## Quick example

```python
from chumicro_runner import Runner

runner = Runner()
runner.add_periodic(lambda now_ms: print("one second"), period_ms=1000)
runner.add_periodic(lambda now_ms: print("five seconds"), period_ms=5000)

while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
```

## Documentation

- [User Guide](guide.md): the check / handle service contract, registration patterns, generator-driven flows, idling between ticks, period-gated and batch-fired services
- [API Reference](api.md): `Runner` with its `add` / `add_periodic` / `add_generator` registrations, `TaskHandle`, and the `sleep_until` suspension helper
- [Testing Helpers](testing.md): using `CallRecorder`, `FakePoller`, and `validate_service` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) · \
[PyPI](https://pypi.org/project/chumicro-runner/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
