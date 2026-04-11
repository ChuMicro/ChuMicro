# Decision 0023: Standalone promote workflow with source archives

Status: `accepted`
Date: `2026-04-09`
Related: Decision 0018

## Context

The promote workflow (`promote.yml`) previously delegated to `release.yml` via `workflow_call`.  This caused two problems:

1. **Stale CI files.**  When a maintainer selected an experimental tag in the "Use workflow from" dropdown, GitHub ran the workflow YAML from that tag — including `release.yml` and all scripts (`bundle_manager.py`, `workspace.py`, etc.).  CI improvements merged to `main` after the experimental release were invisible to promotions.

2. **PyPI OIDC mismatch.**  PyPI's trusted publishing validates attestations against `job_workflow_ref` (the reusable workflow), but the Sigstore certificate carries the caller's identity (the top-level workflow).  These never match when one workflow calls another, forcing attestations to be disabled for stable promotions.

## Decision

### 1. `promote.yml` is standalone

Promote no longer calls `release.yml`.  It contains all build, publish, bundle, and docs steps inline.  This gives single-page visibility for the entire promotion and eliminates the OIDC identity mismatch — `promote.yml` is the direct publisher, so attestations work.

### 2. `release.yml` creates source archives

During experimental release, `release.yml` zips the library's build-relevant files (`src/`, `pyproject.toml`, `VERSION`, `README.md`) and attaches the archive to the GitHub Release as `<name>-v<version>-source.zip`.

### 3. Promote downloads the source archive

`promote.yml` always runs from `main` (not from a tag).  The experimental tag is a text input.  The workflow:

1. Checks out `main` — scripts and build tooling always come from the latest version.
2. Downloads the source archive from the experimental GitHub Release.
3. Unpacks it over `libraries/<name>/`, replacing main's source with the frozen experimental source.
4. Builds, publishes, tags, bundles, and deploys docs using main's CI infrastructure.

### 4. UX change

Maintainers no longer select a tag in the "Use workflow from" dropdown.  Instead they run `promote.yml` from `main` and type the experimental tag name into the input field.  This is a minor change but ensures the workflow YAML itself comes from `main`.

### 5. `release.yml` no longer accepts `workflow_call`

The `workflow_call` trigger, `checkout_ref` input, and `attestations` input are removed from `release.yml`.  They existed solely for the promote path.

### 6. PyPI trusted publisher configuration

`release.yml` publishes experimental packages.  `promote.yml` publishes stable packages.  Each workflow must be configured as a trusted publisher for its respective PyPI package names.

## Consequences

- CI script improvements automatically apply to future stable promotions without re-tagging.
- Attestations can be enabled for both experimental and stable publishes (no more identity mismatch).
- Experimental releases created before this change lack source archives and cannot be promoted with the new workflow.  They must be re-released or handled manually.
- Some build logic is duplicated between `release.yml` and `promote.yml`.  This is an acceptable tradeoff for single-page visibility and correct OIDC identity.
- PyPI trusted publisher settings must list both `release.yml` (for `chumicro-*-experimental`) and `promote.yml` (for `chumicro-*`).

