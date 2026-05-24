# Decision 0025: Dual coverage thresholds

Status: `accepted`
Date: `2026-04-12`
Summary: Humans default to 85% coverage (pyproject default); agents pass `--coverage-threshold 94` for elevated gate; the 94% is CPython-reachable post-pragma, no device-execution coverage.
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

### What 94 % does and does not cover

The 94 % figure is honest only with its scope stated:

- It is **CPython-only**.  Tests run under CPython pytest; the
  per-runtime device adapters that actually execute on the shipped
  targets — e.g. `sockets/_adapters/mp.py`, the CircuitPython
  `microcontroller.nvm` path — are blanket `# pragma: no cover - device
  only` because their imports don't exist under CPython.  ~20 such
  pragmas in `sockets` alone.  Those modules contribute **nothing** to
  the 94 %.
- It is therefore a **post-exclusion** number: 94 % of the
  CPython-reachable lines, not 94 % of shipped code.  There is no
  device-execution coverage signal anywhere in the gate today.
- On the **CI path** there is no per-library 94 % gate at all (CI
  passes no `--coverage-threshold` — see [Decision 0009](0009-per-library-test-runs.md));
  the 94 % bar exists only when an agent or `preflight --coverage-threshold 94`
  passes it, and even then gates each library against the
  CPython-reachable subset.

The individual pragmas are defensible — you cannot run MicroPython
`usocket` under CPython pytest.  What this ADR forbids is presenting the
post-exclusion CPython figure as *the* advertised safety bar with no
device-coverage signal beside it.  Any doc or claim that cites 94 % as
the coverage guarantee must carry this scope, or be wrong.

## Consequences

- `pyproject.toml` `fail_under` is set to 85.
- `--coverage-threshold` flag added to `test` and `preflight` subcommands.
- Agents can no longer pass preflight with coverage below 94 % on libraries
  they changed, but are not blocked by pre-existing coverage in libraries
  they didn't touch.
- Human contributors benefit from a lower barrier to entry.
- The open question "Should the coverage gate be higher?" is resolved.
- 94 % is contractually a **CPython-reachable, post-pragma** figure with
  no device-execution coverage signal.  Closing that gap (a
  device-adapter coverage source, and/or a per-library threshold on the
  CI path) is tracked as the `audit-remediation-and-drift-mechanization`
  workstream's Phase 1 item 2 — this ADR makes the current scope honest;
  it does not claim the gap is closed.
- The honesty of any coverage claim against this scope is itself a
  Phase 4 mechanized check ([Decision 0074](0074-drift-mechanization-as-project-policy.md)).
