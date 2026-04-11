# Decision 0024: Folder-based .mpy serving for mip

Status: `accepted`
Date: `2026-04-11`
Related: Decision 0018

## Context

Decision 0018 established that bundle repos host both `.py` source and `.mpy` bytecode.  The root `package.json` for each library lists `.py` files because mip has no version-negotiation mechanism for self-hosted `github:` packages — the `mpy=True/False` parameter only affects index-based installs from `micropython.org`.

This means mip users always get `.py` source, even on boards that could run pre-compiled `.mpy` bytecode for faster startup and lower RAM usage.  CircuitPython users get `.mpy` through circup (which handles version matching via zip naming), but MicroPython users have no `.mpy` path.

## Decision

### Folder-based mpy manifests

Each bundle repo contains an `mpy6/` directory with per-library `package.json` manifests that point to the `.mpy` files in the root package directories:

```
ChuMicro-Bundle/
├── chumicro_timing/              # default: .py source
│   ├── package.json              # urls → .py files
│   ├── __init__.py
│   ├── __init__.mpy
│   └── ticks.py / .mpy
├── mpy6/                         # opt-in: .mpy v6 bytecode
│   └── chumicro_timing/
│       └── package.json          # urls → root .mpy files
```

The `mpy6/` manifests use full `github:` URLs pointing to the `.mpy` files in the root package directories.  No file duplication — only the `package.json` manifests live under `mpy6/`.

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

### circup interaction

The `mpy6/` directory does not affect circup.  The circup zip builder filters on `chumicro_*` directory names, so `mpy6/` is naturally excluded from circup zips.  circup continues to use the root `.mpy` files via its own version-matched zip naming convention.

## Consequences

- MicroPython users who want `.mpy` bytecode have a documented opt-in path.
- The default `package.json` stays `.py`-based for universal compatibility.
- `build_bundle` generates `mpy6/` manifests alongside the root manifests.
- Bundle README documents both install paths.
- Adding a future mpy format version requires adding one folder and regenerating manifests — no branch or repo management.

