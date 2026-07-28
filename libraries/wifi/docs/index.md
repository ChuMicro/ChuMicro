# chumicro-wifi

**Wifi that auto-reconnects without freezing your loop.**

One wifi service across CircuitPython on Adafruit boards and MicroPython on both ESP32 and Pi Pico W. Register it with `chumicro-runner` and your LED keeps blinking through every connect, drop, and reconnect. This library owns the radio (no `CIRCUITPY_WIFI_*` settings, no firmware-level auto-reconnect competing with you). On CPython there is no radio to drive, so the service runs against an in-memory fake adapter and your host tests exercise the same state machine.

## Quick example

```python
from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))

runner = Runner()
runner.add(wifi)
while True:
    runner.tick()
```

## Documentation

- [User Guide](guide.md): the connect and reconnect state machine, reading IP and errors, state-change notifications, configuration, and runner integration
- [API Reference](api.md): `WifiService`, `WifiConfig`, and the `WifiState` constants
- [Testing Helpers](testing.md): using `FakeWifi` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
