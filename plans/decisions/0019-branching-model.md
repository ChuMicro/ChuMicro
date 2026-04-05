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
- **`main`** is the stable release branch. Merges from `develop` to `main` are "release cuts" — they trigger `release.yml` which publishes to PyPI and creates tags/GitHub Releases for any library whose VERSION changed.
- The `develop` → `main` merge is done via a PR (for auditability) or via the `promote.yml` workflow dispatch. At least one approval is required initially.

### PR targets

All contributor PRs target `develop`. Direct pushes to `main` are blocked via branch protection.

### Pre-release publishing

Releases from `develop` are tagged with `-experimental` suffix (e.g., `timing-v0.2.0-experimental`) and marked as GitHub pre-releases. Releases from `main` are stable — no suffix, no pre-release flag. The bundle repo (`ChuMicro/chumicro-bundle`) only receives artifacts from stable `main` releases.

### CI trigger changes

- `ci.yml` triggers on push to `develop` and on all PRs (targeting any branch).
- `release.yml` triggers on push to `develop` or `main` with `libraries/*/VERSION` changes. Develop releases get `-experimental` tags; main releases are stable and also publish to the bundle repo.
- `promote.yml` is a workflow_dispatch that opens a PR from `develop` → `main`.

### Manual steps required

- Set `develop` as the default branch in GitHub repo settings.
- Configure branch protection on both `develop` and `main`:
  - `develop`: require status checks (lint, test, build, version-check), require 1 approval.
  - `main`: require status checks, require 1 approval, restrict who can push (maintainers only).

## Consequences

- Contributors have a clear, low-friction path: fork → PR to `develop` → CI gates → merge.
- Stable releases are deliberate: someone must explicitly promote from `develop` to `main`.
- No single maintainer bottleneck: any approved contributor can merge to `develop`; release cuts can be automated or done by any maintainer.
- Existing `release.yml` needs only a branch trigger change (already targets `main`).
- `check_version.py` default base ref changes from `origin/main` to `origin/develop`.

