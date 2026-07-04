# Workstream: Deploy walker fails on unresolved imports

Status: **shipped** (walker change). Surfaced 2026-05-12 while cleaning up downstream eager imports of `chumicro_sockets` / `chumicro_timing` / `chumicro_config`. Decision 0062's bench-validation table reported "12 files, zero `chumicro_sockets/*`" for the post-skip deploy, but that result came partly from the walker silently dropping unresolvable imports — not from the per-library code actually being free of those imports. With the cleanup landing in a sibling session, the silent-skip behavior becomes the only remaining failure mode that ships an `ImportError` at boot.

Status note: the walker now refuses unresolved imports at deploy time (see Validation history), and the `## Corrective ADR work` follow-ups below are now complete — the sibling import-cleanup shipped and Decision 0062's bench table was rerun and refreshed on current main.

Trigger: User-confirmed concern that "this should be a reported failure before it turns into a runtime crash."

## Problem

`workbench/deploy/src/chumicro_deploy/sources.py:220` (docstring) + `sources.py:367-378` (code path): when the walker encounters `from chumicro_foo import bar` in a file it's collecting, it calls `_resolve_module("chumicro_foo")`. If no entry under `search_paths` resolves the name, `_resolve_module` returns `None` and `_walk` silently continues past it. The file containing the unresolved import still ships to the device; the broken `import` fires at first boot as an `ImportError` from the device-side runtime, not from `chumicro-deploy`.

Two distinct failure modes share the silent-skip path today:

1. **Genuinely external import** — `import sys`, `import struct`, `from micropython import const`. These resolve against device-builtin modules at runtime, never against `search_paths`. The walker correctly skips them.
2. **Should-have-resolved import** — a chumicro library that's missing from `library_sources`, or a transitive dep the user forgot to register. These look identical to case (1) at AST level. The walker silently skips them; the device boot fails.

The walker has no way to tell (1) from (2) by inspection — both are just bare module names.

## What "good" looks like

A deploy that would `ImportError` at boot is refused at deploy time with a message that names the importing file, the unresolved module name, and the action (register in `library_sources` or supply a skip).

## Design surface (to resolve in the implementing session)

- **Allowlist of known-external module names.** `sys`, `struct`, `time`, `os`, `errno`, `collections`, `gc`, `io`, `random`, `binascii`, `hashlib`, `json`, `socket`, `ssl`, `select`, `asyncio`, plus the platform-only set (`microcontroller`, `wifi`, `socketpool`, `mdns`, `board`, `digitalio`, `analogio`, `bitbangio`, `displayio`, `terminalio`, `storage`, `nvm`, `neopixel_write`, `esp32`, `machine`, `network`, `micropython`, `usb_cdc`, `usocket`, `uselect`, `ustruct`, `utime`, `uerrno`, `uos`, `ujson`, `ubinascii`, `uhashlib`, `urandom`). Anything not on the allowlist that fails to resolve is a deploy-time error.
  - **Risk:** the allowlist is incomplete on day one. Mitigation: ship with the union of what every existing functional test imports, treat the allowlist as a living file in `workbench/deploy/src/chumicro_deploy/`, and provide a clear error format that names the unknown module so users can either fix their `library_sources` or open an issue to grow the allowlist.
- **Alternative considered: heuristic by namespace.** Treat any name matching `chumicro_*` as required-to-resolve; treat anything else as external. Simpler but loses any future chumicro-namespace runtime modules (e.g. a chumicro firmware feature flag module supplied by the runtime build). Allowlist is more accurate.
- **Where the error surfaces.** Same call site that today emits `skip_factories_warnings()` — `ImportGraphSource.__init__` is the natural place to fail-fast, identical pattern to the typo-guard for `__chumicro_skip_factories__` entries. Or: collect the violations during the walk and surface as a `RuntimeError` from a new `source.unresolved_imports()` method that the deploy entry point checks before writing files.
- **Test coverage.** Reproducer fixtures under `.scratch/` matching today's pattern:
  - `app_imports_unregistered.py` — entry point imports a chumicro module that isn't in `library_sources`. Expected: deploy refuses with named error.
  - `app_imports_builtin.py` — entry point uses `import struct`, `import sys`. Expected: deploy succeeds.
  - `app_imports_platform_only.py` — entry point uses `import wifi`, `import microcontroller`. Expected: deploy succeeds (platform allowlist).
  - `app_transitive_unregistered.py` — entry point imports a registered chumicro lib whose `client.py` reaches for an unregistered transitive. Expected: deploy refuses, error names the importing file.

## Corrective ADR work

Both follow-ups are complete; Decision 0062's `## Bench validation` section now reports counts that hold on the merits, not via the silent-skip.

1. Done (2026-07-04). The sibling cleanup — downstream libs stopped importing `chumicro_sockets` / `chumicro_timing` / `chumicro_config` at module top (the "drop eager … imports" commits) — shipped, and the bench was rerun on current main via `ImportGraphSource` over an `mqtt` deploy. With `target_runtime="circuitpython"` the default entrypoint ships 17 files and the `__chumicro_skip_factories__ = ("sockets_factory",)` entrypoint ships 7, a ten-file drop (`sockets_factory.py` + its `chumicro_sockets` / `chumicro_config` / `chumicro_msgpack` closure; `chumicro_timing` stays as the default tick source). The post-skip count is *smaller* than the original 12 because config + msgpack now leave the graph too — post-cleanup they are reachable only through the factory. The table was refreshed in place with these numbers (MicroPython: 19 default / 7 skip). Decision 0098's connect-family collapse left the `sockets_factory` module name intact, so the family matcher still discovers all five factory modules (mqtt / requests / websockets / ntp / http_server) — verified via `discover_factory_modules`, zero unmatched, zero over-match.
2. Done. Decision 0062's `### Limits as originally bench-validated` note records the silent-skip dependency at the time the ADR landed and points here as the corrective.

## Out of scope

- Walker-side `import` semantics beyond resolution (e.g. circular-import detection, conditional imports inside `try`/`except ImportError` blocks that already exist for runtime-fork branches). Leave the existing behavior alone.
- Per-runtime allowlists. The allowlist is a union — a name on it is fine on all three runtimes. If a name is platform-specific and missing from the wrong runtime at boot, that's a `__chumicro_runtimes__` marker job, not a walker job.

## Sizing

~50-80 LOC walker change + the allowlist constant + 4 new fixtures + ~6 new tests. Half a session of focused work; doable in one sitting once the design questions above are picked.

## Validation history

- 2026-06-12: Walker refusal shipped. New `chumicro_deploy/import_allowlist.py` holds `DEVICE_BUILTIN_MODULES` (union of MicroPython v1.26.0 + CircuitPython 10.2.0 built-ins, derived from the `.tools/` clones). `ImportGraphSource` now collects every required unresolved import not on the allowlist and raises `UnresolvedImportError` from `__init__` (collect-all-then-fail), naming each importing file + module; `unresolved_imports()` accessor added. New `DeployFailureKind.UNRESOLVED_IMPORT` + recovery plan + classifier pattern wire the refusal into the recovery taxonomy. `try/except ImportError`-guarded imports and speculative `from x import name` alias probes are exempt (guarded imports detected structurally, since `ast.walk` flattens the `Try` node). Silent-skip docstring rewritten to the new contract. Tests: `test_import_allowlist.py` (5) + 13 new `test_sources.py` cases + 2 `test_recovery.py` cases. Deploy suite 1005 green via `run.py test --libraries deploy --coverage-threshold 94` (TOTAL 95%); workspace suite 901 green (consumers unaffected); examples green. VERSION 0.31.2 -> 0.32.0 (new public API: exception, method, enum member, module). Follow-on (0062 bench rerun) closed 2026-07-04 — see next entry.
- 2026-07-04: Decision 0062 corrective bench rerun on current main. Reconstructed the mqtt deploy via `ImportGraphSource` (search paths over the reachable workspace libs, `target_runtime="circuitpython"`). Default entrypoint ships 17 files; the `("sockets_factory",)` family-skip entrypoint ships 7 — a ten-file drop now including `chumicro_config` / `chumicro_msgpack` (post-cleanup they reach the graph only through the factory). The walker's unresolved-import refusal guarantees the count can't hide a silent drop. Matcher re-verified: `discover_factory_modules` finds all five `sockets_factory` modules, family entry matches all five, zero unmatched / over-match — no walker change needed. Refreshed 0062's `## Bench validation` table + `### Limits as originally bench-validated` note in place.
