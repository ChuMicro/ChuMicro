# User Guide

## Overview

`chumicro-config` reads a project's settings on the board.  The settings live in one file, `/runtime_config.msgpack`, as a flat dict whose keys are dotted names: `wifi.ssid`, `mqtt.broker.host`, `sensor.period_ms`.  `load_runtime_config()` reads the file and returns a `RuntimeConfig`, which you query like a dict.  Each ChuMicro library has a `from_config(config)` method that reads the settings under its own prefix (`wifi.*`, `mqtt.*`), so your code hands one object to every library instead of passing each setting by hand.

`load_section` builds an object of your own class from every setting under one prefix.  Use it to give your own code, or a library you write, the same kind of `from_config` method.

## Getting started

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

`RuntimeConfig(dict)` builds the settings object from a dict, which lets you try the code without a settings file.  On a deployed board, `load_runtime_config()` opens `/runtime_config.msgpack`, unpacks it, and returns the same kind of object; it raises `OSError` when the file is missing.  `chumicro_config.config` gives you the same object without the call: it reads the file the first time you use it and is `None` when the board has no settings file.

Pass that one object to each ChuMicro library you use, and each reads its own settings:

```python
from chumicro_wifi import WifiService

wifi = WifiService.from_config(config)   # reads wifi.ssid, wifi.password, ...
```

## Writing a `from_config` for your own class

A `from_config(config)` class method builds your object from the settings, the way every ChuMicro library does.  Which way to write it depends on what `__init__` takes:

- **Every argument is a setting: use `load_section`.**  When each `__init__` argument matches one setting under a prefix and nothing else gets passed in, `load_section` does the work.  `WifiConfig` in `chumicro-wifi` works this way.
- **Some arguments are objects, or the method needs logic: read the keys yourself.**  When `__init__` also takes objects that cannot live in a settings file (a socket, a radio, a clock, a callback), or the method has to decide something (which keys to read depends on a mode, one setting requires another), call `config.get` and `config.require` directly.  The mqtt, ntp, requests, websockets, and http_server clients work this way.

Start with `load_section`, and switch to reading keys yourself once you need an argument that is not a setting or an `if` inside the method.

### Every argument is a setting: `load_section`

When the constructor's keyword arguments line up with the settings under one prefix, `load_section` builds the object in one call:

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

1. Asserts `config` is a `RuntimeConfig` or plain dict, raising `InvalidConfigType` otherwise.
2. For each `required` subkey, pulls `config[f"{prefix}.{subkey}"]`, raising `MissingConfigKey` if any is absent.
3. For each `optional` subkey, pulls `config[f"{prefix}.{subkey}"]` if present, else uses the default.
4. Calls `cls(**kwargs)` and returns the instance.  Each kwarg name is the bare subkey (no prefix), so `WifiConfig` gets `ssid=…`, `password=…`, etc.

`load_section` ignores keys it was not asked for, so an older library keeps working when the settings file holds keys that only a newer library reads.

`load_section` converts nothing: `"1883"` stays a string, and `__init__` does any conversion the class wants.

### Objects or logic: read keys with `config.get`

When the class also takes objects that do not come from the settings file, or its method needs an `if`, `load_section` has no place for either.  Read the keys directly:

```python
class NTPClient:
    @classmethod
    def from_config(cls, config, *, socket=None, ticks=None):
        server = config.get("ntp.server", "pool.ntp.org")
        port = config.get("ntp.port", 123)
        timeout_ms = config.get("ntp.timeout_ms", 5_000)
        return cls(
            server=server, port=port, timeout_ms=timeout_ms,
            socket=socket, ticks=ticks,
        )
```

This method needs no type check up front.  Passing `None` or a number in place of the settings fails on the first `.get(...)` with `AttributeError`, which points straight at the call.  `MQTTClient.from_config` adds a one-line `hasattr(config, "get")` check that raises `ValueError` instead.

`MQTTClient.from_config` shows why this form exists: it reads `mqtt.broker.host`, takes a `socket` object from the caller, and refuses to build a client with no broker set.  None of that fits `load_section`'s `required` and `optional` lists.

## Soft loading with `try_load_section`

`load_section` raises when required keys are missing, the strict path most libraries want.  When a section is genuinely optional (e.g. an MQTT section the user may not configure if the app doesn't publish), use `try_load_section`:

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

`try_load_section` returns `None` whenever `load_section` would raise: `config` is `None`, `config` is the wrong type, *or* any required key is absent.  Treat a `None` return as "this section wasn't configured; skip the feature."  Callers that want to distinguish "no config at all" from "partial config with a missing key" call `load_section` directly and catch `MissingConfigKey`.

## Exception handling

Three classes, one base:

| Exception | Raised when |
|---|---|
| `ConfigError` | Base; catch this to handle every config failure uniformly. |
| `MissingConfigKey` | A required key wasn't in the config. |
| `InvalidConfigType` | `config` itself wasn't a `RuntimeConfig` / dict (caller passed the wrong shape). |

```python
from chumicro_config import ConfigError, MissingConfigKey

try:
    wifi_config = WifiConfig.from_config(config)
except MissingConfigKey as error:
    print(f"Add the missing setting to your project config: {error}")
    wifi_config = None
except ConfigError as error:
    print(f"The settings could not be read: {error}")
    wifi_config = None
```

`MissingConfigKey` and `InvalidConfigType` are **single-inheritance only**.  They do not also subclass `KeyError` or `TypeError`.  MicroPython rejects multiple inheritance from `Exception` subclasses with differing memory layouts, so the natural CPython idiom (`class MissingConfigKey(ConfigError, KeyError)`) doesn't load on device.  Catch via `ConfigError` if you want broad handling.

## On-device config shape

The runtime config is one msgpack file at `/runtime_config.msgpack`.  Its on-device shape is **flat with dotted keys**, one entry per `<prefix>.<subkey>`:

```python
{
    "wifi.ssid": "HomeNet",
    "wifi.password": "secret",
    "wifi.hostname": "back-porch",
    "mqtt.broker.host": "mqtt.local",
    "mqtt.broker.port": 1883,
    "ntp.server": "pool.ntp.org",
    "app.sample_period_ms": 5000,
}
```

On device, `load_runtime_config()` reads this file back and returns a `RuntimeConfig` that behaves like a flat dict: `config["wifi.ssid"]`, `"mqtt.broker.host" in config`, etc.

### How the workspace tool produces it

You can ignore this section if you're building the msgpack file yourself.  If you're using [`chumicro-workspace`](https://chumicro.com/ChuMicro/workspace/stable/), it composes the file from per-library TOML templates whose **source shape is nested** for human readability:

```toml
# project_config.toml, what the user edits.
[wifi]
ssid = "HomeNet"
password = "secret"
hostname = "back-porch"

[mqtt.broker]
host = "mqtt.local"
port = 1883

[ntp]
server = "pool.ntp.org"

[app]
sample_period_ms = 5000
```

At deploy time the workspace tool flattens nested sections to dotted keys, merges per-library defaults, and msgpack-encodes the result using `msgpack(use_single_float=True)` for wire-compatibility with `chumicro-msgpack` on the device side.

## Platform notes

Works identically on CPython, MicroPython, and CircuitPython.  Only dependency: `chumicro-msgpack` (for the runtime-config decode path).

## Examples

| Example | What it shows |
|---|---|
| [`examples/end_to_end.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config/examples/end_to_end.py) | Reads settings with `config.get`, builds a `SensorConfig` through a `from_config()` method that calls `load_section`, catches `MissingConfigKey`, then takes a pretend reading every `sensor.period_ms` forever.  Runs on every runtime without a settings file. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) · \
[PyPI](https://pypi.org/project/chumicro-config/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
