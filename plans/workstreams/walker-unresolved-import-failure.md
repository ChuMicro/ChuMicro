# Workstream: Deploy walker fails on unresolved imports

Status: **proposed.** Surfaced 2026-05-12 while cleaning up downstream eager imports of `chumicro_sockets` / `chumicro_timing` / `chumicro_config`. Decision 0062's bench-validation table reported "12 files, zero `chumicro_sockets/*`" for the post-skip deploy, but that result came partly from the walker silently dropping unresolvable imports — not from the per-library code actually being free of those imports. With the cleanup landing in a sibling session, the silent-skip behavior becomes the only remaining failure mode that ships an `ImportError` at boot.

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

Decision 0062's `## Bench validation` section currently reports the post-skip 12-file count as if `chumicro_sockets` was excluded because the skip mechanism worked. After this workstream lands, that's true on the merits — but until then, the table also reflects the silent-skip. Two follow-ups:

1. Once the sibling cleanup (downstream libs stop importing `chumicro_sockets` / `chumicro_timing` / `chumicro_config` at module top) ships, rerun the bench. The 12-file count should hold for the right reason. Update the table.
2. Add a `## Limits as originally bench-validated` note acknowledging the silent-skip dependency at the time the ADR landed, with a pointer to this workstream as the corrective.

## Out of scope

- Walker-side `import` semantics beyond resolution (e.g. circular-import detection, conditional imports inside `try`/`except ImportError` blocks that already exist for runtime-fork branches). Leave the existing behavior alone.
- Per-runtime allowlists. The allowlist is a union — a name on it is fine on all three runtimes. If a name is platform-specific and missing from the wrong runtime at boot, that's a `__chumicro_runtimes__` marker job, not a walker job.

## Sizing

~50-80 LOC walker change + the allowlist constant + 4 new fixtures + ~6 new tests. Half a session of focused work; doable in one sitting once the design questions above are picked.
