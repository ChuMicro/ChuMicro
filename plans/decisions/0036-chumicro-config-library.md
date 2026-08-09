# Decision 0036: `chumicro-config` library — home of the runtime-config convention

Status: `accepted`
Date: `2026-04-25`
Summary: `chumicro-config` library ships flat-key `RuntimeConfig` + `load_section` factory; libraries expose `from_config` / `try_from_config` classmethods on their value-object or client-with-injection class.
Related: Decision 0030 (config vs persisted state), Decision 0035 (runtime config structure), Decision 0029 (project workspace), Decision 0010 (constructor injection + `testing.py`).

## Context

Decision 0035 settled the runtime-config layout but left the
*implementation* of the per-library config-loading helpers to each
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

The shape evolved over time.  Today's API (post the
config-shape-beginner-ergonomics workstream) treats the on-device
runtime config as a **flat dict with dotted keys** — `wifi.ssid`,
`mqtt.broker.host` — rather than nested sections.  Compose-time
flattening on the host produces that shape so the device-side
reader does one hash lookup per access, honoring the 256 KB-RAM
floor.  The library exposes that flat dict through a small
`RuntimeConfig` wrapper with beginner-friendly accessors (`.get`,
`[]`, `.require`).  The descriptions below reflect the current API.

## Decisions

### 1. Publish a small device library: `chumicro-config`

A library at `libraries/config/` (cross-runtime: CPython +
MicroPython + CircuitPython) ships the helpers ADR 0035 implies.
Surface:

- `chumicro_config.RuntimeConfig` — flat-key dict-like wrapper.
  `config.get("wifi.ssid")` returns `None` on miss;
  `config.get("wifi.ssid", default)` falls back; `config["wifi.ssid"]`
  raises `MissingConfigKey`; `config.require("wifi.ssid")` is the
  named-intent version of `[]`.  Membership and iteration work like
  a plain dict.
- `chumicro_config.load_section(target_class, config, *, prefix, required, optional)`
  — value-object factory used by libraries whose constructed
  object is a pure config-derived dataclass (see §3, Pattern A).
  Reads `f"{prefix}.{subkey}"` from the flat config and instantiates
  *target_class*.
- `chumicro_config.try_load_section(target_class, config, *, prefix, required, optional)`
  — soft-load sibling that returns `None` whenever `load_section`
  would raise (see §4 for the consumer pattern).
- `chumicro_config.load_runtime_config(path=...)` — explicit reader;
  raises `OSError` on missing file, `InvalidConfigType` on malformed
  payload.  Returns a `RuntimeConfig` directly so callers don't
  re-wrap.
- `chumicro_config.config` — module-level attribute carrying the
  loaded `RuntimeConfig` (or `None` when the file is missing).
  Lazy-loaded on first access via PEP 562 module-level `__getattr__`
  and cached for the lifetime of the import.  See §4 for the user
  pattern.
- `chumicro_config.MissingConfigKey` / `InvalidConfigType` /
  `ConfigError` — exception hierarchy.

Public surface re-exported from the package root so consumers write
`from chumicro_config import RuntimeConfig, config, load_section, load_runtime_config, try_load_section`.

Depends on `chumicro-msgpack` for the decode in `load_runtime_config`.

### 2. `load_section` reads flat keys with a shared prefix

```python
def load_section(target_class, config, *, prefix, required=(), optional=None):
    """Build *target_class* by reading flat keys with a shared prefix.

    Args:
        target_class: Called as ``target_class(**kwargs)`` where each
            kwarg name is the *subkey* and the value comes from
            ``config[f"{prefix}.{subkey}"]``.
        config: A ``RuntimeConfig`` or plain flat dict.
        prefix: Key prefix without trailing dot (e.g. ``"wifi"``).
        required: Tuple of subkey names that must be present.
        optional: Mapping of subkey name → default value.
    """
```

Behavior locked by this ADR (so libraries can't drift):

- Missing **required** key ⇒ `MissingConfigKey` (subclass of
  `ConfigError` only — MicroPython does not allow multiple
  inheritance from differing-layout `Exception` subclasses, so the
  appealing dual `(ConfigError, KeyError)` parent set isn't
  available cross-runtime; callers catch `ConfigError` instead).
- Missing **optional** key ⇒ default from *optional* mapping.
- *config* is `None` or not dict-like ⇒ `InvalidConfigType` (single
  parent for the same MP reason).
- **Unknown keys are ignored** (forward-compat for projects that
  stage future config keys).
- **No type coercion.**  `"1883"` stays a string; if the library
  wants an int, the dataclass `__init__` (or a manual cast inside
  the library's wrapper) does the conversion.  Keeps `load_section`
  predictable.

### 3. Library access pattern: two shapes, `from_config` + `try_from_config` on each

Every config-consuming library exposes a pair of classmethods —
`from_config(config)` (raises) and `try_from_config(config)`
(returns `None` on missing-required / not-dict-like / `config is
None`).  Both take the **whole flat runtime config**; the
classmethods know the section's prefix (e.g. `"wifi"`) and walk
into the right keys.

The methods live on *whichever class is the natural construction
target* for the library — and that class can take one of two
shapes.  Pick by the shape of what's being constructed:

**Pattern A — value-object (`load_section`-wrapping).**  Use when
every field of the constructed object maps 1:1 from a config
subkey, no non-config kwargs.  The methods wrap `load_section` /
`try_load_section` and the class is a pure dataclass.  Today's
live example: `chumicro-wifi`'s `WifiConfig`.

```python
class WifiConfig:
    def __init__(self, ssid: str, password: str, hostname: str | None = None, connect_timeout_ms: int = 15_000) -> None:
        ...

    @classmethod
    def from_config(cls, config) -> "WifiConfig":
        return load_section(
            cls, config,
            prefix="wifi",
            required=("ssid", "password"),
            optional={"hostname": None, "connect_timeout_ms": 15_000},
        )

    @classmethod
    def try_from_config(cls, config) -> "WifiConfig | None":
        return try_load_section(
            cls, config,
            prefix="wifi",
            required=("ssid", "password"),
            optional={"hostname": None, "connect_timeout_ms": 15_000},
        )
```

The required / optional vocabulary is duplicated in `__init__`'s
parameter defaults and the two factory calls — on purpose, so both
construction paths (direct kwargs, runtime-config) agree without a
metaclass deriving one from the other.

**Pattern B — client-with-injection (direct `config.get` reads).**
Use when the constructed object is a runner / client / service
that mixes config-derived fields with **non-config injectables**
(sockets, radios, TLS contexts, listeners, factories, event
handlers) or has **call-site logic** (mode-conditional sub-key
reads, broker-required guards, half-TLS guards, computed
defaults).  The methods do direct `config.get(...)` /
`config.require(...)` reads inside `from_config`; `try_from_config`
delegates after the dict-like guard.  Today's live examples:
`chumicro-mqtt`'s `MQTTClient`, `chumicro-ntp`'s `NTPClient`,
`chumicro-requests`'s `HttpClient`, `chumicro-websockets`'s
`WebSocketClient` / `WebSocketServer`, `chumicro-http-server`'s
`HttpServer`.

```python
class NTPClient:
    @classmethod
    def from_config(
        cls, config, *,
        socket=None, ticks=None, ...
    ) -> "NTPClient":
        server = config.get("ntp.server", DEFAULT_SERVER)
        port = config.get("ntp.port", DEFAULT_PORT)
        timeout_ms = config.get("ntp.timeout_ms", DEFAULT_TIMEOUT_MS)
        return cls(server=server, port=port, timeout_ms=timeout_ms,
                   socket=socket, ticks=ticks, ...)
```

Pattern B does *not* wrap `load_section` because: (i) `load_section`
calls `cls(**kwargs)` with config-only kwargs and has no slot for
non-config injectables, (ii) it has no hook for per-class guards
(mqtt's broker-required, http_server's listening-mode-conditional
TLS), and (iii) call-site logic per construction is clearer
inlined than carried via opaque `optional={}` defaults.

**Input guarding differs by pattern.**  Pattern A gets an
`isinstance(config, (RuntimeConfig, dict))` check built into
`load_section`, raising `InvalidConfigType` on `None` / `str` /
`int` / other-non-mapping.  Pattern B libraries either prepend a
one-line `hasattr(config, "get")` guard raising their own error
(`MQTTClient.from_config` raises `ValueError`) or let the first
`.get(...)` fail with `AttributeError`; no shared public predicate
exists.

**Rejected:** a `ConfigBase` mixin that introspects `_REQUIRED` / `_OPTIONAL` class attributes and auto-generates the methods.  The inheritance + class-attribute indirection saves three lines per library and adds magic the next reader has to chase.

**Rejected:** forcing Pattern A across all libraries by extending `load_section` with hooks for injectables + guards + conditional sub-keys.  The result becomes a kitchen-sink factory harder to read than the seven inline `from_config` bodies it would replace.

### 4. Reading the deployed runtime config — `config` attribute + `load_runtime_config()`

Two surfaces, picked by the calling pattern:

**`config` — the canonical user-facing attribute.**  Module-level
`RuntimeConfig | None` lazy-loaded on first access via PEP 562
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

wifi = WifiService(WifiConfig.from_config(config))
```

**`load_runtime_config(path=...)` — the explicit reader.**

```python
def load_runtime_config(path: str = "/runtime_config.msgpack") -> RuntimeConfig:
    """Return the deployed config as a flat-key RuntimeConfig.

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

### 6. `chumicro-deploy`'s `devices.yml` is out of scope

`devices.yml` is deploy-infrastructure config, not runtime app config — `chumicro-deploy` reads it through its own loader (Decision 0029 §8).  Using `load_section` for it would conflate two distinct contracts.

## Consequences

- One additional published library (`chumicro-config` ≈ 100–150
  lines).  Tiny scope, but distinct from existing libraries —
  doesn't fit `chumicro-compat` (compat is polyfills) or
  `chumicro-msgpack` (msgpack is the codec).
- Decision 0035 §3 names `chumicro-config` as the home of the per-library config-loading factory — the library's `load_section` is the canonical implementation (now flat-key shaped per the config-shape-beginner-ergonomics workstream).  The "no magic dispatcher" rejection in 0035 §3 still stands; this library is helpers, not a dispatcher.
- Every config-consuming library gains a dependency on `chumicro-config`.  The dep is workspace-internal and resolves through the existing topological-sort path in `validate-mip`.
- Future evolution (env-var fallbacks, layered defaults, per-key validators, type coercion, workbench host helpers) extends `chumicro-config` rather than forking each library's hand-rolled implementation.
