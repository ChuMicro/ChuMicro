# User Guide

## Overview

`chumicro-config` is how ChuMicro libraries read their settings on a device.  Every consumer library (wifi, mqtt, ntp, kvstore, …) ships a typed `<Name>Config` class with a `from_config` classmethod that delegates to `load_section`.  Apps read the deployed `runtime_config.msgpack` once with `load_runtime_config()`, then hand the whole config to each consuming library — each library pulls its own prefix's keys.

Every library reads its keys using the same `<prefix>.<subkey>` dotted-key layout, so config parsing logic lives in one place instead of being reinvented per library.

## Getting started

In an app, the read is one line:

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()                       # /runtime_config.msgpack
wifi = WifiService(WifiConfig.from_config(config))   # reads + types wifi.* keys
```

`load_runtime_config()` opens `/runtime_config.msgpack` (the default path — see `DEFAULT_RUNTIME_CONFIG_PATH`), msgpack-decodes it, and returns a `RuntimeConfig` — a thin dict-like view over the flat-key payload.  Every chumicro library reads its own prefix's keys (`wifi.ssid`, `mqtt.broker`, …) from that one object.

## Writing a `from_config` for your own library

A consumer library's typed config class is ~10 lines:

```python
from chumicro_config import load_section


class WifiConfig:
    def __init__(self, ssid, password, hostname=None, connect_timeout_ms=15_000):
        self.ssid = ssid
        self.password = password
        self.hostname = hostname
        self.connect_timeout_ms = connect_timeout_ms

    @classmethod
    def from_config(cls, config):
        return load_section(
            cls,
            config,
            prefix="wifi",
            required=("ssid", "password"),
            optional={"hostname": None, "connect_timeout_ms": 15_000},
        )
```

`load_section` does four things:

1. Asserts `config` is a `RuntimeConfig` or plain dict — raises `InvalidConfigType` otherwise.
2. For each `required` subkey, pulls `config[f"{prefix}.{subkey}"]` — raises `MissingConfigKey` if any is absent.
3. For each `optional` subkey, pulls `config[f"{prefix}.{subkey}"]` if present, else uses the default.
4. Calls `cls(**kwargs)` and returns the instance.  Each kwarg name is the bare subkey (no prefix), so `WifiConfig` gets `ssid=…`, `password=…`, etc.

Unknown keys are **ignored** — that's deliberate forward-compat.  An older library version reads a config file that has newer libraries' keys in it without exploding on the unfamiliar prefixes.

There is no type coercion.  `"1883"` stays a string; the `__init__` does any conversion the library wants.

## Soft loading with `try_load_section`

`load_section` raises when required keys are missing — the strict path most libraries want.  When a section is genuinely optional (e.g. an MQTT section the user may not configure if the app doesn't publish), use `try_load_section`:

```python
from chumicro_config import try_load_section


@classmethod
def try_from_config(cls, config):
    return try_load_section(
        cls,
        config,
        prefix="mqtt",
        required=("broker",),
        optional={"port": 1883, "client_id": None},
    )
```

`try_load_section` returns `None` whenever `load_section` would raise — `config` is `None`, `config` is the wrong type, *or* any required key is absent.  Treat a `None` return as "this section wasn't configured; skip the feature."  Callers that want to distinguish "no config at all" from "partial config with a missing key" call `load_section` directly and catch `MissingConfigKey`.

## Exception handling

Three classes, one base:

| Exception | Raised when |
|---|---|
| `ConfigError` | Base — catch this to handle every config failure uniformly. |
| `MissingConfigKey` | A required key wasn't in the config. |
| `InvalidConfigType` | `config` itself wasn't a `RuntimeConfig` / dict (caller passed the wrong shape). |

```python
from chumicro_config import ConfigError, MissingConfigKey

try:
    wifi = WifiConfig.from_config(config)
except MissingConfigKey as error:
    print(f"Add wifi.* keys to your config: {error}")
    raise
except ConfigError:
    raise  # let it propagate; logs higher up
```

`MissingConfigKey` and `InvalidConfigType` are **single-inheritance only** — they do not also subclass `KeyError` or `TypeError`.  MicroPython rejects multiple inheritance from `Exception` subclasses with differing memory layouts, so the natural CPython idiom (`class MissingConfigKey(ConfigError, KeyError)`) doesn't load on device.  Catch via `ConfigError` if you want broad handling.

## On-device config shape

The runtime config is one msgpack file at `/runtime_config.msgpack`.  Its on-device shape is **flat with dotted keys** — one entry per `<prefix>.<subkey>`:

```python
{
    "wifi.ssid": "HomeNet",
    "wifi.password": "secret",
    "wifi.hostname": "back-porch",
    "mqtt.broker": "mqtt.local",
    "mqtt.port": 1883,
    "ntp.servers": ["pool.ntp.org"],
    "app.sample_period_ms": 5000,
}
```

On device, `load_runtime_config()` reads this file back and returns a `RuntimeConfig` that behaves like a flat dict — `config["wifi.ssid"]`, `"mqtt.broker" in config`, etc.

### How the workspace tool produces it

You can ignore this section if you're building the msgpack file yourself.  If you're using [`chumicro-workspace`](https://chumicro.github.io/ChuMicro/workspace/stable/), it composes the file from per-library TOML templates whose **source shape is nested** for human readability:

```toml
# project_config.toml — what the user edits.
[wifi]
ssid = "HomeNet"
password = "secret"
hostname = "back-porch"

[mqtt]
broker = "mqtt.local"
port = 1883

[ntp]
servers = ["pool.ntp.org"]

[app]
sample_period_ms = 5000
```

At deploy time the workspace tool flattens nested sections to dotted keys, merges per-library defaults, and msgpack-encodes the result using `msgpack(use_single_float=True)` for wire-compatibility with `chumicro-msgpack` on the device side.

## Templates submodule (host-only)

`chumicro_config.templates` ships separately — workspace tooling on the host imports it via `importlib.resources`, but device code never does.  It's not re-exported from `chumicro_config` at the package surface so a stray `from chumicro_config import templates` on a device fails fast rather than mid-call (`importlib.resources` is CPython-only).

## Platform notes

Works identically on CPython, MicroPython, and CircuitPython.  Only dependency: `chumicro-msgpack` (for the runtime-config decode path).

## Examples

| Example | What it shows |
|---|---|
| [`examples/end_to_end.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config/examples/end_to_end.py) | Both patterns — `<Name>Config.from_config()` for library authors, multi-section app wiring for users — plus `MissingConfigKey` / `InvalidConfigType` error handling.  Runs on every runtime; no device or `runtime_config.msgpack` needed. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) · \
[PyPI](https://pypi.org/project/chumicro-config/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
