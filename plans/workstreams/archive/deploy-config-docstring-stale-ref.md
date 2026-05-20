# Workstream: `chumicro_deploy.config` docstring references deleted symbol

Status: **resolved 2026-05-20** during `/audit-comments deploy` Pass 1 MEDIUM (commit `6917cdfe`).  The `_default_loader` docstring no longer cites the deleted symbol.  Surfaced 2026-05-19 during the repl audit, out of scope for that pass.

## Problem

`workbench/deploy/src/chumicro_deploy/config/__init__.py:59` cites `chumicro_repl.cli._device_from_args` as the precedent for runtime-kwarg gating.  That function was deleted in commit `681e9408` (cli slim, 2026-05-14), so the docstring now points at nothing.

## Resolution

Either rewrite the explanation inline so the rationale is self-contained, or point at a still-extant callsite that demonstrates the same gating pattern.
