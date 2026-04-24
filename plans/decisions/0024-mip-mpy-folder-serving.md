# Decision 0024: Folder-based .mpy serving for mip and circup

Status: `accepted`
Date: `2026-04-11`
Related: Decision 0018

## Context

Decision 0018 established that bundle repos host both `.py` source and `.mpy` bytecode.  The root `package.json` for each library lists `.py` files because mip has no version-negotiation mechanism for self-hosted `github:` packages — the `mpy=True/False` parameter only affects index-based installs from `micropython.org`.

CircuitPython and MicroPython both use `.mpy` bytecode format v6, but their mpy-cross compilers embed different magic bytes in the file header:

- CircuitPython mpy-cross: magic byte `C`
- MicroPython mpy-cross: magic byte `M`

Files compiled with the wrong runtime's mpy-cross are rejected at import time.  This means a single `.mpy` file cannot serve both runtimes — each requires its own compilation.

## Decision

### Dual-folder mpy layout

Each bundle repo contains two separate `.mpy` directories — one per runtime:

```
ChuMicro-Bundle/
├── chumicro_timing/              # default: .py source only
│   ├── package.json              # urls → .py files
│   ├── __init__.py
│   └── ticks.py
├── circuitpython-10.x-mpy/      # CircuitPython .mpy (magic 'C')
│   └── chumicro_timing/
│       ├── __init__.mpy
│       └── ticks.mpy
├── mpy6/                         # MicroPython .mpy (magic 'M')
│   └── chumicro_timing/
│       ├── package.json          # urls → mpy6/chumicro_timing/*.mpy
│       ├── __init__.mpy
│       └── ticks.mpy
```

- **`circuitpython-10.x-mpy/`** — follows Adafruit's naming convention where `10.x` reflects the CircuitPython version range.  No `package.json` needed — CircuitPython users install via circup, which uses zip bundles.
- **`mpy6/`** — follows MicroPython's mpy format version convention.  Contains `package.json` manifests for mip install.

### User experience

**CircuitPython (circup):**

```bash
circup bundle-add ChuMicro/ChuMicro-Bundle
circup install chumicro-timing
```

circup downloads the `10.x-mpy` zip, which contains `.mpy` files from `circuitpython-10.x-mpy/`.

**MicroPython (mip — default, .py source):**

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing
```

**MicroPython (mip — optimized, .mpy bytecode):**

```bash
mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing
```

### Build pipeline

`build_bundle` accepts separate `--cp-mpy-cross` and `--mp-mpy-cross` arguments:

- `--cp-mpy-cross`: Path to CircuitPython's mpy-cross binary.  Compiles into `circuitpython-10.x-mpy/`.
- `--mp-mpy-cross`: Path to MicroPython's mpy-cross binary.  Compiles into `mpy6/` and generates `package.json`.

Either argument can be omitted to skip that runtime's compilation.

### Dependency handling

Dependencies in `mpy6/` manifests reference `mpy6/` paths for intra-workspace deps so the entire dependency chain stays on `.mpy`:

```json
["github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing", "latest"]
```

### Naming conventions

- **`circuitpython-10.x-mpy/`** — mirrors Adafruit's zip naming convention (`bundle-10.x-mpy-DATE.zip`).  The `10.x` encodes the CircuitPython version range, not the mpy format version.  When CircuitPython 11.x ships (likely with mpy7), add `circuitpython-11.x-mpy/`.
- **`mpy6/`** — encodes the mpy bytecode format version.  When MicroPython adopts mpy7, add `mpy7/`.

### Alternatives considered

- **Single folder for both runtimes**: Magic byte incompatibility means a single `.mpy` file cannot serve both CircuitPython and MicroPython.  Rejected.
- **Branch-based** (`version="mpy6"`): Every release must update multiple branches atomically.  Branch drift risk.
- **Separate JSON** (`package-mpy6.json`): Users must type the full filename.  Leaks `.json` into dependency declarations.
- **Separate repo per mpy version**: Cross-repo dependency management.  Extremely high CI complexity.

### circup interaction

The circup zip builder scans `circuitpython-10.x-mpy/chumicro_*` directories for `.mpy` files when building the bytecode zip (named `bundle-10.x-mpy-DATE.zip`).  It ignores `mpy6/` entirely — that folder is for MicroPython mip only.

Root `chumicro_*` directories contain only `.py` source and are used for the `-py-` source zip.

The folder layout is designed for multi-version bundles during a future CP 11 / mpy v7 transition (add `circuitpython-11.x-mpy/` and/or `mpy7/` alongside the existing directories), but the build code is single-version today.  The implementation checklist for when a new mpy format actually ships lives under the "How should the bundle pipeline handle multiple mpy format versions?" entry in [`plans/open-questions.md`](../open-questions.md).

## Consequences

- CircuitPython users get `.mpy` files compiled with the correct mpy-cross via circup.
- MicroPython users who want `.mpy` bytecode have a documented opt-in mip path.
- The default `package.json` stays `.py`-based for universal compatibility.
- `build_bundle` compiles into separate folders using separate mpy-cross binaries.
- `build_circup_zips` pulls `.py` from root dirs and `.mpy` from `circuitpython-10.x-mpy/` dirs.
- Bundle README documents all install paths.
- Adding a future mpy format version requires adding one folder per runtime and regenerating manifests.
- Each runtime's `.mpy` files are self-contained in their own directory.
