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
- `chumicro_config.section.try_load_section(cls, runtime_config, section_name, *, required, optional)`
  — the soft-load sibling that returns ``None`` instead of raising
  on missing/invalid input.  See §4 for the consumer pattern.
- `chumicro_config.runtime.load_runtime_config(path=...)` — explicit
  reader; raises `OSError` on missing file, `InvalidConfigType` on
  malformed payload.  Used when callers want precise error semantics
  or read a non-default path.
- `chumicro_config.runtime.config` — module-level attribute carrying
  the loaded `/runtime_config.msgpack` dict (or `None` when the file
  is missing).  Lazy-loaded on first access via PEP 562 module-level
  `__getattr__` and cached for the lifetime of the import; subsequent
  accesses return the same dict reference.  See §4 for the user
  pattern.
- `chumicro_config.MissingConfigKey` / `InvalidConfigType` /
  `ConfigError` — exception hierarchy.

Public surface re-exported from the package root so consumers write
`from chumicro_config import config, load_section, load_runtime_config, try_load_section`.

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
  log, no exception — forward-compat for projects that stage future
  config keys.
- **No type coercion.**  `"1883"` stays a string; if the library
  wants an int, the dataclass `__init__` (or a manual cast inside
  the library's wrapper) does the conversion.  Keeps `load_section`
  predictable.

### 3. Library access pattern: thin `from_dict` + `try_from_dict` wrappers

Each library declares its required + optional keys and exposes two
classmethods on its `<Name>Config` dataclass:

- `from_dict(section_data)` — wraps `load_section`.  Takes a *section*
  dict (typically `config["wifi"]`).  Raises on missing required keys.
- `try_from_dict(runtime_config)` — wraps `try_load_section`.  Takes
  the **whole runtime config dict** (typically the value of
  `chumicro_config.config`) and returns `None` when the section is
  missing/invalid.  The skip-friendly gate for app + test code:

  ```python
  from chumicro_config import config
  from chumicro_wifi import WifiConfig, WifiService

  wifi_cfg = WifiConfig.try_from_dict(config)
  if wifi_cfg is None:
      return  # not configured — skip / use defaults
  service = WifiService(wifi_cfg)
  ```

The required / optional vocabulary is duplicated in `__init__`'s
parameter defaults and the two factory calls — on purpose, so all
three construction paths (direct kwargs, section dict, whole
runtime config) agree without a metaclass deriving one from the
other.

```python
class WifiConfig:
    def __init__(self, ssid: str, password: str, hostname: str | None = None, connect_timeout_ms: int = 15_000) -> None:
        ...

    @classmethod
    def from_dict(cls, data: dict) -> "WifiConfig":
        return load_section(cls, data, required=("ssid", "password"), optional={"hostname": None, "connect_timeout_ms": 15_000})

    @classmethod
    def try_from_dict(cls, runtime_config: dict | None) -> "WifiConfig | None":
        return try_load_section(cls, runtime_config, section_name="wifi", required=("ssid", "password"), optional={"hostname": None, "connect_timeout_ms": 15_000})
```

**Rejected:** a `ConfigBase` mixin that introspects `_REQUIRED` / `_OPTIONAL` class attributes and auto-generates `from_dict` / `try_from_dict`.  The inheritance + class-attribute indirection saves three lines per library and adds magic the next reader has to chase.

### 4. Reading the deployed runtime config — `config` attribute + `load_runtime_config()`

Two surfaces, picked by the calling pattern:

**`config` — the canonical user-facing attribute.**  Module-level
`dict | None` lazy-loaded on first access via PEP 562
`__getattr__`; cached for the lifetime of the import.  Apps that
import `chumicro_config` for `InvalidConfigType` / `load_section`
without touching `config` pay no file-read cost.  `None` when
`/runtime_config.msgpack` is missing — apps gate on that to handle
the no-deployed-config path.  `InvalidConfigType` (file present
but malformed) is *not* caught at import: corruption is a hard
deploy failure that surfaces loudly on first access rather than
silently degrading to `config = None`.

```python
from chumicro_config import config
from chumicro_wifi import WifiConfig, WifiService

if config is None:
    return  # no runtime config deployed — skip / use defaults

wifi = WifiService(WifiConfig.from_dict(config["wifi"]))
```

**`load_runtime_config(path=...)` — the explicit reader.**

```python
def load_runtime_config(path: str = "/runtime_config.msgpack") -> dict:
    """Return the deployed config as a section-namespaced dict.

    Raises:
        OSError: file missing (device deployed without config).
        InvalidConfigType: payload doesn't decode to a dict.
    """
```

Used when callers need precise `OSError` semantics, want to
re-read after a fresh deploy, or read a non-default path (tests
typically monkey-patch `DEFAULT_RUNTIME_CONFIG_PATH` or pass an
explicit `path=`).

PEP 562 module-level `__getattr__` is supported on CPython,
MicroPython, and CircuitPython flash mode.  CircuitPython RAM mode
wraps source modules in a class-stub that bypasses PEP 562 — but
runtime configs aren't shipped in RAM mode anyway (the
`extra_files` staging path requires flash).

### 5. Templating convention: each library ships `_templates/config.toml`

Every library that consumes runtime config ships a starter TOML snippet at `src/chumicro_<name>/_templates/config.toml` containing a `[<section>]` block with required keys spelled out and optional keys commented inline.  The template ships inside `src/` so it lands in the wheel and is discoverable via `importlib.resources` after `pip install`.  ~200 bytes per library; the file rides along to device and is never read there.

`chumicro_config.templates.get_section_template(library_name) -> str` reads the snippet (CPython-only — `importlib.resources` doesn't exist on the embedded runtimes, and template collection is a host-side workspace-tooling concern).  `chumicro-workspace` consumes this from its `add-library` flow to assemble starter `projects/<name>/config.toml` files.

### 6. `chumicro-deploy`'s `devices.yml` is out of scope

`devices.yml` is deploy-infrastructure config, not runtime app config — `chumicro-deploy` reads it through its own loader (Decision 0029 §8).  Using `load_section` for it would conflate two distinct contracts.

## Consequences

- One additional published library (`chumicro-config` ≈ 100–150
  lines).  Tiny scope, but distinct from existing libraries —
  doesn't fit `chumicro-compat` (compat is polyfills) or
  `chumicro-msgpack` (msgpack is the codec).
- Decision 0035 §3 names `chumicro-config` as the home of `from_dict` — the library's `load_section` is the canonical implementation.  The "no magic dispatcher" rejection in 0035 §3 still stands; this library is helpers, not a dispatcher.
- Every config-consuming library gains a dependency on `chumicro-config`.  The dep is workspace-internal and resolves through the existing topological-sort path in `validate-mip`.
- Future evolution (env-var fallbacks, layered defaults, per-key validators, type coercion, workbench host helpers) extends `chumicro-config` rather than forking each library's hand-rolled implementation.
