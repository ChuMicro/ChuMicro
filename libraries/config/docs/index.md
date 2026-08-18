---
title: "chumicro-config: runtime settings for CircuitPython and MicroPython"
---

# chumicro-config

**Typed runtime configuration for ChuMicro libraries.**

Every library reads its settings from one deployed `runtime_config.msgpack` using dotted keys. The app loads that file once at boot and hands the whole config to each library, which pulls its own prefix off it: `wifi.ssid` becomes `WifiConfig.ssid`, `mqtt.broker.host` becomes the broker the MQTT client dials.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_config

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_config

# CPython
pip install chumicro-config
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

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
