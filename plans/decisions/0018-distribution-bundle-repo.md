# Decision 0018: Distribution bundle repository

Status: `accepted`
Date: `2026-04-04`
Updated: `2026-04-05`

## Context

Decision 0007 established that Chumicro publishes to three distribution channels (PyPI, mip, circup).  The ci-release workstream confirmed that the ChuMicro GitHub org hosts a circup-compatible repository and that release artifacts include both `.py` source and `.mpy` compiled bytecode.

What remained unspecified was the concrete repository architecture: where the built artifacts live, how `mip` and `circup` find them, and how the source repo relates to the distribution repo.

Key constraints:

- `.mpy` files are build artifacts tied to a specific bytecode version.  They do not belong in the source repo.
- `mip` installs from GitHub via `package.json` manifests that point to files in the same repo.
- `circup` installs from GitHub bundle repos via tagged releases containing versioned zips.
- Users should be able to install `.py` source (for debugging) or `.mpy` bytecode (for production).
- Not all boards support the same `.mpy` version — `.py` must always be available as a fallback.

## Decision

### 1. Separate repos per channel

Two distribution repos serve the stable and experimental channels:

- `ChuMicro/chumicro-bundle` — stable releases (from `main`)
- `ChuMicro/chumicro-bundle-experimental` — experimental releases (from `develop`)

Using separate repos keeps circup's `Bundle.latest_tag` working naturally per-repo — no prerelease tag management needed.  Within the experimental repo, library directories use an `_experimental` suffix (e.g. `chumicro_timing_experimental/`) so that users who register both bundles can choose between `circup install chumicro-timing` (stable) and `circup install chumicro-timing-experimental` (experimental).  This matches the PyPI naming convention where experimental packages are published as `chumicro-timing-experimental`.

Cross-package dependencies reference the stable repo so that installing one experimental library does not cascade into pulling experimental versions of all transitive dependencies.  Internal (relative) imports within a package work regardless of the directory suffix.

The source repo (`ChuMicro/ChuMicro`) contains only `.py` source, tests, and development infrastructure.

### 2. Bundle repo layout

Both repos share the same layout structure; the experimental repo uses `_experimental` suffixed directory names:

```
ChuMicro/chumicro-bundle/               # stable
├── README.md
├── chumicro_timing/
│   ├── package.json
│   ├── __init__.py / .mpy
│   └── ...

ChuMicro/chumicro-bundle-experimental/  # experimental
├── README.md
├── chumicro_timing_experimental/
│   ├── package.json
│   ├── __init__.py / .mpy
│   └── ...
```

Each library directory contains both `.py` and `.mpy` for every module (except testing modules which are `.py` only), plus a `package.json` for `mip`.

### 3. `mip` installation via `package.json`

Each library's `package.json` lists `.mpy` files as the default targets.  Users install the stable channel with:

```
mpremote mip install github:ChuMicro/chumicro-bundle/chumicro_runner
```

Or the experimental channel (note the `_experimental` suffix):

```
mpremote mip install github:ChuMicro/chumicro-bundle-experimental/chumicro_runner_experimental
```

On a network-capable board:

```python
import mip
mip.install("github:ChuMicro/chumicro-bundle/chumicro_runner")
# experimental: mip.install("github:ChuMicro/chumicro-bundle-experimental/chumicro_runner_experimental")
```

To install source instead of bytecode: `mip.install(..., mpy=False)`.

Dependencies between libraries (e.g., runner depends on timing) are declared in `package.json`'s `deps` list and resolved recursively by `mip`.  Dependencies always reference the stable repo so that installing one experimental library does not cascade into pulling experimental versions of all transitive dependencies.

### 4. `circup` installation via bundle

Users register the bundle once:

```
circup bundle-add ChuMicro/chumicro-bundle
```

Then install libraries normally:

```
circup install chumicro-runner
```

Users can register both bundles simultaneously.  The `_experimental` suffix disambiguates:

```
circup bundle-add ChuMicro/chumicro-bundle-experimental
circup install chumicro-runner-experimental
```

`circup` reads tagged GitHub Releases on the bundle repo.  The `Bundle` class (in `circup/bundle.py`) constructs download URLs from the repo name:

```
https://github.com/{repo}/releases/download/{tag}/{bundle_id}-{platform}-{tag}.zip
```

Where `bundle_id` is the repo name lowercased with underscores replaced by hyphens, and `{platform}` comes from circup's `PLATFORMS` dict in `circup/shared.py`.

For the stable repo: `bundle_id = "chumicro-bundle"`.
For the experimental repo: `bundle_id = "chumicro-bundle-experimental"`.

Each zip must contain a top-level directory named `{bundle_id}-{platform}-{tag}/` with a `lib/` subdirectory inside it.  circup's `lib_dir()` method constructs this path after extraction.  If the mpy zip for a device's platform is missing, circup falls back to the `.py` source zip.

Release automation produces one `.py` zip and one `.mpy` zip per repo:

- Stable: `chumicro-bundle-py-{tag}.zip`, `chumicro-bundle-10.x-mpy-{tag}.zip`
- Experimental: `chumicro-bundle-experimental-py-{tag}.zip`, `chumicro-bundle-experimental-10.x-mpy-{tag}.zip`

Only CircuitPython 10.x mpy bytecode is produced (mpy format v6).  CP 9.x users can install `.py` source.  Tags use date-based format (`YYYYMMDD`).

### 5. Bundle repo content policy

Each bundle repo is an automation-maintained artifact store.  Keep it minimal:

- **No examples.**  Examples live in the source repo and are linked from library READMEs and docs.  Neither `circup install` nor `mip install` puts examples on the device.
- **No per-library READMEs.**  Neither tool reads them.  A single root `README.md` with install commands and a link to the source repo is sufficient.
- **No GitHub Actions workflows.**  All automation lives in the source repo's `release.yml`.  The source repo pushes via `BUNDLE_TOKEN` (a PAT).  PAT-triggered pushes can fire workflows (unlike `GITHUB_TOKEN`), so a bundle-side `on: push` workflow would create a feedback loop.

### 6. Build pipeline

Release CI in the source repo triggers the bundle update:

1. A version tag on a library in `ChuMicro/ChuMicro` triggers the release workflow.
2. CI compiles `.py` → `.mpy` using `mpy-cross` (format v6, CP 10.x).
3. CI pushes the `.py` + `.mpy` files and updated `package.json` to the appropriate bundle repo (`chumicro-bundle` for `main`, `chumicro-bundle-experimental` for `develop`).
4. CI creates a tagged GitHub Release on the bundle repo with circup-format zips.
5. PyPI upload happens in parallel from the source repo (standard `python -m build` + trusted publishing).

### 7. PyPI is independent

CPython users install via `pip install chumicro-runner` from PyPI.  The bundle repos are not involved in PyPI publishing — that happens directly from the source repo's `pyproject.toml` and build artifacts.

## Consequences

- The source repo stays clean: no `.mpy` files, no distribution manifests.
- Stable and experimental channels have separate bundle repos.  Experimental directories use `_experimental` suffixed names so both bundles can be registered in circup simultaneously without name collisions.
- Both `mip` and `circup` install from the same bundle repo per channel, reducing maintenance.
- Users always have access to both `.py` (debugging, older runtimes) and `.mpy` (production).
- Both bundle repos need to exist.  Creating them and wiring up CI is part of the ci-release workstream.
- Platform targeting (Decision 0011) gates which libraries are included in each release.
- Example install commands in hardware examples should use `github:ChuMicro/chumicro-bundle/...` for MicroPython and `circup install ...` for CircuitPython.
- When circup adds new platform entries to `SUPPORTED_PLATFORMS`, the release workflow's mpy zip step needs updating to match.
