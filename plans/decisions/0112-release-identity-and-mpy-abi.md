# Decision 0112: Release identity manifest and mpy ABI evolution

Status: `accepted`
Date: `2026-07-18`
Summary: Every release emits a manifest tying its snapshot to each package version and the bundle/libraries tags; the bundle gains parallel mpy folders with a runtime-aware resolver at the next ABI bump.
Related: Decision [0111](0111-workspace-acquisition-coherence.md) (raised both as open questions), [0101](0101-ship-channel-selection-contract.md) (channel is a repo, runtime is a magic byte), [0018](0018-distribution-bundle-repo.md) (the device bundle `package.json`), [0024](0024-mip-mpy-folder-serving.md) (mip mpy folder serving), [0078](0078-library-acquisition-is-host-local.md) (the libraries `index.json`).

## Context

The first real end-to-end publish (Decision 0111) left two coherence questions open. A release stamps three identifiers with nothing tying them together: PyPI semver per package, the device bundle's date tag, and the libraries channel's timestamp tag. And the device bundle lays out exactly one MicroPython mpy format (`mpy6/`) and one CircuitPython format (`circuitpython-10.x-mpy/`), keyed by today's magic bytes, with no scheme for the next incompatible ABI.

## Decision

### A release emits a correlation manifest

Every release publishes a machine-readable manifest that records, for one snapshot, the full `{package: version}` set plus the concurrent device-bundle and libraries-channel snapshot tags. The manifest is a projection of data the release already computes (the release matrix, the two channel tags), so it adds a write, not a resolver. It gives both directions: a PyPI version resolves to the bundle and libraries snapshots it shipped in, and a snapshot tag resolves to the exact package versions it carries. Nothing about acquisition changes; channels stay independent (Decision 0101), and this is a lookup laid over them, not a version solver.

### The device bundle carries parallel mpy folders, chosen by a runtime-aware resolver

When an incompatible mpy format ships (a MicroPython `.mpy` version past 6, or a CircuitPython magic past the 10.x line), the bundle repo keeps a format folder per live ABI side by side in the one channel repo, and the circup/mip path selects the folder by reading the board's runtime version. This preserves Decision 0101's "channel is a repo" model (one repo per stable/experimental channel, not one per ABI) and keeps older boards installable while newer ones get current bytecode. Implementation is deferred until the next ABI bump actually lands; only two formats are live today, so `bundle_layout.py` stays as it is until then. This record fixes the approach so the next person does not rediscover it cold.

## Rejected

- **Unifying the snapshot tag across channels** to cut the identifier count: couples the two channel publishers to a shared tag and still does not tie PyPI semver in. The manifest correlates without that coupling.
- **Accepting uncorrelated identifiers** and documenting date proximity: cheap, but gives no traceability guarantee, and the correlating data already exists at release time.
- **A bundle repo per mpy ABI generation**: multiplies the repo, deploy-key, and publish surface and fragments the channel-is-a-repo model for a problem parallel folders solve inside one repo.
- **Pruning old mpy formats on a support-window schedule**: breaks installs on lagging firmware for a size saving the target boards do not need yet.

## Consequences

- The release pipeline grows a manifest-emit step; the format and its home (per-channel asset, central index, or both) are an implementation detail to settle when the step is built. Tracked in `plans/next-up.md`.
- No acquisition path changes today. The mpy-folder work is dormant until an ABI bump, at which point `bundle_layout.py`, the circup/mip resolver, and the bundle producer change together.
- The two Decision 0111 open questions are resolved and removed from `plans/open-questions.md`.
