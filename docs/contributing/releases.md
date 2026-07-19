# Releases and Promotion

<img src="../../support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

ChuMicro uses a two-channel release model: **experimental** (automatic) and **stable** (promoted by a maintainer).

<br clear="left">

## How it works

When your PR merges to `main` with a `VERSION` bump, an **experimental release** publishes automatically:

1. The package is built and published to PyPI as `chumicro-<name>-experimental`
2. Files are pushed to the [experimental bundle repo](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)
3. A git tag is created (e.g., `chumicro-timing-v0.2.0-experimental`)
4. Experimental docs are deployed

No manual steps: it just happens on merge.

**Stable promotion** is separate. A maintainer runs `promote.yml` to republish an experimental release to the stable channel. The source archive ensures stable contains the exact code that was tested as experimental.

### Channels at a glance

| | Experimental | Stable |
|---|---|---|
| **PyPI package** | `chumicro-timing-experimental` | `chumicro-timing` |
| **Bundle repo** | `ChuMicro-Bundle-Experimental` | `ChuMicro-Bundle` |
| **Git tag** | `chumicro-timing-v0.2.0-experimental` | `chumicro-timing-v0.2.0` |
| **Import path** | `chumicro_timing` | `chumicro_timing` |

Import paths are identical across channels: switching from experimental to stable is a drop-in replacement. No code changes needed on the device.

### Installing from experimental

```bash
# CircuitPython (circup)
circup bundle-add ChuMicro/ChuMicro-Bundle-Experimental
circup install chumicro_timing

# MicroPython (mip)
mpremote mip install github:ChuMicro/ChuMicro-Bundle-Experimental/chumicro_timing

# CPython (pip)
pip install chumicro-timing-experimental
```

## First release of a new package

The very first release of a brand-new package fails at the PyPI publish step unless a maintainer prepares PyPI ahead of the merge. PyPI only accepts a trusted-publisher upload for a project that already exists or has a matching pending publisher, and the workflow cannot create projects on its own. An account can also hold at most one pending publisher per (repository, workflow, environment) combination, so the slot is usually occupied.

Before merging the first `VERSION` bump of a new package, a maintainer should register a pending publisher on pypi.org for `chumicro-<name>-experimental`: owner `ChuMicro`, repository `ChuMicro`, workflow `release.yml`, environment `pypi`. The first successful publish converts it into a normal per-project publisher automatically. The stable name gets the same treatment with `promote.yml` as the workflow when the package is first promoted.

If the release already fired and failed, recover by bootstrapping the project directly: build the dists locally, verify with `twine check`, upload with a scoped API token, attach a per-project trusted publisher on pypi.org, then re-run the release with `workflow_dispatch`. The publish step's `skip-existing` makes the re-run safe, and the re-run also completes the bundle and libraries-channel jobs that the failed run skipped.

Reading the publish failure:

- **400 Bad Request**: the project does not exist and no pending publisher matched. Follow the bootstrap steps above.
- **403 Forbidden**: the project exists but its trusted publisher is missing or misconfigured. Fix it on the project's Publishing page.
- **429 (too many new projects)**: PyPI creates at most 4 new projects per rolling 24 hours, per user and per IP. Retrying does not help. Wait for the window to roll; the `Ratelimit-Policy` response header carries the exact reset time.

A failed publish leg also skips the bundle, libraries-channel, and manifest jobs for the whole run, including packages whose legs succeeded. Their tags survive, so a `workflow_dispatch` re-run finishes their distribution without republishing anything.

## Requesting a stable promotion

1. Open an issue using the [Stable Promotion Request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) template
2. Fill in the library name, experimental tag, and verification checklist
3. A maintainer reviews and runs `promote.yml`

What maintainers look for: preflight passes, ideally tested on hardware, no known regressions, docs are complete, and the API is intentional (breaking changes after stable require a major bump).

**Promoting several packages at once:** never dispatch `promote.yml` back to back. The shared `release` concurrency group holds one running plus at most one pending run and silently cancels the rest. Run the wave through the dispatcher instead, which orders packages so dependencies promote first and watches each run to completion:

```bash
python scripts/promote_wave.py <experimental-tag> [<experimental-tag> ...]
```

### Promotion flags

`promote.yml` accepts two optional flags. Leave both off for a normal promotion.

**`allow_downgrade`** skips the check that the promoted version must be newer than the newest stable release. Without it, promoting an older experimental tag fails validation instead of quietly rolling the stable bundle and docs back to the older version. Set it only when a hotfix intentionally republishes an older version as stable.

**`resume`** re-runs a promotion that failed after the stable tag was written. Validation then requires the stable tag to exist, and every downstream step is safe to repeat, so the whole pipeline runs again to completion. If a newer stable version shipped in the meantime, the resume fails the version check on purpose; add `allow_downgrade` to finish it deliberately.

## Versioning

See [VERSION bumps](../../CONTRIBUTING.md#version-bumps-and-publishing) in the contributing guide for when and how to bump. Libraries version independently: bumping one has no effect on others.

## FAQ

**Q: Can I publish a stable release myself?**
Not yet. Open a [promotion request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) and a maintainer will handle it.

**Q: What if I bump VERSION but my PR fails CI?**
No release happens until the PR merges. Fix CI and push again.

**Q: What if I accidentally bump VERSION for a docs-only change?**
The release will fire on merge. It's not harmful (the package just gets a new version), but it's unnecessary. Only bump VERSION when source code under `src/` changes.

**Q: What about hotfixes to older stable versions?**
A maintainer creates a short-lived release branch from the stable tag, applies the fix, and runs `release.yml` manually. This is rare: most fixes go directly to `main`.
