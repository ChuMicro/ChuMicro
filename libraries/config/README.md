# chumicro-config

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Read your project's settings by name, from one file on the board.**

Keep the wifi network, the broker address, and how often to take a reading out of `code.py`.  A ChuMicro project keeps its settings in one file on the board, `/runtime_config.msgpack`, and gives each one a dotted name: `wifi.ssid`, `mqtt.broker.host`, `sensor.period_ms`.  `load_runtime_config()` reads that file, and you look settings up the way you would in a dict.  ChuMicro libraries take the same object and read their own settings out of it, so `WifiService.from_config(config)` finds `wifi.ssid` and `wifi.password` without you passing them one at a time.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_config

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_config

# CPython
pip install chumicro-config
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [ChuMicro install guide](https://chumicro.com/ChuMicro/guides/install/).

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

To turn a group of settings into one object, give it a class and let `load_section` fill in the arguments from every `sensor.*` key:

```python
from chumicro_config import load_section

class SensorConfig:
    def __init__(self, name, period_ms=5000, units="C"):
        self.name = name
        self.period_ms = period_ms
        self.units = units

sensor = load_section(
    SensorConfig, config,
    prefix="sensor",
    required=("name",),
    optional={"period_ms": 5000, "units": "C"},
)
```

ChuMicro libraries ship the same kind of class with a `from_config()` method, so `WifiService.from_config(config)` reads `wifi.ssid`, `wifi.password`, and the other `wifi.*` settings in one call.

## What's included

| Symbol | What it does |
|---|---|
| `load_runtime_config(path=None)` | Read `/runtime_config.msgpack` (or the file at `path`) and return a `RuntimeConfig` |
| `chumicro_config.config` | The same settings, read from the file the first time you use it; `None` when the board has no settings file |
| `RuntimeConfig` | The settings object: `config.get(key, default)`, `config[key]` or `config.require(key)` (raise `MissingConfigKey` when absent), and `key in config` |
| `load_section(cls, config, *, prefix, required=(), optional=None)` | Build `cls(...)` from every `<prefix>.*` setting, passing each one as a keyword argument |
| `try_load_section(...)` | Like `load_section`, but returns `None` instead of raising when a required setting is missing or `config` is `None` or not a dict |
| `MissingConfigKey`, `InvalidConfigType` | Raised when a required setting is absent, or when `config` is not a `RuntimeConfig` or dict; catch `ConfigError` for both |

## Where this fits

Depends on [`chumicro-msgpack`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack) to read the settings file; `circup` and `mip` install it for you.  [`chumicro-wifi`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi), [`chumicro-mqtt`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt), [`chumicro-ntp`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp), [`chumicro-requests`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests), [`chumicro-websockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets), and [`chumicro-http_server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server) each read their settings from a `RuntimeConfig` through a `from_config()` method.  `chumicro-workspace` writes `/runtime_config.msgpack` from TOML files on your laptop when it deploys a project.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

| Example | What it shows |
|---|---|
| [`end_to_end.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/config/examples/end_to_end.py) | Reads settings with `config.get`, builds a `SensorConfig` with `load_section`, catches `MissingConfigKey`, then takes a pretend reading every `sensor.period_ms` forever.  Runs on every runtime without a settings file. |

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/config/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/config/experimental/)**

## Find this library

- **PyPI:** [chumicro-config](https://pypi.org/project/chumicro-config/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_config) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_config)
- **Source:** [libraries/config](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
