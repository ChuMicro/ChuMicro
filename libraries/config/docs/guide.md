# User Guide

## Overview

`chumicro-config` reads a project's settings on the board.  A deploy stores them in one file, `/runtime_config.msgpack`, as a flat dict whose keys are dotted names such as `wifi.ssid`, `mqtt.broker.host`, and `sensor.period_ms`.  `load_runtime_config()` reads the file and returns a `RuntimeConfig`, which answers lookups like a dict.  Each ChuMicro library has a `from_config(config)` method that reads the settings under its own prefix, such as `wifi.*` or `mqtt.*`, so one `RuntimeConfig` configures every library in a program.

`load_section` builds an object of your own class from every setting under one prefix.  It gives your own class the same kind of `from_config` method.

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

`RuntimeConfig(dict)` builds the settings object from a dict, so the code runs without a settings file.  On a deployed board, `load_runtime_config()` opens `/runtime_config.msgpack`, unpacks it, and returns the same kind of object.  It raises `OSError` when the file is missing.  `chumicro_config.config` holds the same object with no call, read from the file on first use.  On a board with no settings file it is `None`.

Each ChuMicro library takes that one object and reads its own settings from it:

```python
from chumicro_wifi import WifiService

wifi = WifiService.from_config(config)   # reads wifi.ssid, wifi.password, ...
```

## Writing a `from_config` for your own class

A `from_config(config)` class method builds an object from the settings, the way every ChuMicro library does.  The arguments `__init__` takes pick one of two ways to write it:

- **Every argument is a setting: call `load_section`.**  When each `__init__` argument matches one setting under a prefix, `load_section` collects the settings and calls the class.  `WifiConfig` in `chumicro-wifi` works this way.
- **Some arguments are objects, or the method needs logic: read the keys yourself.**  A socket, a radio, a clock, or a callback has no place in a settings file.  A method that picks its keys by a mode, or that requires one setting only when another is set, needs an `if`.  Either kind of method calls `config.get` and `config.require` itself.  The mqtt, ntp, requests, websockets, and http_server clients work this way.

Start with `load_section`.  Switch to reading keys once `__init__` needs an argument from outside the settings, or the method needs an `if`.

### Every argument is a setting: `load_section`

When the keyword arguments of `__init__` line up with the settings under one prefix, `load_section` builds the object in one call:

```python
from chumicro_config import RuntimeConfig, load_section


class SensorConfig:
    def __init__(self, name, period_ms=5000, units="C"):
        self.name = name
        self.period_ms = period_ms
        self.units = units

    @classmethod
    def from_config(cls, config):
        return load_section(
            cls,
            config,
            prefix="sensor",
            required=("name",),
            optional={"period_ms": 5000, "units": "C"},
        )


sensor = SensorConfig.from_config(RuntimeConfig({"sensor.name": "back-porch"}))
print(sensor.name, sensor.period_ms, sensor.units)   # back-porch 5000 C
```

In order, `load_section`:

1. Raises `InvalidConfigType` unless `config` is a `RuntimeConfig` or a plain dict.
2. Reads `config[f"{prefix}.{subkey}"]` for each `required` subkey, and raises `MissingConfigKey` when one is absent.
3. Reads `config[f"{prefix}.{subkey}"]` for each `optional` subkey, or takes the default when it is absent.
4. Calls `cls(**kwargs)` with each value under its bare subkey, so `SensorConfig` receives `name=…`, `period_ms=…`, and `units=…`, and returns the new object.

`load_section` skips the keys it was not asked for, so an older library keeps working when the settings file holds keys that only a newer library reads.

`load_section` passes each value through as stored.  A `"1883"` stays a string.  `__init__` converts what it needs.

### Objects or logic: read keys with `config.get`

This class takes a sensor object, which no settings file can hold, and checks one setting before it uses it:

```python
from chumicro_config import RuntimeConfig


class Thermometer:
    def __init__(self, sensor, period_ms=5000, units="C"):
        self.sensor = sensor
        self.period_ms = period_ms
        self.units = units

    @classmethod
    def from_config(cls, config, *, sensor):
        units = config.get("thermometer.units", "C")
        if units not in ("C", "F"):
            raise ValueError(f"thermometer.units must be C or F, got {units!r}")
        return cls(sensor, period_ms=config.get("thermometer.period_ms", 5000), units=units)


thermometer = Thermometer.from_config(RuntimeConfig({"thermometer.units": "F"}), sensor=None)
print(thermometer.period_ms, thermometer.units)   # 5000 F
```

`MQTTClient.from_config` takes the same form.  It accepts a `socket` object from the caller.  It requires `mqtt.broker.host` and `mqtt.broker.port` only when the caller passes no socket.  `load_section`'s `required` and `optional` lists hold neither of those.

A method in this form needs no type check of its own.  A `None` or a number passed in place of the settings fails on the first `.get(...)` with `AttributeError`, at the line that made the call.  `MQTTClient.from_config` checks `hasattr(config, "get")` first and raises `ValueError` with a clearer message.

## Optional sections with `try_load_section`

`try_load_section` takes the same arguments as `load_section`.  It returns `None` wherever `load_section` would raise: when `config` is `None`, when `config` is the wrong type, and when a required key is absent.  A `None` result means the project left that section out.  The program then skips the feature:

```python
from chumicro_config import RuntimeConfig, try_load_section


class BrokerConfig:
    def __init__(self, host, port=1883):
        self.host = host
        self.port = port

    @classmethod
    def try_from_config(cls, config):
        return try_load_section(
            cls,
            config,
            prefix="mqtt.broker",
            required=("host",),
            optional={"port": 1883},
        )


broker = BrokerConfig.try_from_config(RuntimeConfig({"wifi.ssid": "HomeNet"}))
if broker is None:
    print("No mqtt.broker settings, so publishing stays off")
```

To tell a project with no settings at all apart from a section with a missing key, call `load_section` and catch `MissingConfigKey`.

## Errors

| Exception | Raised when |
|---|---|
| `ConfigError` | Base class of the other two.  Catch it to handle every config failure. |
| `MissingConfigKey` | A required key is absent. |
| `InvalidConfigType` | `config` is not a `RuntimeConfig` or dict, or the settings file does not unpack to a dict. |

```python
from chumicro_config import ConfigError, MissingConfigKey

try:
    sensor = SensorConfig.from_config(config)
except MissingConfigKey as error:
    print(f"Add the missing setting to your project config: {error}")
    sensor = None
except ConfigError as error:
    print(f"The settings could not be read: {error}")
    sensor = None
```

`MissingConfigKey` and `InvalidConfigType` subclass `ConfigError` alone, so `except KeyError` and `except TypeError` miss them.  MicroPython refuses a class that inherits from two exception types with different memory layouts.  The CPython idiom `class MissingConfigKey(ConfigError, KeyError)` therefore fails to load on a board.

## On-device config shape

`/runtime_config.msgpack` holds one flat dict, with one entry per `<prefix>.<subkey>`:

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

`load_runtime_config()` returns it as a `RuntimeConfig`, so `config["wifi.ssid"]` and `"mqtt.broker.host" in config` work as they do on a dict.

### How the workspace tool produces it

A [`chumicro-workspace`](https://chumicro.com/ChuMicro/workspace/stable/) deploy writes this file from the TOML tables in `secrets.toml` and `project_config.toml`.  The workspace guide's [How config flows from your edits to the device](https://chumicro.com/ChuMicro/workspace/stable/guide/#how-config-flows-from-your-edits-to-the-device) shows a table such as `[mqtt.broker]` turning into the `mqtt.broker.*` keys.

To write the file without the workspace tool, pack a flat dict like the one above with PyPI `msgpack` and `use_single_float=True`.  [Wire-format compatibility with PyPI `msgpack`](https://chumicro.com/ChuMicro/msgpack/stable/guide/#wire-format-compatibility-with-pypi-msgpack) covers that flag.

## Platform notes

The library works the same on CPython, MicroPython, and CircuitPython.  `load_runtime_config()` unpacks the file with `chumicro-msgpack`, the library's only dependency.

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
