# chumicro-config

**Typed runtime configuration for ChuMicro libraries.**

Every library reads its settings from one shared file using dotted keys — write `wifi.ssid` in TOML, get `WifiConfig.ssid` on the device.

## Quick example

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
```

## Documentation

- [User Guide](guide.md) — getting started and usage patterns
- [API Reference](api.md) — full API documentation

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) · \
[PyPI](https://pypi.org/project/chumicro-config/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
