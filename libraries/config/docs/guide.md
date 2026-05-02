# User Guide

## Overview

`chumicro-config` is the canonical way ChuMicro libraries read their settings on a device.  Every consumer library (wifi, mqtt, ntp, kvstore, …) ships a typed `<Name>Config` class with a `from_dict` factory that delegates to `load_section`.  Apps read the deployed `runtime_config.msgpack` once with `load_runtime_config()`, then hand each section to the consuming library.

The library is intentionally tiny: a single shared exception hierarchy, a single `load_section` factory, and a single `load_runtime_config` reader.  The convention it locks in (Decisions [0035](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0035-runtime-config-structure.md) / [0036](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0036-chumicro-config-library.md)) is what gives every chumicro library identical config semantics.

## Getting started

In an app, the read is one line:

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()                           # /runtime_config.msgpack
wifi = WifiService(WifiConfig.from_dict(config["wifi"]))
```

`load_runtime_config()` opens `/runtime_config.msgpack` (the canonical path — see `DEFAULT_RUNTIME_CONFIG_PATH`), msgpack-decodes it, asserts the result is a section-keyed dict, and returns it.  Every chumicro library reads its own section out of that dict.

## Writing a `from_dict` for your own library

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
    def from_dict(cls, data):
        return load_section(
            cls,
            data,
            required=("ssid", "password"),
            optional={"hostname": None, "connect_timeout_ms": 15_000},
        )
```

`load_section` does four things:

1. Asserts `data` is a dict — raises `InvalidConfigType` otherwise.
2. Pulls every `required` key — raises `MissingConfigKey` if any is absent.
3. Pulls every `optional` key, falling back to its default value.
4. Calls `cls(**kwargs)` and returns the instance.

Unknown keys are **ignored** — that's deliberate forward-compat.  An older library version reads a `config["wifi"]` block written by a newer workspace template without exploding on keys it doesn't know.

There is no type coercion.  `"1883"` stays a string; the `__init__` does any conversion the library wants.

## Exception handling

Three classes, one base:

| Exception | Raised when |
|---|---|
| `ConfigError` | Base — catch this to handle every config failure uniformly. |
| `MissingConfigKey` | A required key wasn't in the section dict. |
| `InvalidConfigType` | The section value wasn't a dict (caller passed the wrong shape). |

```python
from chumicro_config import ConfigError, MissingConfigKey

try:
    wifi = WifiConfig.from_dict(config.get("wifi", {}))
except MissingConfigKey as error:
    print(f"Add a wifi section to your config: {error}")
    raise
except ConfigError:
    raise  # let it propagate; logs higher up
```

`MissingConfigKey` and `InvalidConfigType` are **single-inheritance only** — they do not also subclass `KeyError` or `TypeError`.  MicroPython rejects multiple inheritance from `Exception` subclasses with differing memory layouts, so the natural CPython idiom (`class MissingConfigKey(ConfigError, KeyError)`) doesn't load on device.  Catch via `ConfigError` if you want broad handling.

## Section-namespaced config layout

The runtime config is one msgpack file at `/runtime_config.msgpack`.  Its top-level shape is **section-namespaced** — one key per consuming library:

```toml
# What the workspace tool merges from per-library config.toml templates.
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

The workspace tool encodes this to msgpack at deploy time using the wire-format-compatible PyPI `msgpack(use_single_float=True)` encoding (see `chumicro-msgpack`'s wire-compatibility note).  On device, your app reads it back as a regular Python dict.

## Templates submodule (host-only)

`chumicro_config.templates` ships separately — workspace tooling on the host imports it via `importlib.resources`, but device code never does.  It's not re-exported from `chumicro_config` at the package surface so a stray `from chumicro_config import templates` on a device fails fast rather than mid-call (`importlib.resources` is CPython-only).

## Platform notes

Works identically on CPython, MicroPython, and CircuitPython.  Only dependency: `chumicro-msgpack` (for the runtime-config decode path).

## Examples

| Example | What it shows |
|---|---|
| [`examples/end_to_end.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config/examples/end_to_end.py) | Both patterns — `<Name>Config.from_dict()` for library authors, three-section app wiring for users.  Runs on every runtime; no device or `runtime_config.msgpack` needed. |

## What's new

- **0.0.1**: Initial library — `load_runtime_config`, `load_section`, exception hierarchy.

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) · \
[PyPI](https://pypi.org/project/chumicro-config/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
