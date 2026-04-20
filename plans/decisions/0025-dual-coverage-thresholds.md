# Decision 0025: Dual coverage thresholds

Status: `accepted`
Date: `2026-04-12`
Related: [Decision 0009](0009-per-library-test-runs.md)

## Context

The project started with a single coverage gate (90 %, later raised to 94 %)
configured in `pyproject.toml` and enforced on every `test` and `preflight`
run.  This worked well for agent-authored code, which can easily hit high
coverage, but human contributors sometimes had to write disproportionate
test code for small bug fixes — the high gate created friction without
improving safety.

## Decision

Two thresholds:

| Audience | Threshold | Enforcement |
|----------|-----------|-------------|
| Human contributors | 85 % | Default in `pyproject.toml` `[tool.coverage.report].fail_under` |
| Agents | 94 % | `--coverage-threshold 94` on every `test` and `preflight` invocation |

`run.py test` and `run.py preflight` accept a `--coverage-threshold PCT`
flag that overrides the `pyproject.toml` value.  When the flag is absent,
the pyproject default (85 %) applies.

**Per-library scoping in preflight:** When `--coverage-threshold` is passed
to `preflight`, the elevated threshold applies only to libraries the caller
changed (detected via `detect_changed_packages()`).  Unchanged libraries
use the `pyproject.toml` default.  This prevents agents from failing on
pre-existing coverage in human-authored code they didn't touch.  When
change detection returns `None` (infrastructure change, no diff, or no
git), the threshold applies to all libraries.

When `--coverage-threshold` is passed directly to `test`, it applies
uniformly to all libraries being tested — the caller chose the scope
explicitly via `--all` or `--libraries`.

Agent instructions in `AGENTS.md` and the `task-checkpoint` skill require
`--coverage-threshold 94`.

CI enforces the human baseline (85 %) so that PRs from any contributor pass
the same minimum bar.  Agent tooling raises the bar on the agent side.

## Consequences

- `pyproject.toml` `fail_under` is set to 85.
- `--coverage-threshold` flag added to `test` and `preflight` subcommands.
- Agents can no longer pass preflight with coverage below 94 % on libraries
  they changed, but are not blocked by pre-existing coverage in libraries
  they didn't touch.
- Human contributors benefit from a lower barrier to entry.
- The open question "Should the coverage gate be higher?" is resolved.
