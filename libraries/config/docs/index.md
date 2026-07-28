# chumicro-config

**Typed runtime configuration for ChuMicro libraries.**

Every library reads its settings from one deployed `runtime_config.msgpack` using dotted keys. The app loads that file once at boot and hands the whole config to each library, which pulls its own prefix off it: `wifi.ssid` becomes `WifiConfig.ssid`, `mqtt.broker.host` becomes the broker the MQTT client dials.

## Quick example

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
```

## Documentation

- [User Guide](guide.md): writing a `from_config` for your own library, soft loading with `try_load_section`, exception handling, the on-device config shape
- [API Reference](api.md): `load_runtime_config`, `load_section`, `RuntimeConfig`, and the config exceptions

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) · \
[PyPI](https://pypi.org/project/chumicro-config/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
