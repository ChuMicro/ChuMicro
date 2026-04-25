# Decision 0035: Runtime config file structure

Status: `accepted`
Date: `2026-04-25`
Related: Decision 0029 (project workspace), Decision 0030 (config vs persisted state), Decision 0034 (kvstore API).

## Context

Decision 0030 established that every thing carries one `config.toml`
which the deployer merges with workspace defaults + secrets into a
single `/runtime_config.msgpack` baked onto the device.  Decision
0030 stops at "the deployer writes a merged dict" — it does not pin
down *the shape* of that dict.

With Phase 3a (`chumicro-wifi`) about to land as the first library
that consumes a "real" config slice, we need the convention now so
chumicro-wifi doesn't define a layout future libraries (mqtt, app
code, sensor drivers) have to renegotiate.

The constraint surface:

- **One file per thing.**  Decision 0030 §1.  Adding a second config
  file per package would defeat the "one place users edit settings"
  principle.
- **Each library finds its slice without colliding with others.**
  `chumicro-wifi` reads its keys; `chumicro-mqtt` reads its keys; the
  app reads thing-specific keys.  Without a namespacing convention,
  flat keys like `ssid`, `port`, `broker` collide as soon as two
  libraries care about overlapping vocabulary.
- **The user edits TOML / YAML by hand**, so the on-host format has
  to be obvious — the section a config block belongs to should be
  spelled out, not derived from key names.
- **The deployer doesn't know what libraries the thing imports.**
  Schema validation per-library at deploy time would require every
  library to ship a schema descriptor; out of scope for the
  workspace-runtime work.

## Decisions

### 1. Top-level shape: section-namespaced dict

The msgpack payload at `/runtime_config.msgpack` decodes to a single
flat dict whose top-level keys are **section names**.  Each section
value is itself a dict of arbitrary depth.

```python
{
    "wifi": {
        "ssid": "HomeNet",
        "password": "actual-password",
        "hostname": "back-porch",
    },
    "mqtt": {
        "broker": "mqtt.home",
        "port": 1883,
        "client_id": "back-porch",
    },
    "app": {
        "sample_period_ms": 30000,
        "feature_flags": {"new_ui": True},
    },
}
```

A library's documentation calls out which section it consumes and
which keys are required vs optional.  At runtime, each library
extracts its slice and constructs its own typed config object — see
§4 below.

**Rejected:** flat dict with prefixed keys (`wifi_ssid`,
`mqtt_broker`).  Loses the visual grouping users want when editing
TOML, and doesn't extend cleanly to nested config (e.g.
`app.feature_flags.new_ui`).

### 2. Section key = library basename without `chumicro-` prefix

Convention: a library named `chumicro-<name>` reads from section
`<name>` by default.

| Library          | Default section key |
|------------------|---------------------|
| `chumicro-wifi`  | `wifi`              |
| `chumicro-mqtt`  | `mqtt`              |
| `chumicro-kvstore` | `kvstore`         |

Easy to remember, matches the import path (`chumicro_wifi` →
`wifi`), no per-library registry to maintain.  Libraries that don't
consume runtime config (`chumicro-timing`, `chumicro-runner`,
`chumicro-msgpack`) simply don't reserve a section.

The `app` section is reserved for thing-specific config that no
library owns — sample periods, feature flags, calibration values,
custom keys the user code reads directly.  Always available.

**Multiple instances** (rare): a thing wanting two MQTT clients
defines two sections with arbitrary names and wires them
explicitly:

```toml
[mqtt_primary]
broker = "primary.local"

[mqtt_backup]
broker = "secondary.local"
```

```python
primary = MqttClient(MqttConfig.from_dict(config["mqtt_primary"]))
backup  = MqttClient(MqttConfig.from_dict(config["mqtt_backup"]))
```

The library doesn't care that the section name isn't the canonical
one — it takes whatever dict the caller passes.  The convention is
about the *default*, not a constraint.

### 3. Library access pattern: dataclass + `from_dict` classmethod backed by `chumicro-config`

> **Amended 2026-04-25 by Decision 0036.**  The `from_dict`
> *implementation* now lives in a shared library
> (`chumicro-config`) so every consumer library calls the same
> standardized factory and the convention can't drift.  The shape
> below is unchanged — only the implementation moved.

Every library that consumes runtime config ships a `<Name>Config`
dataclass plus a `from_dict(d: dict) -> <Name>Config` classmethod.
The classmethod calls `chumicro_config.load_section`, which
implements the canonical missing-required / missing-optional /
unknown-key / non-dict-input semantics:

```python
# In chumicro_wifi:
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

User code in `app.py` is:

```python
from chumicro_config import load_runtime_config
from chumicro_wifi import WifiService, WifiConfig

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_dict(config["wifi"]))
```

(`load_runtime_config` is the on-device reader for
`/runtime_config.msgpack`, also part of `chumicro-config`.)

No magic.  The user explicitly wires sections to libraries — code
remains greppable, debuggable, and refactor-safe.  Tests construct
`WifiConfig(ssid="...", password="...")` directly without going
through the dict path.

**Rejected:** a generic `chumicro-config-runtime` library that loads
the file + dispatches to libraries.  Adds a published package for a
3-line user code path; doesn't earn its keep.  `chumicro-config`
(per Decision 0036) is helpers, not a dispatcher — the user still
explicitly wires `config["wifi"]` to `WifiConfig.from_dict`.

**Rejected:** each library shipping a `from_config_file()` helper
that reads `/runtime_config.msgpack` itself.  Forces every consumer
library to know about the on-device path + the file format, which
creates a dependency on the workspace-runtime ABI.  `from_dict` keeps
libraries config-source-agnostic.

### 4. Required vs optional keys

`from_dict` raises `KeyError` on missing **required** keys (no
guessing — fail loudly so deploy-time errors surface fast).
Optional keys use `dict.get(name, default)`.  The library's
documentation is the source of truth for which is which.

Defaults live in the dataclass field declaration *and* the
`from_dict` `.get()` call — duplicated on purpose so both
construction paths (direct kwargs in tests, dict-based in
production) get the same defaults without one path leaking.

### 5. Deep-merge semantics: per-key, not per-section

The deployer merges three sources into the final dict:

1. **`workspace.yml` defaults** (lowest precedence) — shared across
   every thing in the workspace.
2. **`things/<name>/config.toml`** (overrides workspace defaults).
3. **`secrets.yml`** entries resolved via `!secret <name>`
   references inside any of the above.

Merge is **deep, key-level** within sections: workspace's `[wifi]`
section + thing's `[wifi]` section combine key-by-key, with the
thing's keys winning.

```yaml
# workspace.yml
defaults:
  wifi:
    hostname_prefix: "chu-"
  mqtt:
    port: 1883
```

```toml
# things/back-porch/config.toml
[wifi]
ssid = "HomeNet"
password = "!secret wifi_password"
hostname = "back-porch"

[mqtt]
broker = "mqtt.home"
client_id = "back-porch"
```

```python
# Merged result on device:
{
    "wifi": {
        "hostname_prefix": "chu-",     # from workspace.yml
        "ssid": "HomeNet",             # from thing
        "password": "<resolved>",      # from secrets.yml
        "hostname": "back-porch",      # from thing
    },
    "mqtt": {
        "port": 1883,                  # from workspace.yml
        "broker": "mqtt.home",         # from thing
        "client_id": "back-porch",     # from thing
    },
}
```

Top-level sections present in either source carry through.  Sections
present only in workspace.yml become global defaults the thing
inherits without restating.

### 6. Schema validation policy: each library owns its own

The deployer **does not** validate per-library schemas at merge
time.  Every library is the source of truth for its own shape;
schema errors surface at runtime when `<Name>Config.from_dict` is
called.  This trades early detection for not requiring a schema
registry.

**Why:** the deployer doesn't know what libraries `app.py` imports,
and asking every published library to ship a schema descriptor adds
weight for marginal benefit.  Typos in `config.toml` propagate to
runtime; the library raises a clear `KeyError` or `TypeError` at
boot, which is good enough for the workspace-template flow.

The deployer **does** validate the *file-level* shape: TOML/YAML
parses cleanly, top-level structure is a dict of dicts, no `!secret`
reference is unresolved.  These are format-level checks, not
schema-level.

### 7. Unknown sections are ignored

A section in `config.toml` that no library consumes is **not** an
error.  The merged dict carries it through to device; it's simply
not read.  This matters for forward-compat: a thing that adds
`[mqtt_v2]` config in anticipation of a new library doesn't need
the library to be installed yet for the deploy to succeed.

User code reading `config["mqtt_v2"]` will `KeyError` on devices
where the section is missing — same as any other dict access.

### 8. File path on device: `/runtime_config.msgpack`

Decision 0030 §1 fixed this.  This ADR confirms the path is
verbatim — every library + the workspace template assumes that
exact location.  Changing it would be a workspace-runtime ABI
break.

### 9. Top-level reserved keys: none for now

The spec deliberately leaves *no* top-level reserved keys (no
`version`, no `deployed_at`, no `_meta`).  Adds clutter for
forward-compat we don't need yet.  If we later need versioning,
we add it as `_chu_meta` or similar (single-underscore convention
for internal keys — won't collide with user sections).

## Consequences

- `chumicro-wifi` (Phase 3a) ships with `WifiConfig` + `from_dict`
  reading section `wifi`.  Documentation calls out the section name
  + required vs optional keys explicitly.
- Future libraries (`chumicro-mqtt` Phase 6, sensor drivers) follow
  the same pattern — section name = library basename, `from_dict`
  pairs with the typed config dataclass.
- `chumicro-workspace-runtime` (Phase 4a) implements the deep-merge
  + secrets resolution + msgpack write.  This ADR fixes the input
  shape (TOML / YAML sections) and the output shape (section-keyed
  dict on device).
- The thing template's `AGENTS.md` documents the convention so
  third-party authors writing things outside the mono-repo follow
  the same shape.  The template ships with example sections for
  `wifi` and `app`.
- `kvstore` is **not** in this scheme — it's a runtime persistence
  store (Decision 0030, Decision 0034), not config.  A future
  decision could add `[kvstore]` config (`backend="auto"`,
  `capacity=...`) but slice 0–5 didn't surface the need.
- The "no schema registry" stance limits the deployer's ability to
  catch typos at deploy time.  If this becomes painful, a future
  ADR can add an opt-in schema descriptor without breaking the
  format defined here.
