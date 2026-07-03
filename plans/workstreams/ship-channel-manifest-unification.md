# Workstream: one source of truth for what ships in a package

Status: **RESOLVED by verified convergence** (2026-07-03).  The audit-wave fixes had already
unified all four channels on the shared `chumicro_deploy.runtime_marker` primitives
(`file_targets_runtime`, `is_test_support_module`) plus per-module `__chumicro_data_files__`
declarations — the planned resolver build was unnecessary.  Verified cell by cell:

- **Deploy walker**: runtime-filters, drops test-support, stages declared data files, and data
  files inherit their module's runtime marker — a CP deploy of the TLS demo stages neither
  `_ca_bundle.py` nor its 16 KB `.der` (live-verified), an MP deploy stages both.  This closes
  deploy-bundle-bloat **step 3** as already-shipped.
- **mip/circup bundles**: per-channel `target_runtime` (circup=CP, mpy=MP, source=DEVICE_RUNTIMES),
  `is_test_support_module` exclusion, manifest-derived content (S1) and declared data files with
  the same inheritance.
- **PyPI sdist/wheel**: keeps `testing.py` fakes **by design** — host application tests import
  them (the documented pattern); the exclusion policy applies to device channels only.  This
  narrows the original next-up bullet, which lumped wheels in.
- **pytest-device staging**: whole trees including fakes — correct, on-device tests import them.

Shipped 2026-07-03: two regression tests pinning the one previously-unpinned contract (data-file
runtime inheritance) on both the walker and the bundle sides, so the convergence can't silently
drift apart again.  Remaining related work lives in
[deploy-path-unification](deploy-path-unification.md) (the *transport* half, unchanged).

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
