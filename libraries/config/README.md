# chumicro-config

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Runtime config from one shared dotted-key shape (`wifi.ssid`, `mqtt.broker.host`).**

Each library exposes a `<Name>Config.from_config()` factory that reads its own dotted-prefix section from a shared dict (`wifi.*`, `mqtt.broker.*`, etc.) and returns typed configuration.  Apps load one `runtime_config.msgpack` at boot; libraries pull their slice out.  No global registry, no hand-written `if "key" in config:` walls.

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

User-app pattern (the 2-line bring-up):

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()                          # reads /runtime_config.msgpack
wifi = WifiService(WifiConfig.from_config(config))      # reads + types the wifi.* keys
```

Library-side pattern (`load_section` builds a typed config from the flat-key payload, used today by `chumicro-wifi`):

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
| `config` | Lazily-loaded module attribute: the deployed `RuntimeConfig`, or `None` when the file is absent.  First attribute access reads the file once and caches the result |
| `RuntimeConfig` | Lookup wrapper over the flat-key payload: `get(key[, default])`, `[key]` / `require(key)`, `in` check |
| `load_section(cls, config, *, prefix, required=…, optional=…)` | Build `cls(**kwargs)` by reading flat-prefix keys.  Used today by `chumicro-wifi`'s `WifiConfig.from_config`; available to any library whose constructor signature maps 1:1 to its config subkeys |
| `try_load_section(...)` | Soft variant: returns `None` instead of raising when `config` is `None`, the wrong type, or missing a required key |
| `MissingConfigKey` / `InvalidConfigType` / `ConfigError` | Targeted exceptions: single-inheritance from `ConfigError` (MicroPython forbids multi-parent layouts) |

## Where this fits

Depends on [`chumicro-msgpack`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/msgpack) for decode.  Most ChuMicro libraries with a `<Name>Config.from_config()` factory read their slice off the shared `RuntimeConfig` via `config.get(...)`; [`chumicro-wifi`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) additionally uses the `load_section` helper here.  Other consumers: [`chumicro-mqtt`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/mqtt), [`chumicro-ntp`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/ntp), [`chumicro-requests`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/requests), [`chumicro-websockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/websockets), [`chumicro-http_server`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/http_server).

## Platform support

Works on CPython, MicroPython, and CircuitPython.

## Examples

[`examples/end_to_end.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/config/examples/end_to_end.py) shows the full read → `load_section` → typed-config flow on CPython; see any consumer library (starting with `chumicro-wifi`) for the integrated usage shape.

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
