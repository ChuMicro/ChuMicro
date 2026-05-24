# Decision 0082: chumicro_test_harness ships as an infrastructure library

Status: `accepted`
Date: `2026-05-24`
Related: Decision [0016](0016-cross-runtime-unit-tests.md) (cross-runtime test runner that lives in this package), Decision [0058](0058-test-skips-must-be-loud.md) (`chumicro_test_harness.skip` primitive), Decision [0070](0070-host-only-test-marker.md) (host-only marker the harness honours), Decision [0078](0078-library-acquisition-is-host-local.md) (snapshot channel that ships `libraries/`), Decision [0042](0042-library-dependency-policy.md) (dep-declaration model the snapshot walker reads).

## Context

The cross-runtime test runner, the `raises`/`skip` primitives, and the wifi-bringup + runtime-config helpers needed by every networking library's `tests/` and `functional_tests/` need a home that is (a) cross-runtime (the runner deploys to MicroPython and CircuitPython), (b) reachable from every networking library's tests per AGENTS.md's test-import rule, and (c) shipped to a workspace-template consumer who pulls a networking library through `chumicro-workspace library add` without the mono-repo on disk.

`support/test_harness/` satisfies (a) and (b) today but not (c): the snapshot mechanism walks `libraries/` only, so support packages stay mono-repo-local and a downstream consumer cannot run a library's functional tests or examples.  Extending the snapshot to walk `support/` is real plumbing for a one-entry tree.  Promoting test_harness into `libraries/` reuses the existing snapshot path and aligns it with the same audit / VERSION / check-api cycle as every other publishable cross-runtime package.

A second concern: a package at `libraries/test_harness/` is not one an app developer picks up.  Listing it in the interactive `library browse` catalogue alongside MQTT and WiFi misleads the new-user picking flow.

## Decision

**`chumicro_test_harness` lives at `libraries/test_harness/` as an infrastructure library: it ships through the same snapshot channel as every other cross-runtime library, follows the same shape rules, and is hidden from the browsable catalogue unless asked for by name.**

- **Tree placement.** Source lives at `libraries/test_harness/src/chumicro_test_harness/`.  The `support/` tree is dissolved (no other entries justify it; future infrastructure packages land in `libraries/` with the same flag).
- **Infrastructure flag.** `pyproject.toml`'s `[tool.chumicro]` block carries `kind = "infrastructure"`.  The snapshot index records the kind; `chumicro-workspace library browse` and `library list` filter `kind == "infrastructure"` entries by default.  `list --all` shows them.  `library add <name>` (explicit ask) and `fetch_closure` (transitive resolve) ignore the flag — the flag controls *discovery*, not *fetchability*.
- **Network helpers.** A new `chumicro_test_harness.network` submodule holds the wifi-bringup + runtime-config helpers that today live duplicated in each network-using library's `examples/helpers.py`.  The submodule uses only runtime built-ins (CP `wifi`, MP `network`); it never imports another chumicro library.  Tests in any networking library may import `chumicro_test_harness.network`.
- **Test-import rule.** AGENTS.md's "Tests in any package may depend only on…" rule names the import name `chumicro_test_harness` (and its submodules), not the literal source-tree path.  The path is mechanism; the import name is the invariant.
- **Distribution-graph dep.** Networking libraries that ship example or functional-test infrastructure depending on the network helpers declare `chumicro-test-harness` in `[project].dependencies` so `fetch_closure` pulls it transitively (Decision 0078).  The dep is real, not a dev-only marker — the harness ships to the board alongside the library at deploy time.
- **VERSION + audit cycle.** `libraries/test_harness/VERSION` follows the same bump rules as peer libraries; `check-api`, `check-version`, `audit-library`, and `audit-embedded` apply.  `verify-examples` is a no-op (the package has no `examples/`).

## Rejected

- **Keep in `support/` and extend the snapshot to walk both trees.**  Plumbing (`_iter_libraries`, `LibraryCatalogEntry`, `fetch_closure`, the publish pipeline) for a one-entry tree the workspace already moved away from.  The path-as-signal benefit is reproduced by the `kind = "infrastructure"` flag at zero structural cost.
- **Promote to `workbench/`.**  `workbench/` is CPython-host-only by definition; `runner.py` deploys to MP/CP and runs there — host-only placement would lie about the deploy graph.
- **Publish `chumicro-test-harness` directly to PyPI without the snapshot channel.**  Adds external API-stability obligations on what is internally test infrastructure and duplicates a distribution path the snapshot already covers.  PyPI publication remains a one-flag follow-up if a downstream consumer asks for it.
- **Split the package — device-side runner in `libraries/`, host-side discovery in `workbench/`.**  Two packages for four files.  Runtime markers (`__chumicro_runtimes__ = ("cpython",)` on `discovery.py`) handle the host-only file; the deploy walker already honours them.

## Consequences

- `support/` is dissolved.  Future infrastructure packages (a cross-runtime debug helper, a board-bringup utility that ships to the device but is not for app use) land in `libraries/` with `kind = "infrastructure"`.
- AGENTS.md's "Testing" non-negotiable updates from `support/test_harness/` to `chumicro_test_harness` (and its submodules); the path drops out of the rule.
- Decisions 0016, 0058, 0070 carry inline `support/test_harness/...` paths.  When the move lands, those bodies edit in place to `libraries/test_harness/...` — no supersede markers, no banners; the decisions themselves are unchanged.
- `scripts/libraries_channel.py:_iter_libraries` does not change shape.  `[tool.chumicro] kind` is a new optional manifest field; absent = visible, current behaviour preserved.
- `chumicro-workspace library browse` / `list` filter by `kind`.  Snapshots without the field treat all entries as visible (forward-compatible).
- The five networking libraries' `examples/helpers.py` copies become candidates for retirement once `chumicro_test_harness.network` lands: examples either switch to the import or keep an inlined copy for per-platform pedagogy.  That call is per-library and rides the implementation workstream.
- `libraries/README.md` gains a brief "Internal infrastructure (not for app use)" subsection beneath the main inventory — separates the user-facing list from the package the snapshot ships alongside it.
