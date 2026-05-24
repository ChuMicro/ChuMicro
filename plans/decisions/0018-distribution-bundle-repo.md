# Decision 0018: Distribution bundle repository

Status: `accepted`
Date: `2026-04-04`
Summary: Two bundle repos (`ChuMicro-Bundle` stable + `ChuMicro-Bundle-Experimental`) ship both `.py` and `.mpy` per library; `mip` and `circup` install from there; PyPI is independent.
Related: Decision 0007 (cross-platform deps), Decision 0023 (promote workflow), Decision 0024 (mip folder serving)

## Context

Decision 0007 established that ChuMicro publishes to three distribution channels (PyPI, mip, circup).  The ci-release workstream confirmed that the ChuMicro GitHub org hosts a circup-compatible repository and that release artifacts include both `.py` source and `.mpy` compiled bytecode.

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

- `ChuMicro/ChuMicro-Bundle` — stable releases (promoted via `promote.yml`)
- `ChuMicro/ChuMicro-Bundle-Experimental` — experimental releases (auto-published on VERSION bump)

Using separate repos keeps circup's `Bundle.latest_tag` working naturally per-repo — no prerelease tag management needed.  Both repos use identical directory names (e.g. `chumicro_timing/`) so that users can swap between channels without changing any import statements in their `code.py`.  Switching channels is explicit: change which bundle is registered with circup, or change the repo URL for mip.

The `-experimental` suffix only exists on PyPI (where two packages cannot share the same name).  On-device, the package name is always the base name (e.g. `chumicro_timing`), and swapping is a drop-in replacement.

The source repo (`ChuMicro/ChuMicro`) contains only `.py` source, tests, and development infrastructure.

### 2. Bundle repo layout

Both repos share the same layout; only the library versions differ:

```
ChuMicro/ChuMicro-Bundle/              # (or ChuMicro-Bundle-Experimental)
├── README.md
├── chumicro_timing/
│   ├── package.json
│   ├── __init__.py / .mpy
│   ├── ticks.py / .mpy
│   └── testing.py / .mpy
├── chumicro_runner/
│   └── ...
└── (GitHub Releases for circup)
```

Each library directory contains both `.py` and `.mpy` for every module, plus a `package.json` for `mip`.

### 3. `mip` installation via `package.json`

Each library's root `package.json` lists `.py` source files as the targets.  MicroPython compiles `.py` to bytecode on import, so source works on all mpy versions.  The `.mpy` bytecode files in the bundle are consumed by circup (which handles version matching via the zip naming convention); mip users opt into pre-compiled `.mpy` via the per-runtime folder layout described in [Decision 0024](0024-mip-mpy-folder-serving.md).  Users install the stable channel with:

```
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_runner
```

Or the experimental channel (same package name, different repo):

```
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_runner
```

On a network-capable board:

```python
import mip
mip.install("github:ChuMicro/ChuMicro-Bundle/chumicro_runner")
# experimental: mip.install("github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_runner")
```


Dependencies between libraries (e.g., runner depends on timing) are declared in `package.json`'s `deps` list and resolved recursively by `mip`.  Dependencies reference the same bundle repo as the package being installed — experimental deps pull from experimental, stable from stable.  This keeps all installed code on the same channel without requiring the user to change any import statements.

### 4. `circup` installation via bundle

Users register the bundle once:

```
circup bundle-add ChuMicro/ChuMicro-Bundle
```

Then install libraries normally:

```
circup install chumicro-runner
```

To switch to experimental, swap the bundle registration:

```
circup bundle-remove ChuMicro/ChuMicro-Bundle
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-runner
```

No import changes are needed — the on-device package name is always `chumicro_runner` regardless of channel.  Do not register both bundles simultaneously (circup may pick either version for a given package name).

`circup` reads tagged GitHub Releases on the bundle repo.  The `Bundle` class (in `circup/bundle.py`) constructs download URLs from the repo name:

```
https://github.com/{repo}/releases/download/{tag}/{bundle_id}-{platform}-{tag}.zip
```

Where `bundle_id` is the repo name lowercased with underscores replaced by hyphens, and `{platform}` comes from circup's `PLATFORMS` dict in `circup/shared.py`.

For the stable repo: `bundle_id = "ChuMicro-Bundle"`.
For the experimental repo: `bundle_id = "ChuMicro-Bundle-Experimental"`.

Each zip must contain a top-level directory named `{bundle_id}-{platform}-{tag}/` with a `lib/` subdirectory inside it.  circup's `lib_dir()` method constructs this path after extraction.  If the mpy zip for a device's platform is missing, circup falls back to the `.py` source zip.

Release automation produces one `.py` zip and one `.mpy` zip per repo:

- Stable: `ChuMicro-Bundle-py-{tag}.zip`, `ChuMicro-Bundle-10.x-mpy-{tag}.zip`
- Experimental: `ChuMicro-Bundle-Experimental-py-{tag}.zip`, `ChuMicro-Bundle-Experimental-10.x-mpy-{tag}.zip`

Only CircuitPython 10.x mpy bytecode is produced (mpy format v6).  CP 9.x users can install `.py` source.  Tags use date-based format (`YYYYMMDD`) for the first release of a day, with a semver-compatible sequence suffix (`.1`, `.2`, etc.) for subsequent releases on the same day.  This preserves release history across multiple pushes per day while remaining parseable by circup's `semver.VersionInfo.parse(tag, optional_minor_and_patch=True)`.

### 5. Bundle repo content policy

Each bundle repo is an automation-maintained artifact store.  Keep it minimal:

- **No examples.**  Examples live in the source repo and are linked from library READMEs and docs.  Neither `circup install` nor `mip install` puts examples on the device.
- **No per-library READMEs.**  Neither tool reads them.  A single root `README.md` with install commands and a link to the source repo is sufficient.
- **No GitHub Actions workflows.**  All automation lives in the source repo's `release.yml`.  The source repo pushes via `BUNDLE_TOKEN` (a PAT).  PAT-triggered pushes can fire workflows (unlike `GITHUB_TOKEN`), so a bundle-side `on: push` workflow would create a feedback loop.

### 6. Build pipeline

Release CI in the source repo triggers the bundle update:

1. A version tag on a library in `ChuMicro/ChuMicro` triggers the release workflow.
2. CI compiles `.py` → `.mpy` using `mpy-cross` (format v6, CP 10.x).
3. CI pushes the `.py` + `.mpy` files and updated `package.json` to the appropriate bundle repo (`ChuMicro-Bundle` for stable channel, `ChuMicro-Bundle-Experimental` for experimental channel).
4. CI creates a tagged GitHub Release on the bundle repo with circup-format zips.
5. PyPI upload happens in parallel from the source repo (standard `python -m build` + trusted publishing).

### 7. PyPI is independent

CPython users install via `pip install chumicro-runner` from PyPI.  The bundle repos are not involved in PyPI publishing — that happens directly from the source repo's `pyproject.toml` and build artifacts.

## Consequences

- The source repo stays clean: no `.mpy` files, no distribution manifests.
- Stable and experimental channels have separate bundle repos with identical directory names.  Users swap channels by changing their bundle registration — no import changes needed.  Do not register both bundles simultaneously.
- Both `mip` and `circup` install from the same bundle repo per channel, reducing maintenance.
- Users always have access to both `.py` (debugging, older runtimes) and `.mpy` (production).
- Both bundle repos need to exist.  Creating them and wiring up CI is part of the ci-release workstream.
- Platform targeting (Decision 0011) gates which libraries are included in each release.
- Example install commands in hardware examples should use `github:ChuMicro/ChuMicro-Bundle/...` for MicroPython and `circup install ...` for CircuitPython.
- When circup adds new platform entries to `SUPPORTED_PLATFORMS`, the release workflow's mpy zip step needs updating to match.
