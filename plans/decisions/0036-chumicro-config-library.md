# Decision 0036: `chumicro-config` library — home of the runtime-config convention

Status: `accepted`
Date: `2026-04-25`
Related: Decision 0030 (config vs persisted state), Decision 0035 (runtime config structure), Decision 0029 (project workspace), Decision 0010 (constructor injection + `testing.py`).

## Context

Decision 0035 settled the runtime-config layout (section-namespaced
dict, library basename = section key, `<Name>Config.from_dict`
classmethod) but left the *implementation* of `from_dict` to each
library.  Without a shared helper:

- Two libraries will inevitably disagree on what a missing optional
  key should do (default to `None`, raise, warn).
- Two libraries will inevitably disagree on whether to type-coerce
  values (`"1883"` vs `1883`).
- Two libraries will inevitably disagree on what to do with
  unexpected keys (ignore, warn, raise).
- Boilerplate `data["x"]` / `data.get("x", default)` repeats per
  library.
- The on-device file path (`/runtime_config.msgpack`) gets hard-coded
  in every library that reads it.

The convention from ADR 0035 needs a code home so it actually stays
uniform.  This ADR establishes that home.

## Decisions

### 1. Publish a small device library: `chumicro-config`

A new library at `libraries/config/` (cross-runtime: CPython +
MicroPython + CircuitPython) ships the helpers ADR 0035 implies.
Two-module API:

- `chumicro_config.section.load_section(cls, data, *, required, optional)`
  — the standardized factory every library's `from_dict` calls.
- `chumicro_config.runtime.load_runtime_config(path=...)` — reads +
  decodes `/runtime_config.msgpack` into the section-namespaced dict.
- `chumicro_config.MissingConfigKey` / `InvalidConfigType` /
  `ConfigError` — exception hierarchy.

Public surface re-exported from the package root so consumers write
`from chumicro_config import load_section, load_runtime_config`.

Depends on `chumicro-msgpack` for the decode in `load_runtime_config`.

### 2. `load_section` is the standardized `from_dict` core

```python
def load_section(target_class, data, *, required=(), optional=None):
    """Build *target_class* from a config-dict slice.

    Args:
        target_class: Called as ``target_class(**kwargs)`` with the
            keys the function extracts from *data*.
        data: The section dict, typically ``config["wifi"]``.
        required: Tuple of key names that must be present.  Missing
            ⇒ ``MissingConfigKey``.
        optional: Mapping of key name → default value.  Missing key
            ⇒ default; present key ⇒ value.
    """
```

Behavior locked by this ADR (so libraries can't drift):

- Missing **required** key ⇒ `MissingConfigKey` (subclass of
  `ConfigError` only — MicroPython does not allow multiple
  inheritance from differing-layout `Exception` subclasses, so the
  appealing dual `(ConfigError, KeyError)` parent set isn't
  available cross-runtime; callers catch `ConfigError` instead).
- Missing **optional** key ⇒ default from *optional* mapping.
- *data* is not a dict ⇒ `InvalidConfigType` (subclass of
  `ConfigError` only, same reason as above).
- **Unknown keys are ignored**, matching ADR 0035 §7.  No warning
  log, no exception — forward-compat for things that stage future
  config keys.
- **No type coercion.**  `"1883"` stays a string; if the library
  wants an int, the dataclass `__init__` (or a manual cast inside
  the library's wrapper) does the conversion.  Keeps `load_section`
  predictable.

### 3. Library access pattern: thin `from_dict` wrapper

Each library declares its required + optional keys and calls
`load_section`:

```python
# In chumicro_wifi.config:
from chumicro_config import load_section


class WifiConfig:
    def __init__(
        self,
        ssid: str,
        password: str,
        hostname: str | None = None,
        connect_timeout_ms: int = 15_000,
    ) -> None:
        self.ssid = ssid
        self.password = password
        self.hostname = hostname
        self.connect_timeout_ms = connect_timeout_ms

    @classmethod
    def from_dict(cls, data: dict) -> "WifiConfig":
        return load_section(
            cls,
            data,
            required=("ssid", "password"),
            optional={"hostname": None, "connect_timeout_ms": 15_000},
        )
```

The required / optional vocabulary is duplicated in `__init__`'s
parameter defaults and `from_dict`'s call — on purpose.  Both
construction paths (direct kwargs in tests, dict-based in
production) must agree, and writing them twice locally is more
readable than a metaclass that derives one from the other.

**Rejected:** a `ConfigBase` mixin that introspects `_REQUIRED` /
`_OPTIONAL` class attributes and auto-generates `from_dict`.  The
inheritance + class-attribute indirection saves three lines per
library and adds magic the next reader has to chase.  Three lines
per library is fine.

### 4. `load_runtime_config` reads + decodes the on-device file

```python
def load_runtime_config(path: str = "/runtime_config.msgpack") -> dict:
    """Return the deployed config as a section-namespaced dict.

    Raises:
        OSError: file missing (device deployed without config).
        InvalidConfigType: payload doesn't decode to a dict.
    """
```

Centralises the path constant + msgpack decode so user code is:

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_dict(config["wifi"]))
```

Saves the user from importing `msgpack` directly and from typing
the path.  The `path=` parameter exists so tests + multi-config
scenarios can point elsewhere.

### 5. Workbench helpers deferred

A future `chumicro_config.host` module could carry CPython-only
helpers — TOML / YAML loaders, deep-merge, `!secret` resolution —
for workbench packages that want to consume the same conventions
on the host side (e.g. a future deploy-time validator that
previews what `/runtime_config.msgpack` will look like).  Out of
scope for this commit; add when a workbench package actually
needs it.  When it lands it lives inside the same library so
"chumicro-config = the config convention" stays a single brand.

`chumicro-deploy`'s `devices.yml` reader stays separate — that file
is deploy-infrastructure config, not runtime app config; using
`load_section` for it would conflate two distinct contracts.

### 6. Adoption: every config-consuming library uses it

`chumicro-wifi` (Phase 3a) ships with `chumicro-config` as a runtime
dependency from day one.  Future libraries (`chumicro-mqtt` Phase 6,
sensor drivers in Phase 7) follow the same pattern.

Existing libraries (`chumicro-timing`, `chumicro-runner`,
`chumicro-msgpack`, `chumicro-compat`, `chumicro-kvstore`) don't
consume runtime config and don't add the dependency.  If any later
grows config (e.g. a future `chumicro-kvstore` that exposes
`backend="auto"` via `[kvstore]`), it adopts `load_section` at that
point.

## Consequences

- One additional published library (`chumicro-config` ≈ 100–150
  lines).  Tiny scope, but distinct from existing libraries —
  doesn't fit `chumicro-compat` (compat is polyfills) or
  `chumicro-msgpack` (msgpack is the codec).
- ADR 0035 §3 is amended to name `chumicro-config` as the home of
  `from_dict` — the library's `load_section` is now the canonical
  implementation.  The "no magic dispatcher" rejection in §3 still
  stands; this library is helpers, not a dispatcher.
- Every config-consuming library gains one dependency
  (`chumicro-config`).  The dep is workspace-internal and resolves
  through the existing topological-sort path in `validate-mip`.
- `chumicro-wifi` (Phase 3a) is the first adopter; lands with
  `WifiConfig.from_dict` calling `load_section` per §3 above.
- Future evolution lives in one place: env-var fallbacks, layered
  defaults, per-key validators, type coercion (if we ever want it),
  workbench host helpers — all extend `chumicro-config` rather than
  forking each library's hand-rolled implementation.
- Scaffolding: `python scripts/run.py new-library config`
  generates the standard layout; manual fill-in of `section.py` +
  `runtime.py` content + tests + dep on `chumicro-msgpack`.
