---
title: "chumicro-config: runtime settings for CircuitPython and MicroPython"
---

# chumicro-config

**Read your project's settings by name, from one file on the board.**

Keep the wifi network, the broker address, and how often to take a reading out of `code.py`.  A ChuMicro project keeps its settings in one file on the board, `/runtime_config.msgpack`, and gives each one a dotted name: `wifi.ssid`, `mqtt.broker.host`, `sensor.period_ms`.  `load_runtime_config()` reads that file into an object you query like a dict.  ChuMicro libraries take the same object and read their own settings out of it, so `WifiService.from_config(config)` finds `wifi.ssid` and `wifi.password` without your code passing them one at a time.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_config

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_config

# CPython
pip install chumicro-config
```

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Read two settings and use them in the main loop:

```python
import time

from chumicro_config import RuntimeConfig

# On a board deployed with chumicro-workspace, read the settings file instead:
#     from chumicro_config import load_runtime_config
#     config = load_runtime_config()
config = RuntimeConfig({"sensor.name": "back-porch", "sensor.period_ms": 2000})

name = config["sensor.name"]                       # raises MissingConfigKey if absent
period_ms = config.get("sensor.period_ms", 5000)   # 5000 if absent

while True:
    print(f"{name}: taking a reading")
    time.sleep(period_ms / 1000)
```

## Documentation

- [User Guide](guide.md): reading the settings file, building a settings object for your own code or library, optional sections with `try_load_section`, the errors, and what the file looks like on the board
- [API Reference](api.md): `load_runtime_config`, `RuntimeConfig`, `load_section`, `try_load_section`, and the config exceptions

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) · \
[PyPI](https://pypi.org/project/chumicro-config/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
