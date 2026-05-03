# chumicro-config

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Standardized runtime-config helpers for ChuMicro libraries. One file per thing, section-namespaced dict, typed `<Name>Config.from_dict()` per consumer. See [Decision 0035](../../plans/decisions/0035-runtime-config-structure.md) for the convention and [Decision 0036](../../plans/decisions/0036-chumicro-config-library.md) for why this lives in its own library.

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

User-app pattern (the canonical 2-line bring-up):

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()                                # reads /runtime_config.msgpack
wifi = WifiService(WifiConfig.from_dict(config["wifi"]))      # types + validates the wifi section
```

Library-side pattern (inside every consumer library's `<Name>Config.from_dict`):

```python
from chumicro_config import load_section

class WifiConfig:
    def __init__(self, ssid, password, hostname=None, connect_timeout_ms=15_000): ...

    @classmethod
    def from_dict(cls, data):
        return load_section(
            cls, data,
            required=("ssid", "password"),
            optional={"hostname": None, "connect_timeout_ms": 15_000},
        )
```

## What's included

| Symbol | What it does |
|---|---|
| `load_runtime_config(path=…)` | Read + decode `/runtime_config.msgpack` into the section-namespaced dict |
| `load_section(cls, data, required=…, optional=…)` | Standardized `from_dict` core every library calls |
| `MissingConfigKey` / `InvalidConfigType` / `ConfigError` | Targeted exceptions (also subclass `KeyError` / `TypeError`) |
| `DEFAULT_RUNTIME_CONFIG_PATH` | The canonical on-device path (`/runtime_config.msgpack`) |

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

No standalone examples — see any consumer library (starting with `chumicro-wifi`) for the integrated usage shape.

## Developing this library

Host-side tests live in `tests/`; real-board functional tests belong in `functional_tests/`.

```bash
python scripts/run.py test --libraries config
python scripts/run.py test-libraries-functional --library config
```

Before running device tests, generate local board config files with `python scripts/run.py setup`, then fill in `devices.yml`. See the [contributing guide](https://github.com/ChuMicro/ChuMicro/blob/main/CONTRIBUTING.md) and the [device testing guide](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/device-testing.md) for the full workflow.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/config/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/config/experimental/)**

## Find this library

- **PyPI:** [chumicro-config](https://pypi.org/project/chumicro-config/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_config) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_config)
- **Source:** [libraries/config](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config)
