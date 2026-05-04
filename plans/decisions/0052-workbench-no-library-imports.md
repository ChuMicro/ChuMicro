# Decision 0052: Workbench packages don't import library packages

Status: `accepted`
Date: `2026-05-04`
Related: Decision 0032 (workbench host tools), Decision 0049 (three runtimes — CPython is the testing seam, not a production target for workbench), Decision 0050 (library inclusion test).

## Context

Workbench packages are CPython-only host tools.  Library packages are cross-runtime device libraries that incidentally also run on CPython (so they can be tested with host-side pytest).  When a workbench package needs to read a config file, send msgpack, parse YAML, or talk to a device's runtime, it's tempting to `import chumicro_<libname>` and reuse the device-library implementation.

This is wrong.  Workbench tools are CPython-native and live their entire life on a developer's laptop — they should consume battle-tested CPython-native PyPI packages, not chumicro's cross-runtime pure-Python re-implementations.

## Decision

Workbench packages (anything under `workbench/<name>/`) **MUST NOT** `import chumicro_<libname>` from a `libraries/` package.

The replacement varies by need:

| Workbench need | Use this | Not this |
|----------------|----------|----------|
| msgpack encode / decode | `msgpack` (PyPI) | `chumicro_msgpack` |
| YAML read / write | `ruamel.yaml` (PyPI) | `chumicro_config` |
| TOML read | `tomllib` (stdlib) | `chumicro_config` |
| Serial port I/O | `pyserial` (PyPI) | n/a |
| HTTP client | `requests` (PyPI) | `chumicro_requests` |
| WebSocket client | `websockets` (PyPI) | `chumicro_websockets` |
| Tick-shaped scheduler | normal sync code | `chumicro_runner` |

**Templates and on-device payloads embedded as strings or bytes are fine.**  A workbench tool that ships a starter `code.py` to a device, or embeds a `_workspace_template/` tree of starter files, is shipping payload — that's data the tool writes onto a device, not code the tool itself imports.

## Rejected

**Allow library imports for "shared types" (config dataclasses, msgpack schemas, etc.).**  Rejected: the moment workbench imports a device-library type, the device library's evolution becomes coupled to host-tool evolution.  A library version bump (driven by a board-side concern) breaks the host tool; a host-tool version bump (driven by a CLI ergonomic concern) implicates the library.  Cross-coupling kills the invariant that libraries evolve at device-pace and workbench evolves at host-pace.

**Allow library imports if the library is pure-Python with no CP/MP-specific code.**  Rejected: even a "pure" library is being maintained for cross-runtime constraints (no f-strings of a certain shape, no `dataclasses.dataclass` defaults, no PEP-589 TypedDict on MP) that don't apply to workbench.  Workbench picks up cruft it doesn't need.

**Vendor a copy of the library inside the workbench package.**  Rejected: still ties workbench to library API shape, just with a slower drift signal.

## Consequences

- New workbench packages declare their `[project].dependencies` against PyPI directly — `pyserial`, `pyyaml`, `ruamel.yaml`, `msgpack`, `requests`, `rich`, etc.  No `chumicro-*` deps in workbench `pyproject.toml` files except other workbench packages (which is allowed).
- Workbench tests don't exercise device-library code paths.  A `chumicro_deploy` test that needs to encode msgpack uses the PyPI `msgpack` package; the library's `chumicro_msgpack` is exercised by its own tests under `libraries/msgpack/tests/`.
- The lint / preflight gate enforces the rule via import-graph check: any `from chumicro_<libname>` or `import chumicro_<libname>` in a `workbench/*/src/` file (other than `chumicro_<workbench-name>` self-imports and other workbench packages) fails.
- A workbench tool that needs the *contract* a library defines (e.g., a host-side validator that previews what a device will see when it parses a config) ships its own host-only implementation of the contract.  Decision 0036's "future `chumicro_config.host` workbench helpers" idea was the temptation that led to this rule; the helpers, if they ship, will live in their own workbench package, not inside a library.
- The boundary makes refactors safer.  When a library API changes for board reasons, workbench is unaffected.  When a workbench CLI rearranges its surface, libraries are unaffected.
