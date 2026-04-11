# Decision 0022: No Single-Letter Variable Names / Banned Abbreviations

Status: `accepted`
Date: `2026-04-09`
Related: none

## Context

Single-letter variable names (`i`, `e`, `p`, `r`, `t`, `d`, etc.) kept appearing in both agent-written and human-written code despite a prose rule in AGENTS.md.  Prose rules are easy to ignore; automated enforcement is not.  Ruff has no built-in rule for variable name length, so a custom check was needed.

Short abbreviations like `env`, `buf`, `src`, `cmd`, `msg`, `err`, `ref` were originally allowed but still caused readability issues — they should be spelled out (`environment`, `buffer`, `source`, `command`, `message`, `error`, `reference`).

## Why this helps

Code is read far more often than it is written.  Descriptive names remove the mental step of translating abbreviations back to their meaning, especially for contributors who are new to the codebase.

A useful side effect: longer names push lines past the 100-character limit, which forces multi-line formatting.  That forced splitting consistently improves readability — each argument on its own line is easier to scan, diff, and annotate with `git blame`.

## Decision

**No single-letter variable names and no banned abbreviations**, enforced by a custom linter (`scripts/check_names.py`, rule `CHU001`).

- `_` is the only allowed single-letter name (throwaway / unused binding).
- Common Python idioms like `e`, `f`, `i`, `k`, `v` must be spelled out: `error`, `file`, `index`, `key`, `value`.
- The following abbreviations are banned and must be spelled out: `env`, `buf`, `src`, `cmd`, `msg`, `err`, `ref`, `addr`, `exc`, `exec`.
- Banned abbreviations are also caught as **suffixes** in compound names (e.g., `base_ref` → `base_reference`, `build_env` → `build_environment`).  `_dir` is exempt — it is a short-but-complete word like `key` or `tag`.
- The check covers variables, parameters, exception handler names, and function/method names.
- The check runs automatically as part of `python scripts/run.py lint`.
- Suppress with `# noqa: CHU001` only when matching an upstream API that you cannot rename.

Short-but-complete words (`ok`, `tag`, `key`, `raw`, `pin`, `led`, `end`) and widely understood abbreviations (`dir`, `args`, `config`) are still fine — they are not on the banned list.

## Consequences

- `scripts/check_names.py` added, integrated into `lint()` in `run.py`.
- `CHU001` runs on the same paths ruff scans.
- All existing single-letter violations fixed or suppressed.
- AGENTS.md hard rules and common pitfalls updated.
- CONTRIBUTING.md project rules table updated.
- Existing violations are caught on the next `lint` or `preflight` run — no silent regression.
