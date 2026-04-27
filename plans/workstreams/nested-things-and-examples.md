# Workstream: Nested things + examples folder

Status: `planned` — drafted 2026-04-27.  Phase 1 of the umbrella `workspace-ecosystem.md` workstream.

## Why

Today's `things/<name>/` layout is flat — one level deep.  Real workspaces accumulate things and need namespacing: `things/upstairs/bedroom_sensor/`, `things/garage/sensors/door_open/`, etc.  Beyond UX, namespacing is the natural shape for a multi-room / multi-zone deployment and pairs well with MQTT topic hierarchies.

A second pressure point: the workspace template ships exactly one worked example (`things/example_sensor/`).  The library-level examples (`libraries/{requests,mqtt,http_server}/examples/circuitpython_*.py`) showcase individual libraries but aren't wired as full workspace projects.  Multi-thing demos (server + client) don't fit the flat layout cleanly without polluting `things/` with non-user content.  Solution: a separate `examples/` folder of complete worked projects, leveraging the new nested layout for things like `examples/two_things/{server,sensor}/`.

The two changes are coupled — `examples/two_things/` is itself a nested layout, so the deploy machinery needs to handle nesting before the examples make sense.

## Folder convention

A directory under `things/` (or under `examples/<example>/`) is one of three things:

* **Thing** — leaf folder containing an entry-point file (`app.py`, `code.py`, or `main.py`).  This is what gets deployed.
* **Namespace** — folder containing only sub-folders (or sub-folders + Markdown / `.txt` documentation).  Pure organisational structure; no entry point.
* **Supporting** — folder containing files but no entry point AND no descendant things.  Silently ignored by deploy / list / new.  Lets users park `docs/`, design notes, etc. anywhere in the tree without flagging them.

Validation rule: each path segment must independently be a valid Python identifier (no hyphens, dots, leading digits, leading underscore).  The on-device import path is `things.<seg1>.<seg2>.app`, so each segment must satisfy Python's import grammar.

## Detection algorithm

```
def classify(path: Path) -> Literal["thing", "namespace", "supporting"]:
    if any((path / name).is_file() for name in ("app.py", "code.py", "main.py")):
        return "thing"
    sub_things = any(
        classify(child) in ("thing", "namespace")
        for child in path.iterdir()
        if child.is_dir() and not child.name.startswith(("_", "."))
    )
    return "namespace" if sub_things else "supporting"
```

`list_things()` walks `things/` recursively, returns paths-relative-to-things-dir for every classified `"thing"` (slash-form).  Stops recursing at thing boundaries — once a folder is a thing, its sub-folders aren't more things (they're the thing's internal structure).

## Name resolution from CLI

User-typed names accept three shapes:

| Shape | Example | Behaviour |
|---|---|---|
| Bare | `bedroom_sensor` | Look up across the entire tree.  If unique → that thing.  If ambiguous → list candidates + exit 2. |
| Slash | `upstairs/bedroom_sensor` | Direct.  Files under `things/upstairs/bedroom_sensor/`. |
| Dotted | `upstairs.bedroom_sensor` | Direct.  Same as slash — accepted because it matches the on-device import path. |

Disambiguation message:

```
deploy: 'thing1' is ambiguous — multiple things match:
  upstairs/thing1
  garage/thing1
specify the path: `python run.py deploy upstairs/thing1`
```

Default behaviour with **no positional name**: deploy if the workspace has exactly one thing across the whole tree.  Two-or-more is an error.  Same shape as today's flat-layout default.

## On-device shape

`THING_NAME` in `/active.py` becomes the dotted import path:

```python
# /active.py — written by deploy
THING_NAME = "upstairs.bedroom_sensor"
```

`workspace_runtime.boot()` already does `module_path = "things." + thing_name + ".app"` — that line stays unchanged, just receives a dotted name instead of a bare name.

The boot-shim file generator emits an `__init__.py` for **every** namespace level:

```
/lib/things/__init__.py                          (already present)
/lib/things/upstairs/__init__.py                 (new — namespace)
/lib/things/upstairs/bedroom_sensor/__init__.py  (new — thing init)
/lib/things/upstairs/bedroom_sensor/app.py       (the thing's app)
```

All `__init__.py` files at namespace levels are empty bytes.  Avoids PEP 420 namespace packages (more fragile on MP / CP than regular packages).

## CLI command behaviour

### `python run.py new <path>`

Accepts bare, slash, or dotted forms.  Auto-creates intermediate namespace dirs as needed.  Each path segment validated.

```bash
python run.py new bedroom_sensor                      # things/bedroom_sensor/
python run.py new upstairs/bedroom_sensor             # things/upstairs/bedroom_sensor/
python run.py new garage/sensors/door_open            # things/garage/sensors/door_open/
```

`--from <example-path>` flag added: `cp -r <example>` instead of `cp -r things/_template`:

```bash
python run.py new garage/heater --from examples/two_things/server
```

### `python run.py deploy [<path>]`

Same shape as today; accepts bare/slash/dotted or no positional (single-thing default).  Adds disambiguation prompt for bare names.

### `python run.py things [--flat | --tree]`

Default: tree view.

```
$ python run.py things
things/
├── thermostat
├── upstairs/
│   ├── bedroom_sensor
│   └── nightstand_lamp
└── garage/
    ├── sensors/
    │   └── door_open
    └── controls/
        └── heater
```

`--flat` for plain output (one thing per line, slash-form):

```
$ python run.py things --flat
thermostat
upstairs/bedroom_sensor
upstairs/nightstand_lamp
garage/sensors/door_open
garage/controls/heater
```

### `python run.py rename <old-path> <new-path>`

Path-aware.  Old + new can both be bare/slash/dotted.  Renames the directory, updates any `/active.py` references on probed devices (skip with `--no-update-devices`).

### `python run.py switch <path>`

Same disambiguation as deploy.  Accepts bare/slash/dotted.

## Examples folder

Lives at the workspace root, **separate from** `things/`:

```
examples/                                 ← top-level
  README.md                               ← index of every example
  hello_world/                            ← single-thing trivial
    README.md
    app.py
    config.toml
  two_things/                             ← multi-thing namespace
    README.md                             ← walkthrough
    server/                               ← thing
      app.py
      config.toml
    sensor/                               ← thing
      app.py
      config.toml
  periodic_get/                           ← single-thing requests demo
    README.md
    app.py
    config.toml
  telemetry_publisher/                    ← single-thing mqtt demo
    README.md
    app.py
    config.toml
  wifi_only/                              ← single-thing wifi-up + LED
    README.md
    app.py
    config.toml
```

### Why a separate `examples/` (not under `things/`)

* `python run.py deploy` (no args) defaults to the lone thing.  If examples lived in `things/`, every workspace would have 5+ things and the bare deploy gets ambiguous.
* `python run.py test` doesn't sweep examples (each example has its own `tests/` if any; the user's own things/ tests stay clean).
* Feels like reading material rather than working code.

### Deploy from examples

User can deploy any example with explicit path:

```bash
python run.py deploy examples/two_things/server --device-id board-a
python run.py deploy examples/two_things/sensor --device-id board-b
```

Or copy an example into `things/`:

```bash
python run.py new garage/heater --from examples/two_things/server
```

### Initial example content

Five examples, sourced or refreshed from existing library-level examples.  Each becomes a full `app.py` + `config.toml` pair using the workspace's deploy-time merge model.

| Example | Source | Purpose |
|---|---|---|
| `hello_world/` | new | trivial `print('hello')` for "is my deploy chain working?" |
| `two_things/server/` + `two_things/sensor/` | `libraries/http_server/examples/circuitpython_two_thing_*.py` | server + sensor LAN demo, real wifi, two boards |
| `periodic_get/` | `libraries/requests/examples/circuitpython_periodic_get.py` | poll a URL on a heartbeat |
| `telemetry_publisher/` | `libraries/mqtt/examples/circuitpython_telemetry.py` | periodic QoS 1 publish |
| `wifi_only/` | new (variant of `libraries/wifi/examples/quickstart.py` for real boards) | wifi up + LED on connect |

Library-level examples STAY where they are — they're the "I'm reading the library docs" entry.  Workspace `examples/` is the "I have a workspace, show me a complete project" entry.  Different audiences.

## Slices

Each slice ends with green preflight + task-checkpoint commit + push.

### Slice 1 — Recursive thing detection

* `chumicro_workspace.workspace.WorkspaceLayout.list_things` rewritten to walk recursively with the classifier above.  Returns sorted slash-form paths.
* `WorkspaceLayout.thing_dir(name)` already handles slashes natively (Path joins) — no change.
* `WorkspaceLayout.iter_things_with_classification()` new helper for `things` and `doctor` commands that need the namespace tree, not just the leaves.
* New tests: nested fixtures (single-level, two-level, three-level, namespace-with-supporting-files, namespace-with-empty-subdir-only).
* `_validate_thing_name` extended to handle slash/dotted paths — splits + validates each segment.

**Acceptance:** `python run.py things` on a fixture workspace with a 3-level layout lists every leaf in the right order; an empty subdirectory doesn't appear; `_template` is hidden; `_supporting` (no entry-point children) is hidden.

### Slice 2 — Deploy + boot-shim nesting

* `_cmd_deploy` accepts slash/dotted paths.  Bare-name lookup with disambiguation.
* `boot_shim.boot_shim_files` accepts dotted `thing_name`, emits one `__init__.py` per namespace level.
* `boot_shim.build_active_py` writes the dotted name unchanged (`THING_NAME = "upstairs.bedroom_sensor"`).
* `workspace_runtime.boot()` already handles dotted names (line 67: `"things." + thing_name + ".app"`).  Verify with a unit test that `thing_name = "a.b.c"` produces `"things.a.b.c.app"` correctly.
* `multi_thing_boot_source` extended for nested paths (each thing's own namespace tree gets its `__init__.py`s).

**Acceptance:** deploying `upstairs/bedroom_sensor` to a real Pi Pico W lands files at `/lib/things/upstairs/bedroom_sensor/app.py` plus the namespace inits, and `import things.upstairs.bedroom_sensor.app` resolves on-device.

### Slice 3 — `new` accepts paths + `--from`

* `_cmd_new` accepts slash/dotted paths.  Per-segment validation.
* `--from <example-path>` flag: copies from the named source instead of `things/_template/`.  Validates the source is a thing (has an entry point).
* Error messages refreshed for nested cases ("namespace `garage/` doesn't exist; pass `--mkdirs` to create it" or auto-create silently — pick one; recommend auto-create with a trace line).

**Acceptance:** `python run.py new garage/sensors/door_open` produces `things/garage/sensors/door_open/{app.py,config.toml,tests/test_app.py}` plus empty `things/garage/__init__.py` and `things/garage/sensors/__init__.py` namespace markers (host-side, for tooling consistency — separate from the on-device shim's `__init__.py`s).

### Slice 4 — `things` tree renderer + `rename` / `switch`

* `_cmd_things` tree view by default, `--flat` for plain.  Builds the tree from `iter_things_with_classification()`.
* `_cmd_rename` accepts slash paths on both sides.  When renaming a thing that's currently active on a device, prompts to update `/active.py` (or `--no-update-devices` skips).
* `_cmd_switch` accepts bare/slash/dotted, same disambiguation as deploy.

**Acceptance:** `python run.py things` on the example workspace renders the tree shown above; `--flat` produces the slash-list.

### Slice 5 — Examples folder shipped to template repo

* `chumicro-workspace`'s `_payloads/default_template/` (or wherever the canonical template content lives) gains an `examples/` directory.
* Five examples written: `hello_world/`, `two_things/{server,sensor}/`, `periodic_get/`, `telemetry_publisher/`, `wifi_only/`.  Each with `app.py`, `config.toml`, `README.md`.
* `examples/README.md` index lists each example with one-line summary.
* Workspace-template repo (separate Git repo) gets the same content via `chumicro-workspace update` — the canonical template lives in the package payload, the template repo gets refreshed from it.
* Update template repo's top-level `README.md` and `AGENTS.md` to mention `examples/`.

**Acceptance:** A fresh `python run.py init my-workspace` clone has an `examples/` folder.  `python run.py things` on that workspace shows only `things/_template` (not the examples).  `python run.py deploy examples/two_things/server` deploys cleanly.

### Slice 6 — Tests, docs, polish

* End-to-end test: scaffold a 3-level nested workspace in tmp_path, deploy a thing, assert the boot-shim file map has the right `__init__.py`s.
* Refresh `workbench/workspace/docs/guide.md` with nested-layout walkthrough.
* Refresh template-repo README + AGENTS.md.
* `plans/workstreams/project-workspace-research.md` may need an update — the original assumed flat.

**Acceptance:** preflight green at 94 % across all touched packages.  Template-repo README walks a user through "create a nested thing → deploy from an example → list the tree."

### Slice 7 — Drop the `switch` command

User triage 2026-04-27 confirmed: `switch` exists today only to support the multi-thing-staging path (re-point `/active.py` at a different thing already deployed under `/lib/things/<each>/`).  That path is itself on the chopping block (`plans/next-up.md` "Replace multi-thing staging with scoped diff-deploy").  With no backward-compat burden, the cleanest move is to drop `switch` outright now — slot the deletion alongside Phase 1's deploy refactor since deploy's positional args are already being reworked.

Concrete changes:

* Delete `_cmd_switch` from `chumicro_workspace/cli.py`.
* Delete the `switch` subparser registration.
* Delete `chumicro_workspace.boot_shim::multi_thing_boot_source` and `switch_source`.
* Delete `_cmd_switch` tests in `workbench/workspace/tests/test_cli.py`.
* Delete the `switch` row from `AGENTS.md` commands table in the template repo.
* Delete the `--boot-shim` and `--active` flags on `deploy` (they only made sense with multi-thing staging).
* Update `workbench/workspace/functional_tests/test_boot_shim_hardware.py` — keep the single-thing-boot-shim tests, drop the multi-thing-active-runs and switch-runs-new-active tests.

What stays: `thing_boot_source` (single-thing boot via `/active.py` indirection — still used).

**Acceptance:** `python run.py --help` no longer lists `switch`.  `deploy <a> <b> <c>` returns a helpful error ("multi-thing deploys are no longer supported; use `deploy <one>` per device").  Existing single-thing deploy + boot-shim chain unaffected.

This slice can land independently of Slices 1-6 if the user wants to ship it standalone; it's logically grouped here because deploy is being touched anyway.

## Test plan

* Unit tests under `workbench/workspace/tests/` — every classifier branch, every CLI dispatch path with nested names.
* Functional test under `workbench/workspace/functional_tests/test_nested_thing_hardware.py` — deploys a 2-level-nested thing to a real board and asserts the boot-shim chain runs `app.run()`.
* Cross-runtime parity: the on-device imports for `things.upstairs.bedroom_sensor.app` must work on CP + MP — verify via the existing test-harness pattern.

## Files to touch (mono-repo)

| File | Change |
|---|---|
| `workbench/workspace/src/chumicro_workspace/workspace.py` | `list_things` recursive; `iter_things_with_classification` new. |
| `workbench/workspace/src/chumicro_workspace/cli.py` | `_validate_thing_name` per-segment; `_cmd_deploy` / `_cmd_new` / `_cmd_things` / `_cmd_rename` / `_cmd_switch` all path-aware; `--from` flag; tree renderer. |
| `workbench/workspace/src/chumicro_workspace/boot_shim.py` | `THING_NAME` dotted; intermediate `__init__.py` emission. |
| `workbench/workspace/src/chumicro_workspace/_payloads/default_template/examples/` | New tree of 5 examples. |
| `workbench/workspace/src/chumicro_workspace/_payloads/default_template/things/_template/` | Possibly add a starter README.md note about nested layouts. |
| `workbench/workspace/src/chumicro_workspace/template_zones.py` | If it has any "every dir under things/ is a thing" assumption — verify and update. |
| `workbench/workspace/src/chumicro_workspace/_payloads/workspace_runtime/__init__.py` | Verify dotted `THING_NAME` round-trips through `__import__`.  Likely no change. |
| `workbench/workspace/tests/test_workspace.py` | New test cases for nested layouts. |
| `workbench/workspace/tests/test_cli.py` | New test cases for path-aware commands. |
| `workbench/workspace/tests/test_boot_shim.py` | New test cases for dotted `THING_NAME` + namespace inits. |
| `workbench/workspace/functional_tests/test_nested_thing_hardware.py` | New (Slice 6). |
| `workbench/workspace/docs/guide.md` | Nested-layout walkthrough. |

## Files to touch (template repo)

| File | Change |
|---|---|
| `examples/` | New directory, populated from `chumicro-workspace update` flow. |
| `README.md` | Add examples/ section, nested-things tip. |
| `AGENTS.md` | Update layout section + commands table. |
| `things/_template/` | No structural change; possibly refresh the per-thing README to mention nested layouts. |

## Notes for the executor

* **Auto-create namespace dirs in `new`.**  `python run.py new garage/sensors/door_open` should NOT require the user to pre-create `garage/` and `garage/sensors/` — auto-create with a trace line ("creating namespace garage/", "creating namespace garage/sensors/").
* **Namespace `__init__.py` placement.**  On-device: yes, every level needs `__init__.py` for the import to work.  Host-side `things/`: namespace `__init__.py` files are NOT strictly required since pytest doesn't import the tree as a package — but emit them anyway for tooling consistency (lets the user do `from things.upstairs.bedroom_sensor.app import run` in a host-side test).
* **Empty namespace dirs.**  If user creates `things/garage/` then deletes the only thing inside it, `things` should still show `garage/` as an empty namespace OR auto-classify it as supporting (hidden).  Recommendation: hidden — avoids cluttering the tree with empty branches.
* **`examples/` deploy without device-id.**  When the user deploys an example without a `--device-id`, fall through to the existing single-default-device logic.  Examples don't get pinned to specific devices; they're meant to be run on whatever's at hand.
