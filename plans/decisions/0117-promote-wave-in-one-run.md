# Decision 0117: A promotion wave is one workflow run

Status: `accepted`
Date: `2026-08-07`
Summary: `promote.yml` takes a tag list and promotes a whole wave in one run: a matrix publish, then one batched bundle, channel, docs and manifest pass. `scripts/promote_wave.py` retires.
Related: Decision [0023](0023-standalone-promote-workflow.md) (standalone promote from `main` off the source archive, unchanged here), Decision [0018](0018-distribution-bundle-repo.md) (bundle repo), Decision [0032](0032-workbench-host-tools.md) (workbench skips the bundle), Decision [0112](0112-release-identity-and-mpy-abi.md) (release manifest)

## Context

`promote.yml` was written to promote one package.  A wave of N packages therefore meant N dispatches, and bulk-dispatching them hits a GitHub Actions trap: a concurrency group keeps one running plus at most one pending run, and queuing a third silently cancels the pending one with no failure signal.  `scripts/promote_wave.py` exists to dodge that by dispatching strictly one at a time and watching each to completion.

The cost was never measured until the 2026-08-07 wave.  The same seventeen packages went through both channels that day, on the same runners:

| Workflow | Shape | Wall |
|---|---|---|
| `release.yml` (experimental) | one run, 23 jobs | 9.2 min |
| `promote.yml` (stable) | seventeen runs | 92.3 min |

A tenfold gap for identical work, and `release.yml` already performs every shared-state write that supposedly forces serialization: the bundle push, the libraries channel index, the manifest, the mip validation.  It fans the publishes out as a matrix and does each shared write once, at the end.

Two specific wastes account for the gap.  The preflight gate re-runs per promotion, and every tag in a wave from a single push points at the same commit, so seventeen runs gated one tree seventeen times (about 45 of the 92 minutes).  And each promotion pushes its own bundle snapshot, so a wave leaves seventeen bundle tags whose intermediate manifests pin dep tags naming partial states, when the wave has exactly one coherent snapshot.

## Decision

`promote.yml` accepts `experimental_tags`, a comma-separated list, and promotes the whole wave in one run.  Its job graph mirrors `release.yml`:

1. **`validate`** runs `scripts/promote_matrix.py` over every tag and emits `matrix`, `library_matrix`, `docs_matrix` and `gate_commits`, the same way `release_matrix.py` feeds `release.yml`.  Per-tag validation stays in `promote_validate.py`; the matrix script loops it.
2. **`preflight-gate`** is a matrix over the *distinct commits* the tags point at, not over the tags.  A wave cut from one push gates once.  A wave mixing commits gates once per commit, degrading to the old cost only when the tags genuinely disagree.  Gating the experimental tag's tree rather than `main` is unchanged from Decision 0023.
3. **`release`** is a matrix over packages with `fail-fast: false`.  Each package is its own PyPI project with its own trusted publisher and its own git tag, so nothing is shared between legs.
4. **`bundle`, `channel`, `docs`, `manifest`** are each a single job taking the whole matrix: one bundle clone staging every library, one `finalize-tag`, one push, one release; one channel index write; one `docs-deploy --channel stable --libraries a,b,c` producing one `gh-pages` push.
5. **`validate-mip`** is one job over `library_matrix`, as in `release.yml`.

The `release` concurrency group stays.  It serializes promotions against experimental releases, which is still required, and with one run per wave there is nothing left to queue behind, so the cancel trap stops being reachable rather than being managed.

A tag whose stable tag already exists drops out of the matrix, with `--include-tagged` as the escape hatch.  This replaces the `resume` input: re-dispatching a failed wave's tag list is the resume path, and already-promoted packages fall out on their own.

Dependency ordering is dropped, because batching removes the requirement rather than relocating it.  `promote_wave.py` ordered its dispatches because each run pushed its own bundle snapshot, so a package promoted before its dependency would pin a snapshot that did not yet contain it.  One batched snapshot stages every library independently and then `finalize-tag` pins every manifest to that single tag, so there is no intermediate state for ordering to protect.  This is why `release.yml` has never needed it for its N-package bundle: `bundle_manager.stage_matrix` walks the matrix in the order given and does not reorder.

Ordering is likewise not load-bearing for stable PyPI, where intra-workspace deps are unpinned or carry already-satisfied floors, and PyPI does not resolve dependencies at upload.

**Rejected: per-package concurrency groups.**  This is the obvious way to parallelize and it is wrong.  It would let the bundle push, the channel index write and the `gh-pages` deploy race each other on shared state.  The fix for those jobs is batching, not concurrency.

**Rejected: keeping the serial loop and only gating once.**  It recovers the preflight time but still leaves N bundle snapshots per wave, only the last of which describes the wave.

**Rejected: dropping the per-promotion gate.**  Stable PyPI is immutable, so the tree that ships must be provably green.  The gate is re-run per distinct commit, not removed.

## Consequences

`scripts/promote_wave.py` is deleted along with its tests.  Its entire purpose was dodging a trap that a single run does not expose.

A wave produces one bundle tag, one channel index write and one `gh-pages` push instead of N of each, so the bundle history gains one coherent snapshot per wave rather than N partial ones.

Partial failure changes shape.  Under the serial loop a failure stopped the wave, leaving the packages before it published.  Now `fail-fast: false` means every leg attempts, and the batched jobs run only when all publishes succeeded, so a partial wave publishes to PyPI but does not push a bundle describing a state that never fully shipped.  Recovery is re-dispatching the same tag list once the failure is fixed.

The measured wave shape goes from about 92 minutes to about 10.  The remaining floor is the single preflight, which is core-bound on a 2-vCPU runner (Decision [0048](0048-preflight-phase-level-parallel.md) covers its internal parallelism) and is the same floor `release.yml` already lives with.
