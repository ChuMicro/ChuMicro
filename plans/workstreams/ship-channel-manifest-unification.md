# Workstream: one source of truth for what ships in a package

Status: **open** (2026-07-03). Successor to the cell-by-cell fixes of the ship-channel matrix;
complements [deploy-path-unification](deploy-path-unification.md), which covers the *transport*
half ("one mechanism puts code on a board") — this covers the *selection* half ("one function
decides which files belong to a package for a target").

## Problem

Four channels each reimplement file selection: the deploy walker (`chumicro_deploy.sources`),
the mip/circup bundle builder (`scripts/bundle_manager.py`), the sdist/wheel gate
(`scripts/sdist_content.py`), and pytest-device staging.  Three markers modulate selection:
`__chumicro_data_files__`, `__chumicro_test_support__`, `__chumicro_runtimes__`.  Every
channel × marker cell is a separate implementation, and 2026-07-03 alone patched four cells
(C7 walker data-files, its bundle_manager sibling, circup stale-module manifests S1, sdist
data-file gate S7) while a fifth sits open (test-support exclusion from wheels/mip/circup —
the next-up packaging-policy bullet).  Every new channel or marker reopens every cell.

## Direction

One host-side resolver — `package_manifest(package_dir, *, target_runtime, include_test_support)`
returning the file set with per-file classification — consumed by all four channels.  The
existing per-channel behaviors become table-driven policy over one manifest instead of four
walkers.  The circup fix (S1) already established the pattern locally: the mip `package.json`
manifest is authoritative and other artifacts derive from it; this workstream promotes that from
"circup reads mip's manifest" to "everyone reads the same resolver."

## Scope notes

- The test-support packaging-policy bullet in next-up folds in here as the first consumer win.
- The deploy-bundle-bloat step 3 (CP deploys drop the MP-only CA `.der`) is a target-runtime
  policy cell — a second consumer win.
- Requires a decision record: which marker semantics are contractual (ADR) vs advisory.
- Not started; queued behind the runner API design pass.
