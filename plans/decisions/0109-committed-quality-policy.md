# Decision 0109: `quality.toml` is the committed quality-policy home for workspaces

Status: `accepted`
Date: `2026-07-05`
Summary: Workspace quality gates live in a committed `quality.toml` at the workspace root; `workspace.yml`'s `quality:` block becomes a per-machine override that wins per key.
Related: Decision 0057 (workspace-config file shape — edited in place), Decision 0029 (project workspace), Decision 0038 (gitignored files materialized on setup)

## Context

Decision 0057 placed the `quality` block (lint knobs, coverage threshold) in `workspace.yml`, which is gitignored because dev mode writes machine-specific paths into its `library_sources:` block.  The 2026-07-05 template audit surfaced the consequence: a workspace cloned from the template has no committed home for its own gates.  `pyproject.toml` carries the defaults but is tool-owned (`update` rewrites it), and any `quality:` edit in `workspace.yml` exists only on the machine where it was typed — clone the same project repo elsewhere and the gates silently reset.  One file was carrying two kinds of state with different sharing needs: machine-local wiring and project policy.

## Decision

Quality policy gets its own committed, user-owned file: `quality.toml` at the workspace root, next to `run.py`.  TOML mirror of the existing block, top-level keys before the `[lint]` table:

```toml
coverage_threshold = 85

[lint]
enabled = true
tools = ["ruff", "chumicro-checks"]
select = ["E", "F", "I"]
```

`load_quality_config` reads both sources and merges per key, one level deep for `lint`.  Precedence, highest first:

1. CLI passthrough args (unchanged — user `--` args already win).
2. `workspace.yml`'s `quality:` block — the per-machine override, gitignored.
3. `quality.toml` — the committed policy that travels with the repo.
4. `pyproject.toml` defaults (`fail_under`, `[tool.ruff]`) as the floor.

Each source validates separately so a shape error names the file that carries it.  A missing `quality.toml` behaves exactly like the pre-0109 world, so existing workspaces need no migration.

The template ships a `quality.toml` starter with every knob present but commented, so the file documents itself without duplicating code defaults.  It is user-owned: `update` never touches it.

## Rejected

- **Make `pyproject.toml` user-owned.**  Forfeits `update`'s ability to evolve dependencies and tool config for existing workspaces.
- **Commit `workspace.yml` and move `library_sources:` to a gitignored overlay.**  Inverts the established contract of Decision 0057 for every existing workspace, and `deploy_targets` device ids are per-user anyway.
- **Section-level ownership inside `pyproject.toml`.**  The template-zone system is file-granular; section-granular merge tooling is a new mechanism to maintain for one consumer.

## Consequences

- `chumicro_workspace.quality` reads `quality.toml` (stdlib `tomllib`) and merges; `QUALITY_TOML_NAME` names the file.  Minor version bump.
- Decision 0057's file-shape table is edited in place: `quality` in `workspace.yml` is now described as the per-machine override, with the committed policy in `quality.toml`.
- The template repo ships the commented starter and documents the two-layer story in CONTRIBUTING's quality section and AGENTS.md's ownership table.
- `status` / `doctor` do not yet validate `quality.toml`; a malformed file surfaces at `lint` / `test` time with the file named.  Add a health check if that proves too late in practice.
