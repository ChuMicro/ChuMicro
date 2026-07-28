# Decision 0019: Branching model — single branch with tags

Status: `accepted`
Date: `2026-04-06`
Summary: Single-branch model: `main` is the only long-lived branch; stable releases are git tags; experimental releases auto-fire on VERSION bump; release branches only for older-stable hotfixes.
Related: none

## Context

The repo initially used a two-branch model (`develop` + `main`) where `main` was the stable release branch and `develop` was the integration branch (Decision 0019 v1). This created problems:

1. Auto-syncing `main` with `develop` pushed all library code to `main`, even for libraries that hadn't been promoted — so `main` didn't actually reflect stable releases.
2. Selectively merging library code to `main` is impractical in a mono-repo: the commit graph diverges on library paths, and future merges produce conflicts.
3. The stable release artifact (PyPI package, bundle repo, git tag) already exists independently of any branch. No consumer tool looks at a git branch.

## Decision

### Single-branch model

- **`main`** is the only branch. All PRs target `main`. CI runs on every PR and push to `main`.
- **Stable releases are tag-based.** The `promote.yml` workflow triggers `release.yml` with `channel=stable` for named libraries. This creates stable git tags (`timing-v0.2.0`), publishes to stable PyPI, and updates the stable bundle repo. The tag points to the exact commit that was promoted.
- **Experimental releases are automatic.** When a VERSION file changes on push to `main`, `release.yml` fires with `channel=experimental`, creating `-experimental` tags and publishing to the experimental PyPI package and bundle repo.
- **"What code is stable?"** → `git checkout timing-v0.2.0`. The tag is the artifact.

### Release branches (when needed)

For hotfixes against an older stable version (e.g., `main` has breaking changes in progress but `timing-v0.2.0` needs a patch):

1. Branch from the stable tag: `git checkout -b release/timing-v0.2.x timing-v0.2.0`
2. Fix the bug, bump VERSION to `0.2.1`.
3. Run `release.yml` manually on that ref with `channel=stable`.
4. Cherry-pick the fix back to `main`.

Release branches are created only when needed and deleted after the patch is released. They are not long-lived.

### Experimental and stable release channels

Channels are differentiated by **package name**, not version number or branch:

| Channel | PyPI package | Bundle repo | Git tag |
|---|---|---|---|
| Experimental | `chumicro-timing-experimental` | `ChuMicro-Bundle-Experimental` | `timing-v0.2.0-experimental` |
| Stable | `chumicro-timing` | `ChuMicro-Bundle` | `timing-v0.2.0` |

On-device import paths are always the base name (`chumicro_timing`). Channel separation is by repo and package name, not by directory name (Decision 0018).

**Dependency model:** experimental packages depend on experimental releases, stable on stable. Dependencies reference the same bundle repo as the package being installed.  Import paths are always the base name (`chumicro_timing`) regardless of channel.

### CI trigger changes

- `ci.yml` triggers on push to `main` and on all PRs.
- `release.yml` triggers on push to `main` with `libraries/*/VERSION` changes (experimental auto-release). Also accepts `workflow_dispatch` with `channel` and `libraries` inputs for stable releases and manual re-runs.
- `promote.yml` is a `workflow_dispatch` that builds and publishes the stable package from the experimental source archive, publishes to the stable bundle repo, and deploys stable docs inline (with a retry loop to handle concurrent gh-pages pushes).
- `docs-deploy.yml` triggers on push to `main` (experimental docs) and accepts `workflow_dispatch` for ad-hoc deploys. Stable docs are deployed by `promote.yml` directly, not via `docs-deploy.yml`, to avoid silent cancellation from the shared concurrency group.

### Manual steps for migration

- Set `main` as the default branch in GitHub repo settings.
- Delete the `develop` branch.
- Branch protection on `main` stays off: maintainer and agent work commits directly to `main` (the flow AGENTS.md documents), and an approval requirement would block exactly that path.  Contributor pull requests get CI plus maintainer review instead.  (The originally drafted step here, "require status checks + 1 approval", was never applied; this line was corrected 2026-07-28 to record the practice actually decided.)

## Consequences

- One branch eliminates all sync complexity — no `sync-main.yml`, no divergence risk, no GITHUB_TOKEN push-event suppression dependency.
- Stable releases are deliberate and selective: `promote.yml` with library names.
- Libraries stabilize independently. Promoting `timing` does not release `runner`.
- The "stable code" for any library is a tag, not a branch — unambiguous and immutable.
- Hotfixes use short-lived release branches from stable tags — standard Git workflow.
- Contributors have the simplest possible path: fork → PR to `main` → CI → merge.
