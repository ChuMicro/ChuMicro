# Releases and Promotion

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

Every library and tool releases on two channels: **experimental**, published automatically when a PR merges, and **stable**, which a maintainer promotes by hand.

<br clear="left">

## When to bump VERSION

Each package keeps its version in its own `VERSION` file (`libraries/<name>/VERSION`, `workbench/<name>/VERSION`) and follows [semantic versioning](https://semver.org/).  Packages version independently: bumping one has no effect on the others.

Bump once per PR when the PR changes what a user of the package gets:

| Change | Bump | Example |
|---|---|---|
| Bug fix, or any behavior change, including a changed error message or other string the package ships | patch | `0.8.4` to `0.8.5` |
| New feature | minor | `0.8.4` to `0.9.0` |
| Breaking change: a removed or renamed public function, class, or argument | minor while the package is below 1.0, major after | `0.8.4` to `0.9.0` |
| Tests, docs, examples, or a code change limited to comments and docstrings | none | |

The rules behind the table:

- **One bump per PR.**  A PR with five commits to `timing` bumps `timing` once.  CI grades the whole PR against `main`, so a second bump in a later commit is never needed.
- **`check-version` finds a missing bump.**  It fails when a package's `src/` or `pyproject.toml` changed and its `VERSION` did not.  It ignores a diff that only touches comments and docstrings.
- **`check-api` names the minimum level.**  It compares the public API against the last release tag and fails when a removal or rename comes with too small a bump.
- **No compatibility shims before 1.0.**  When you rename something, rename it everywhere in the same PR.  Leave no alias and no deprecation warning behind ([Decision 0092](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0092-no-backwards-compat-before-publication.md)).
- **`0.0.0` is exempt.**  A package whose `VERSION` reads `0.0.0` has never released, so `check-version` leaves it alone.

## What happens on merge

When your PR merges to `main` with a `VERSION` bump, an **experimental release** publishes automatically:

1. The package is built and published to PyPI as `chumicro-<name>-experimental`
2. Files are pushed to the [experimental bundle repo](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)
3. A git tag is created (for example `chumicro-timing-v0.8.5-experimental`)
4. Experimental docs are deployed

No one runs anything by hand for this.

**Stable promotion** is separate.  A maintainer runs `promote.yml` to republish an experimental release on the stable channel.  Stable is built from the experimental release's source archive, so it contains exactly the code that was tested as experimental.

### Channels at a glance

| | Experimental | Stable |
|---|---|---|
| **PyPI package** | `chumicro-timing-experimental` | `chumicro-timing` |
| **Bundle repo** | `ChuMicro-Bundle-Experimental` | `ChuMicro-Bundle` |
| **Git tag** | `chumicro-timing-v0.8.5-experimental` | `chumicro-timing-v0.8.5` |
| **Import path** | `chumicro_timing` | `chumicro_timing` |

Import paths are identical across channels, so switching from experimental to stable needs no code change on the board.

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

## Requesting a stable promotion

1. Open an issue using the [Stable Promotion Request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) template
2. Fill in the library name, experimental tag, and verification checklist
3. A maintainer reviews and runs `promote.yml`

What maintainers look for: preflight passes, ideally tested on hardware, no known regressions, docs are complete, and the API is intentional (breaking changes after 1.0 require a major bump).

## FAQ

**Q: Can I publish a stable release myself?**
No.  Open a [promotion request](https://github.com/ChuMicro/ChuMicro/issues/new?template=stable_promotion.yml) and a maintainer will handle it.

**Q: What if I bump VERSION but my PR fails CI?**
No release happens until the PR merges. Fix CI and push again.

**Q: What if I bump VERSION for a docs-only change by accident?**
The release fires on merge and publishes a new version with no code change.  It does no harm, and it wastes a version.  Bump only when the table above says to.

**Q: What about hotfixes to older stable versions?**
A maintainer cuts a short-lived `release/<library>-vX.Y.x` branch from the stable tag, applies the fix, runs `release.yml` by hand, and deletes the branch once the patch ships.  This is rare: most fixes go through a normal PR to `main`.

**Q: How do security fixes reach users?**
Like any fix, with urgency: the patch merges to `main`, publishes to experimental automatically, and the maintainer promotes it to stable at once instead of waiting for the next routine promotion. If you are reporting a vulnerability, go through [SECURITY.md](https://github.com/ChuMicro/ChuMicro/blob/main/SECURITY.md) privately; do not open a public promotion request for it.

## For maintainers

The rest of this page covers running the release workflows.  Contributors can stop here.

### Promoting several packages at once

Put every experimental tag in the `experimental_tags` input of `promote.yml`, comma-separated.  One workflow run promotes the whole wave:

```
chumicro-timing-v0.8.2-experimental,chumicro-mqtt-v0.28.2-experimental
```

The publishes run in parallel, and the bundle push, docs deploy, and libraries-channel write each happen once for the whole wave.  That produces one bundle snapshot describing the wave rather than one per package.

If a publish leg fails, the packages that succeeded keep their tags, and the bundle, docs, and channel jobs do not run.  Fix the failure and dispatch the same tag list again: packages already on stable drop out of the matrix on their own, so the re-run finishes only what is left.

### Promotion flags

`promote.yml` accepts two optional flags. Leave both off for a normal promotion.

**`allow_downgrade`** skips the check that the promoted version must be newer than the newest stable release.  Without it, promoting an older experimental tag fails validation instead of quietly rolling the stable bundle and docs back to the older version.  Set it only when a hotfix deliberately republishes an older version as stable.

**`include_tagged`** keeps packages whose stable tag already exists, instead of dropping them from the matrix.  Every downstream step is safe to repeat, so this is how you deliberately republish something already on stable.  A normal re-run does not need it.

### First release of a new package

The first release of a brand-new package fails at the PyPI publish step unless a maintainer prepares PyPI before the merge.  PyPI accepts a trusted-publisher upload only for a project that already exists or has a matching pending publisher, and the workflow cannot create projects on its own.  An account can also hold at most one pending publisher per (repository, workflow, environment) combination, so the slot is usually occupied.

Before merging the first `VERSION` bump of a new package, register a pending publisher on pypi.org for `chumicro-<name>-experimental`: owner `ChuMicro`, repository `ChuMicro`, workflow `release.yml`, environment `pypi`.  The first successful publish turns it into a normal per-project publisher.  The stable name gets the same treatment, with `promote.yml` as the workflow, when the package is first promoted.

If the release already fired and failed, bootstrap the project directly: build the dists locally, check them with `twine check`, upload with a scoped API token, attach a per-project trusted publisher on pypi.org, then re-run the release with `workflow_dispatch`.  The publish step's `skip-existing` makes the re-run safe, and the re-run also completes the bundle and libraries-channel jobs that the failed run skipped.

Reading the publish failure:

- **400 Bad Request**: the project does not exist and no pending publisher matched. Follow the bootstrap steps above.
- **403 Forbidden**: the project exists but its trusted publisher is missing or misconfigured. Fix it on the project's Publishing page.
- **429 (too many new projects)**: PyPI creates at most 4 new projects per rolling 24 hours, per user and per IP.  Retrying does not help.  Wait for the window to roll; the `Ratelimit-Policy` response header carries the exact reset time.

A failed publish leg also skips the bundle, libraries-channel, and manifest jobs for the whole run, including packages whose legs succeeded.  Their tags survive, so a `workflow_dispatch` re-run finishes their distribution without republishing anything.
