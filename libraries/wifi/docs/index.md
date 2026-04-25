# chumicro-wifi

Unified wifi supervisor across CircuitPython, MicroPython, and CPython. Sole-supervisor model — no `CIRCUITPY_WIFI_*` keys, no firmware-level auto-reconnect.

## Quick example

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_dict(config["wifi"]))
runner.add(wifi)
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
