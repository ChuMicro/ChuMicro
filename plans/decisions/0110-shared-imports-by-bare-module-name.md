# Decision 0110: `shared/` modules import by bare module name

Status: `proposed`
Date: `2026-07-11`
Summary: A `shared/` module is imported by bare name (`from foo import bar`), never `shared.foo`; the deploy search path roots at `shared/`, so no `shared` package exists on host or device.
Related: Decision [0046](0046-shared-and-lazy-libraries.md) (§1 corrected in place by this record), Decision [0077](0077-one-device-staging-path.md) (workspace-agnostic staging is why the fix stays out of `chumicro_deploy`; the `CHU034` boundary), Decision [0092](0092-no-backwards-compat-before-publication.md) (no dual-form support carried before first publication)

## Context

Decision 0046 §1 introduced the workspace `shared/` folder and wrote that its modules are imported as `from shared.foo import bar`, resolved as an implicit namespace package. That claim never matched the code. `build_search_paths` (`workbench/workspace/src/chumicro_workspace/import_graph.py`) puts the `shared/` directory itself on the import-resolution search path, so `shared/foo.py` resolves as the top-level module `foo`, not as `shared.foo`. The bare form is the tested, deploy-verified contract (`workbench/workspace/tests/test_import_graph.py` stages `import shared_helper` to `/lib/shared_helper.py`); the package form resolves to no deployed file and is refused at deploy time with `UnresolvedImportError` (`workbench/deploy/src/chumicro_deploy/sources.py`).

## Decision

**A module under a workspace's `shared/` is imported by its bare module name.** `shared/foo.py` is `from foo import bar` or `import foo`, never `shared.foo`. The shared payload is rooted at the `shared/` directory, so its modules occupy the flat import namespace the device already searches (`/lib`); there is no `shared` package on host or device.

The rooting is the whole mechanism. `build_search_paths` appends `workspace.shared_dir` (the `shared/` directory) to the search path, alongside each `libraries/<name>/src/` and `packages/`. A file dropped in `shared/` is therefore importable by its stem exactly as a device `/lib` module is, with no package qualifier and no `__init__.py`.

Deploy already enforces this. A project that writes `from shared.foo import bar` produces an unresolved `shared.foo`, and `ImportGraphSource` refuses the deploy rather than shipping an import that would `ImportError` at first boot. When the unresolved import's top segment is `shared`, the workspace deploy CLI appends a one-line fix to the refusal so the mistake is self-correcting.

## Rejected

- **Support both `foo` and `shared.foo`.** Rooting the search path at both `shared/` and the workspace root would let the same file resolve under two names. On a device that is a double-import hazard: `foo` and `shared.foo` become two distinct module objects backed by one file, doubling that module's RAM on a 256 KB board and splitting any module-level state. One name per file is the invariant.
- **Package form only (`shared.foo`).** Making `shared.foo` resolve needs the *workspace root* on the search path, which leaks `projects/` and `packages/` into importland, or a `shared`-taxonomy special-case inside `chumicro_deploy`, which is workspace-agnostic by Decision 0077 (`CHU034` keeps deploy staging free of workspace concepts). It would further require a synthesized on-device `shared/__init__.py`, because MicroPython and CircuitPython do not reliably support PEP 420 namespace packages, and it still carries the double-import hazard against any bare-name import of the same file. Three costs, no gain over the bare form.
- **A dedicated lint for the package form.** Held in reserve. The deploy-time refusal plus its bare-name hint, and the `shared/README.md` note in the consumer template, catch the mistake at the moment it would ship. A `CHU0NN` rule stays available if the refusal proves too late in practice.

## Consequences

- Decision 0046 §1 is edited in place to describe the bare form and cross-links here; no supersede banner (the reasoning was wrong from the start, so this is an in-place correction per the decisions README).
- `WorkspaceLayout.shared_dir`'s docstring drops its `from shared.foo import bar` example for the bare form.
- The workspace deploy CLI appends a bare-name hint to `UnresolvedImportError` when an unresolved import's top segment is `shared`. The hint lives in the workspace layer; `chumicro_deploy` stays taxonomy-free.
- The consumer template puts `shared/` on the host test path and on pyright's `extraPaths`, so a project's bare shared imports resolve under `run.py test` and in the IDE the same way they do on device.
- Flat-namespace shadowing is the accepted cost: a `shared/` module and a device `/lib` module (or a scaffolded library) that share a stem collide, first match on the search path winning. Users avoid it by naming, the same discipline any flat import namespace demands.
