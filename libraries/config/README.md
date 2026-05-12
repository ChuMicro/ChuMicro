# chumicro-config

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Runtime config from one shared dotted-key shape (`wifi.ssid`, `mqtt.broker.host`).**

Each library exposes a `<Name>Config.from_config()` factory that reads its own dotted-prefix section from a shared dict (`wifi.*`, `mqtt.broker.*`, etc.) and returns typed configuration.  Apps load one `runtime_config.msgpack` at boot; libraries pull their slice out.  No global registry, no hand-written `if "key" in config:` walls.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro-config

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_config

# CPython
pip install chumicro-config
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

User-app pattern (the 2-line bring-up):

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()                          # reads /runtime_config.msgpack
wifi = WifiService(WifiConfig.from_config(config))      # reads + types the wifi.* keys
```

Library-side pattern (inside every consumer library's `<Name>Config.from_config`):

```python
from chumicro_config import load_section

class WifiConfig:
    def __init__(self, ssid, password, hostname=None, connect_timeout_ms=15_000): ...

    @classmethod
    def from_config(cls, config):
        return load_section(
            cls, config,
            prefix="wifi",
            required=("ssid", "password"),
            optional={"hostname": None, "connect_timeout_ms": 15_000},
        )
```

## What's included

| Symbol | What it does |
|---|---|
| `load_runtime_config(path=…)` | Read + decode `/runtime_config.msgpack` into a flat-key `RuntimeConfig` (dict-shaped) |
| `load_section(cls, config, *, prefix, required=…, optional=…)` | Standardized `from_config` core every library calls |
| `MissingConfigKey` / `InvalidConfigType` / `ConfigError` | Targeted exceptions — single-inheritance from `ConfigError` (MicroPython forbids multi-parent layouts) |
| `DEFAULT_RUNTIME_CONFIG_PATH` | The canonical on-device path (`/runtime_config.msgpack`) |

## Where this fits

Depends on [`chumicro-msgpack`](../msgpack/) for decode.  Every ChuMicro library that has a `<Name>Config.from_config()` factory uses this — [`chumicro-wifi`](../wifi/), [`chumicro-mqtt`](../mqtt/), and friends.

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

No standalone examples — see any consumer library (starting with `chumicro-wifi`) for the integrated usage shape.

## Contributing

Working on `chumicro-config` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/config/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/config/experimental/)**

## Find this library

- **PyPI:** [chumicro-config](https://pypi.org/project/chumicro-config/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_config) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_config)
- **Source:** [libraries/config](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
