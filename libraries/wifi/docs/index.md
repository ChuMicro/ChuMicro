# chumicro-wifi

**Wifi that auto-reconnects without freezing your loop.**  One service across CircuitPython, MicroPython, and CPython — register it with `chumicro-runner` and your LED keeps blinking through every connect, drop, and reconnect.  This library owns the radio (no `CIRCUITPY_WIFI_*` settings, no firmware-level auto-reconnect competing with you).

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

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation
- [Testing Helpers](testing.md) — `FakeWifi` for downstream test suites

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
