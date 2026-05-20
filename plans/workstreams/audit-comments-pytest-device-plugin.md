# Workstream: `/audit-comments` — `pytest-device/plugin.py` degraded comments

Status: **proposed.**  Surfaced 2026-05-19 during the pytest-device audit under the trim-only comment pass; flagged for the rewrite-from-fresh-read path the audit-comments skill carries.

## Problem

Three stretches of prose in `workbench/pytest-device/src/chumicro_pytest_device/plugin.py` failed the cold-maintainer test under a trim-only audit and now need rewriting from a fresh read of the code, not further subtractive trim:

- **Per-file / per-library deploy-path inline blocks at ~1045-1067 and ~1115-1133** — longer than the code they wrap, mixing two deploy modes with RP2040 board facts and idempotency notes.
- **`_TransportCache.disconnect_all` docstring at ~988-1004** — 16 of 17 lines spent on the ESP32-S2 USB-CDC wedge incident.
- **`_IN_MEMORY_MODES` + `_should_soft_reset_before_stage` prose at ~1582-1635** — two homes for one concept.

## Resolution

Route through the `/audit-comments` skill, which is the judgment counterpart to the mechanized comment-lint subset.  Trim-only passes (the `/audit-library` comment dimension) cannot fix degraded comments by subtracting further; the rewrite path is the load-bearing one for this kind of rot.
