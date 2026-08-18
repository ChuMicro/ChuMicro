# Deploy refused, or ImportError on boot

Before a deploy copies anything, it walks your project's imports and refuses when one resolves to no file it can ship, so you learn about a missing module on your laptop instead of on the board.  If an unresolved import slips past that check, the board raises `ImportError` on its first boot instead.  This page covers the import and naming problems that stop a deploy or crash the first run.

## "an import in the bundle resolves to no deployed file and is not a known device built-in" (or `ImportError: no module named X` on boot)

An import points at something the deploy couldn't find: a ChuMicro library that isn't installed, a project-local helper imported by the wrong path, or an external package whose source isn't on the board (pip installs land on your laptop only, never the device).

The fix depends on which one it is:

- ChuMicro library: add it so the deploy ships it.

```bash
chumicro-workspace library add chumicro_mqtt
```

- Project-local helper: fix the import path, or move code shared between projects into `shared/`.
- External package: drop its source tree under `packages/`, where the deploy's import walker finds it.
- Genuinely optional import: wrap it in `try` / `except ImportError` so a missing module is tolerated.

## `chumicro-workspace new` rejects the project name, or `import projects.<name>.app` fails at deploy

The runtime imports your project as a Python package, so every part of the path has to be a valid Python identifier: letters, digits, and underscores only, with no hyphens, no dots, and no leading digit.

Use underscores.  Rename `back-porch` to `back_porch`, and `1sensor` to `sensor_one`.  `chumicro-workspace new` checks the name up front and fails fast with the reason.

## `from shared.foo import bar` refused at deploy, or `ImportError` on boot

The deploy search path roots at the `shared/` directory itself, so `shared/foo.py` ships as the top-level module `foo`.  There is no `shared` package on the board to import from.  (background: [Decision 0110](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0110-shared-imports-by-bare-module-name.md))

Import shared modules by their bare name:

```python
from foo import bar
# or
import foo
```

The deploy tool appends this bare-name hint to the refusal message.

## `MQTTClient.from_config(...)` raises `RuntimeError` naming a bypass keyword, or a deploy names missing factory families

The sockets library `chumicro_sockets`, which supplies the network transport, was filtered out by a skip marker or never installed, or a factory module isn't at its expected `*_factory.py` path.

Install the sockets library:

```bash
chumicro-workspace library add chumicro_sockets
```

Or hand the transport in yourself with `transport_factory=` (MQTT and NTP also accept `socket=`).  If a skip entry is filtering the sockets library out, fix or remove that entry, and keep factory files at the `*_factory.py` path.
