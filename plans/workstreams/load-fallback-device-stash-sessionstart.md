# Workstream: `_load_fallback_device` — stash sessionstart error to save the runtime re-load

Status: **proposed.**  Investigated 2026-05-19 during the pytest-device audit; ruled out as a `/audit-integration` candidate, parked as a sole-purpose cleanup.

## Problem

Initial audit claim: the fallback duplicated `DeviceConfigError` handling done in `pytest_sessionstart`.

Read pass shows the two paths are complementary:

- `pytest_sessionstart` silently swallows the error so collection finishes — the IDE play-button needs that on `__chumicro_runtimes__=("cpython",)`-filtered files.
- `_load_fallback_device` surfaces verbosely at runtest with setup instructions.

## Resolution

Minor cleanup only: stash the captured `DeviceConfigError` (or the loaded registry result) at sessionstart so the runtest path doesn't re-call `load_device_registry`.  Cosmetic — below the threshold for a sibling-cohesion pass.  File for anyone who wants to land it.
