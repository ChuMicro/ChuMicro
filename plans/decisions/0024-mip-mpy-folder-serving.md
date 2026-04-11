# Decision 0024: Folder-based .mpy serving for mip

Status: `accepted`
Date: `2026-04-11`
Related: Decision 0018

## Context

Decision 0018 established that bundle repos host both `.py` source and `.mpy` bytecode.  The root `package.json` for each library lists `.py` files because mip has no version-negotiation mechanism for self-hosted `github:` packages — the `mpy=True/False` parameter only affects index-based installs from `micropython.org`.

This means mip users always get `.py` source, even on boards that could run pre-compiled `.mpy` bytecode for faster startup and lower RAM usage.  CircuitPython users get `.mpy` through circup (which handles version matching via zip naming), but MicroPython users have no `.mpy` path.

## Decision

### Folder-based mpy layout

Each bundle repo contains an `mpy6/` directory with per-library subdirectories that hold both the compiled `.mpy` files and a `package.json` manifest:

```
ChuMicro-Bundle/
├── chumicro_timing/              # default: .py source only
│   ├── package.json              # urls → .py files
│   ├── __init__.py
│   └── ticks.py
├── mpy6/                         # opt-in: .mpy v6 bytecode
│   └── chumicro_timing/
│       ├── package.json          # urls → mpy6/chumicro_timing/*.mpy
│       ├── __init__.mpy
│       └── ticks.mpy
```

The `.mpy` files live exclusively under `mpy6/`, not in the root package directories.  This keeps each mpy format version self-contained so that a future `mpy7/` folder can be added without file collisions.

### User experience

```bash
# Default (safe, works everywhere):
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_timing

# Optimized (.mpy v6, for boards with mpy format v6):
mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing
```

### Dependency handling

Dependencies in `mpy6/` manifests reference `mpy6/` paths for intra-workspace deps so the entire dependency chain stays on `.mpy`:

```json
["github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing", "latest"]
```

### Version naming

The folder name encodes the mpy bytecode format version, not the runtime version.  `mpy6` corresponds to mpy format v6 (used by CircuitPython 10.x and MicroPython 1.24+).  When a new mpy format arrives, add an `mpy7/` folder.

### Alternatives considered

- **Branch-based** (`version="mpy6"`): Every release must update multiple branches atomically.  The `version` parameter rewrites all URLs in the manifest, requiring the entire file tree per branch.  Branch drift risk with automation.
- **Separate JSON** (`package-mpy6.json`): Dependencies leak the `.json` suffix into user-facing dep declarations.  Users must type the full filename.
- **Separate repo per mpy version**: Cross-repo dependency management.  Extremely high CI complexity.
- **.mpy files in root (previous approach)**: Co-locating `.mpy` and `.py` in the root package directory prevents supporting multiple mpy format versions simultaneously — file names collide and there is no way to distinguish which mpy format a given `.mpy` file targets.

### circup interaction

The circup zip builder scans `mpy6/chumicro_*` directories for `.mpy` files when building the bytecode zip.  Root `chumicro_*` directories contain only `.py` source.  The zip naming convention (`-10.x-mpy-`) tells circup which bytecode format the zip contains.

## Consequences

- MicroPython users who want `.mpy` bytecode have a documented opt-in path.
- The default `package.json` stays `.py`-based for universal compatibility.
- `build_bundle` compiles `.mpy` files into `mpy6/` and generates manifests pointing to those files.
- `build_circup_zips` pulls `.py` from root dirs and `.mpy` from `mpy6/` dirs.
- Bundle README documents both install paths.
- Adding a future mpy format version requires adding one folder and regenerating manifests — no branch or repo management.
- Each mpy format version is self-contained: files and manifest live together.
