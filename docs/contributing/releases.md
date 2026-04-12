# Releases and Promotion

ChuMicro uses a two-channel release model: **experimental** (automatic) and **stable** (promoted by a maintainer).

## How it works

When your PR merges to `main` with a `VERSION` bump, an **experimental release** publishes automatically:

1. The package is built and published to PyPI as `chumicro-<name>-experimental`
2. Files are pushed to the [experimental bundle repo](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)
3. A git tag is created (e.g., `timing-v0.2.0-experimental`)
4. Experimental docs are deployed

No manual steps — it just happens on merge.

**Stable promotion** is separate. A maintainer runs `promote.yml` to republish an experimental release to the stable channel. The source archive ensures stable contains the exact code that was tested as experimental.

### Channels at a glance

| | Experimental | Stable |
|---|---|---|
| **PyPI package** | `chumicro-timing-experimental` | `chumicro-timing` |
| **Bundle repo** | `ChuMicro-Bundle-Experimental` | `ChuMicro-Bundle` |
| **Git tag** | `timing-v0.2.0-experimental` | `timing-v0.2.0` |
| **Import path** | `chumicro_timing` | `chumicro_timing` |

Import paths are identical across channels — switching from experimental to stable is a drop-in replacement. No code changes needed on the device.

### Installing from experimental

```bash
# CircuitPython (circup)
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro-timing

# MicroPython (mip)
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_timing

# CPython (pip)
pip install chumicro-timing-experimental
```

## Requesting a stable promotion

1. Open an issue using the [Stable Promotion Request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) template
2. Fill in the library name, experimental tag, and verification checklist
3. A maintainer reviews and runs `promote.yml`

What maintainers look for: preflight passes, ideally tested on hardware, no known regressions, docs are complete, and the API is intentional (breaking changes after stable require a major bump).

## Versioning

See [VERSION bumps](../../CONTRIBUTING.md#version-bumps) in the contributing guide for when and how to bump. Libraries version independently — bumping one has no effect on others.

## FAQ

**Q: Can I publish a stable release myself?**
Not yet. Open a [promotion request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) and a maintainer will handle it.

**Q: What if I bump VERSION but my PR fails CI?**
No release happens until the PR merges. Fix CI and push again.

**Q: What if I accidentally bump VERSION for a docs-only change?**
The release will fire on merge. It's not harmful (the package just gets a new version), but it's unnecessary. Only bump VERSION when source code under `src/` changes.

**Q: What about hotfixes to older stable versions?**
A maintainer creates a short-lived release branch from the stable tag, applies the fix, and runs `release.yml` manually. This is rare — most fixes go directly to `main`.
