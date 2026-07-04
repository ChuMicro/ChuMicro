# Decision 0101: One selection contract behind every ship-channel manifest

Status: `accepted`
Date: `2026-07-04`
Summary: A single AST-marker selection resolves each file's channel and runtime membership once; the four ship channels' manifests all project it, and a module's data files ship only where the module ships.
Related: Decision [0018](0018-distribution-bundle-repo.md) (the device bundle `package.json`), Decision [0078](0078-library-acquisition-is-host-local.md) (the host `index.json` catalog and snapshot model), Decision [0024](0024-mip-mpy-folder-serving.md) (mip mpy folder serving), Decision [0037](0037-runtime-file-marking.md) (runtime file marking), Decision [0044](0044-deploy-time-runtime-filtering.md) (deploy-time runtime filtering), Decision [0069](0069-test-support-module-marker.md) (test-support marker), Decision [0070](0070-host-only-test-marker.md) (host-only marker), [`plans/workstreams/ship-channel-manifest-unification.md`](../workstreams/ship-channel-manifest-unification.md).

## Context

The workspace ships through four channels — the deploy walker, the mip/circup device bundle (`package.json`), the sdist/wheel gate, and pytest-device staging — plus the host libraries channel's catalog (`index.json`). Decision 0018 fixes the device `package.json`, Decision 0078 fixes the host `index.json`, and Decisions 0037/0044/0069/0070 define the AST runtime markers. What no ADR recorded — and the `ship-channel-manifest-unification` workstream flagged as needing one (git `a00b9f75`, "contract pinned") — is the selection contract *underneath* all of them: what a manifest promises, who reads it, and the invariants that keep four channels from selecting files four different ways.

## Decision

- **One selection source, applied as per-channel policy.** Every channel resolves what a package contains through the same `chumicro_deploy.runtime_marker` reads: `file_targets_runtime` (`__chumicro_runtimes__`), `is_test_support_module` (`__chumicro_test_support__`), and per-module `__chumicro_data_files__`. A channel supplies only its target — circup takes CircuitPython, `mpy6/` takes MicroPython, the source snapshot takes every device runtime, the PyPI wheel keeps test-support — never its own file-selection logic. A file's channel and runtime membership is decided once.
- **A manifest is a projection, and it is authoritative.** The device `package.json` (Decision 0018) and the host `index.json` catalog (Decision 0078) each list exactly the files the shared selection admits for that channel. The manifest is content-authoritative: circup zips are built *from* the regenerated `package.json`, so a stale file left by a non-deleting overlay copy cannot ride in, and a package with no manifest is a hard error.
- **What a manifest promises.** Every listed entry resolves to a real staged file that belongs on that channel for that runtime. `package.json` deps point at the *same* channel repo (stable to stable, experimental to experimental). `index.json` carries a `tag` equal to the snapshot it was fetched at (else the tree and the manifest disagree) and a one-version-per-library snapshot that is internally consistent.
- **Data files inherit their module's runtime.** The invariant git `a00b9f75` was written to pin: a module's declared `__chumicro_data_files__` ship only where the module ships. The runtime filter drops a module before its data files are read, so a CircuitPython deploy stages neither an MP-only module nor its 16 KB CA bundle.
- **Channel is a repo, runtime is a magic byte.** Stable versus experimental is repo separation (`ChuMicro-Bundle(-Experimental)`, `ChuMicro-Libraries(-Experimental)`), not a tag or a package-name suffix. mpy bytecode splits by incompatible compiler: magic `M` to `mpy6/`, magic `C` to `circuitpython-10.x-mpy/`, with `scripts/bundle_layout.py` the one source both producer and consumer read. Unmarked files are default-safe and ship everywhere.

## Rejected

- **Four independent file-selection implementations.** The channel-by-marker matrix was patched cell-by-cell (four fixes in one day) until the shared `runtime_marker` reads became every channel's single source. Convergence on the markers, not a fifth reimplementation, is the contract.
- **A standalone `package_manifest(...)` resolver.** Planned to unify the channels, then found unnecessary: the markers already *are* the shared selection, so a resolver would only wrap them. Two data-file-inheritance regression tests pin the convergence instead.
- **One unified channel or manifest.** Kept split by payload: the device bundle stays deploy-flattened `.py` + `.mpy` + `package.json` for circup/mip; the libraries channel carries whole source trees plus `index.json` for host acquisition (Decision 0078). Same snapshot model, different payloads.

## Consequences

- A new ship channel supplies a target runtime and consumes the shared markers; it does not author selection. A new marker is read in one place and every channel inherits it.
- Which marker semantics are contractual (they gate what reaches a device) versus advisory is recorded here, rather than implied across four call sites.
- No board sees a file the selection did not admit for its runtime; test-support fakes stay off devices but remain in PyPI wheels by design.
- The manifest, not the staging directory's current contents, is the authority on channel membership; regenerate it and the derived circup zips follow.
