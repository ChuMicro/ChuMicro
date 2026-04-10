# Decision 0022: No Single-Letter Variable Names / Banned Abbreviations

Status: `accepted`
Date: `2026-04-09`
Related: none

## Context

Single-letter variable names (`i`, `e`, `p`, `r`, `t`, `d`, etc.) kept appearing in both agent-written and human-written code despite a prose rule in AGENTS.md.  Prose rules are easy to ignore; automated enforcement is not.  Ruff has no built-in rule for variable name length, so a custom check was needed.

Short abbreviations like `env`, `buf`, `src`, `cmd`, `msg`, `err`, `ref` were originally allowed but still caused readability issues — they should be spelled out (`environment`, `buffer`, `source`, `command`, `message`, `error`, `reference`).

## Decision

**No single-letter variable names and no banned abbreviations**, enforced by a custom linter (`scripts/check_names.py`, rule `CHU001`).

- `_` is the only allowed single-letter name (throwaway / unused binding).
- Common Python idioms like `e`, `f`, `i`, `k`, `v` must be spelled out: `error`, `file`, `index`, `key`, `value`.
- The following abbreviations are banned and must be spelled out: `env`, `buf`, `src`, `cmd`, `msg`, `err`, `ref`.
- The check runs automatically as part of `python scripts/run.py lint`.
- Suppress with `# noqa: CHU001` when matching an upstream API (e.g., `micropython.const(x)`).

Short-but-complete words (`ok`, `tag`, `key`, `raw`, `pin`, `led`, `end`) and widely understood abbreviations (`dir`, `args`, `config`) are still fine — they are not on the banned list.

## Consequences

- `scripts/check_names.py` added, integrated into `lint()` in `run.py`.
- `CHU001` runs on the same paths ruff scans.
- All existing single-letter violations fixed or suppressed.
- AGENTS.md hard rules and common pitfalls updated.
- CONTRIBUTING.md project rules table updated.
- Existing violations are caught on the next `lint` or `preflight` run — no silent regression.
