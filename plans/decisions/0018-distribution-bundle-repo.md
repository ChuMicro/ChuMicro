# Decision 0018: Distribution bundle repository

Status: `accepted`
Date: `2026-04-04`

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

### 1. Separate distribution repo

A new repo, `ChuMicro/chumicro-bundle`, serves as the distribution target for both `mip` and `circup`.  The source repo (`ChuMicro/ChuMicro`) contains only `.py` source, tests, and development infrastructure.

### 2. Bundle repo layout

```
ChuMicro/chumicro-bundle/
├── chumicro_timing/                      # stable channel
│   ├── package.json
│   ├── __init__.py / .mpy
│   ├── heartbeat.py / .mpy
│   ├── ticks.py / .mpy
│   └── testing.py                        # source-only (mock layer)
├── chumicro_timing_experimental/         # experimental channel
│   ├── package.json
│   ├── __init__.py / .mpy
│   ├── heartbeat.py / .mpy
│   ├── ticks.py / .mpy
│   └── testing.py
├── chumicro_runner/
│   ├── package.json
│   ├── __init__.py / .mpy
│   ├── core.py / .mpy
│   └── testing.py
├── chumicro_runner_experimental/
│   └── (same structure)
└── (GitHub Releases for circup)
```

Each library directory contains both `.py` and `.mpy` for every module (except testing modules which are `.py` only), plus a `package.json` for `mip`.  Experimental directories mirror their stable counterparts; the `package.json` inside installs files to the base import name (`chumicro_timing/`) on the device, sourcing them from the `_experimental/` directory in the repo.

### 3. `mip` installation via `package.json`

Each library's `package.json` lists `.mpy` files as the default targets.  Users install the stable channel with:

```
mpremote mip install github:ChuMicro/chumicro-bundle/chumicro_runner
```

Or the experimental channel:

```
mpremote mip install github:ChuMicro/chumicro-bundle/chumicro_runner_experimental
```

On a network-capable board:

```python
import mip
mip.install("github:ChuMicro/chumicro-bundle/chumicro_runner")
# or: mip.install("github:ChuMicro/chumicro-bundle/chumicro_runner_experimental")
```

To install source instead of bytecode: `mip.install(..., mpy=False)`.

Dependencies between libraries (e.g., runner depends on timing) are declared in `package.json`'s `deps` list and resolved recursively by `mip`.

### 4. `circup` installation via bundle

Users register the bundle once:

```
circup bundle-add ChuMicro/chumicro-bundle
```

Then install libraries normally:

```
circup install chumicro-runner
```

`circup` reads tagged GitHub Releases on the bundle repo.  Release automation produces versioned zip files in the format `circup` expects (containing `lib/` with `.mpy` and `.py` variants).

### 5. Build pipeline

Release CI in the source repo triggers the bundle update:

1. A version tag on a library in `ChuMicro/ChuMicro` triggers the release workflow.
2. CI compiles `.py` → `.mpy` using `mpy-cross` for each targeted bytecode version.
3. CI pushes the `.py` + `.mpy` files and updated `package.json` to `ChuMicro/chumicro-bundle`.
4. CI creates a tagged GitHub Release on the bundle repo with circup-format zip.
5. PyPI upload happens in parallel from the source repo (standard `python -m build` + `twine`).

### 6. PyPI is independent

CPython users install via `pip install chumicro-runner` from PyPI.  The bundle repo is not involved in PyPI publishing — that happens directly from the source repo's `pyproject.toml` and build artifacts.

## Consequences

- The source repo stays clean: no `.mpy` files, no distribution manifests.
- Both `mip` and `circup` install from the same bundle repo, reducing maintenance.
- Users always have access to both `.py` (debugging, older runtimes) and `.mpy` (production).
- The bundle repo does not exist yet.  Creating it and wiring up CI is part of the ci-release workstream.
- Platform targeting (Decision 0011) gates which libraries are included in each release.
- Example install commands in hardware examples should use `github:ChuMicro/chumicro-bundle/...` for MicroPython and `circup install ...` for CircuitPython once the bundle exists.

