# Decision 0019: Branching model — develop → main

Status: `accepted`
Date: `2026-04-05`

## Context

The repo initially used `main` as both the integration branch and the release branch. As the project prepares for community contributions, this creates two problems:

1. Every merge to `main` is a potential release trigger. Contributors must be careful not to bump VERSION prematurely.
2. There is no staging area where changes can be tested together before being promoted to a stable release.

## Decision

### Two-branch model

- **`develop`** is the default branch and the target for all PRs. CI runs full checks (lint, all tests, verify-examples, build, version-check, API breakage detection, AI review) on every PR to `develop`.
- **`main`** is the stable release branch. It is kept **automatically in sync** with `develop` — every push to `develop` fast-forwards `main` via `sync-main.yml`. This means non-library work (scripts, plans, support, CI workflows, docs) is always current on both branches.
- **Stable releases are selective.** The `promote.yml` workflow dispatch accepts a comma-separated list of library names and triggers `release.yml` on `main` for only those libraries. Libraries stabilize at different rates; promoting one library does not force-release others.
- Running `promote.yml` with no libraries performs a sync-only run that also deploys stable docs.

### PR targets

All contributor PRs target `develop`. Direct pushes to `main` are blocked via branch protection (with a bypass for the GitHub Actions bot, which performs the auto-sync).

### Experimental and stable release channels

Both `develop` and `main` are full release branches — version bumps happen on `develop` and carry into `main` unchanged.

The channels are differentiated by **package name**, not version number:

| Channel | PyPI package | mip package | Bundle repo | Git tag |
|---|---|---|---|---|
| Experimental (develop) | `chumicro-timing-experimental` | `chumicro_timing` | `ChuMicro-Bundle-Experimental` | `timing-v0.2.0-experimental` |
| Stable (main) | `chumicro-timing` | `chumicro_timing` | `ChuMicro-Bundle` | `timing-v0.2.0` |

On-device import paths are always the base name (`chumicro_timing`). Both bundle repos use the same directory names (no `_experimental` suffix) — channel separation is by repo, not by directory name (Decision 0018). Users switch channels by reinstalling from the other package — they cannot have both installed simultaneously.

**Dependency model:** experimental packages depend on **stable** (production) releases by default. Installing one experimental library does not cascade into pulling experimental versions of its transitive dependencies. This means a user can run stable `chumicro-timing` alongside experimental `chumicro-mqtt` without conflict. When coordinated experimental changes across libraries are needed, the developer explicitly overrides specific dependencies in that library's build.

Experimental GitHub Releases are marked as pre-releases. Bundle releases use date-based tags with the channel suffix (e.g., `20260405-experimental`).

### CI trigger changes

- `sync-main.yml` triggers on push to `develop` and fast-forwards `main`. Uses `GITHUB_TOKEN` (push-event suppression prevents downstream workflow triggers — this is intentional).
- `ci.yml` triggers on push to `develop` and on all PRs. Does not trigger on `main` push (redundant since main = develop).
- `release.yml` triggers on push to `develop` with `libraries/*/VERSION` changes (experimental auto-release). Stable releases on `main` are triggered only via `workflow_dispatch` from `promote.yml`.
- `promote.yml` is a `workflow_dispatch` that syncs main, then triggers `release.yml` and `docs-deploy.yml` on `main` for the specified libraries.
- `docs-deploy.yml` triggers on push to `develop` (experimental docs) and via `workflow_dispatch` on `main` (stable docs, called by `promote.yml`).

### Manual steps required

- Set `develop` as the default branch in GitHub repo settings.
- Configure branch protection on both `develop` and `main`:
  - `develop`: require status checks (lint, test, build, version-check), require 1 approval.
  - `main`: allow GitHub Actions bot to bypass (for `sync-main.yml` auto-push). No required status checks needed (code already passed CI on `develop`).

## Consequences

- Contributors have a clear, low-friction path: fork → PR to `develop` → CI gates → merge.
- `main` never falls behind `develop` — auto-sync keeps non-library code (scripts, CI, plans, support) current at all times.
- Stable releases are deliberate and selective: someone must explicitly promote specific libraries via `promote.yml`. Libraries stabilize independently.
- No single maintainer bottleneck: any approved contributor can merge to `develop`; release promotion can be done by any maintainer.
- `check_version.py` default base ref is `origin/develop` (not `origin/main`).
- The `GITHUB_TOKEN` push-event suppression is load-bearing: `sync-main.yml`'s push to `main` must *not* trigger `release.yml`. The `workflow_dispatch` exception is also load-bearing: `promote.yml` relies on it to trigger `release.yml` and `docs-deploy.yml`.

