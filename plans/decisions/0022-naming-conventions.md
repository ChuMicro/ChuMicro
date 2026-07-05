# Decision 0022: No Single-Letter Variable Names / Banned Abbreviations

Status: `accepted`
Date: `2026-04-09`
Summary: `CHU001` lint forbids single-letter variables (except `_`) and banned abbreviations (`env`, `buf`, `src`, `cmd`, `msg`, etc.); for-loop targets exempt for humans only.
Related: none

## Context

Single-letter variable names (`i`, `e`, `p`, `r`, `t`, `d`, etc.) kept appearing in both agent-written and human-written code despite a prose rule in AGENTS.md.  Prose rules are easy to ignore; automated enforcement is not.  Ruff has no built-in rule for variable name length, so a custom check was needed.

Short abbreviations like `env`, `buf`, `src`, `cmd`, `msg`, `err`, `ref` were originally allowed but still caused readability issues — they should be spelled out (`environment`, `buffer`, `source`, `command`, `message`, `error`, `reference`).

## Why this helps

Python's common abbreviations — `msg`, `err`, `exc`, `buf`, `cmd` — are tribal knowledge.  They come from C and Unix culture, and experienced Python developers read them without thinking.  But not everyone has that background:

- **Newcomers to Python** (or to programming) don't know that `exc` means "exception" or `buf` means "buffer."  They have to guess from context or look it up.
- **Multilingual developers** working across Python, JavaScript, Swift, Kotlin, Rust, or Go don't share a single set of abbreviation conventions.  `msg` is obvious if you've spent years in Python, but it's just a three-letter fragment if you haven't.
- **Non-native English speakers** may not recognize that `err` is a truncation of "error" — especially when reading quickly or scanning unfamiliar code.

The abbreviations save a few keystrokes per line.  The full words save every future reader a mental lookup.  We chose the side that scales.

The other driver, stated plainly because it's load-bearing: a large share of the patches in this repo are agent-written.  Agents obey lint rules and ignore prose conventions (the Context above is the receipt), so anything the project actually cares about has to be a lint rule.  Humans inherit the same gate because maintaining two divergent rule sets is worse than one strict one.

This is a deliberate tradeoff.  Experienced developers will find it verbose, and the rule fights muscle memory that predates this project.  The linter names the exact replacement, which makes each hit mechanical — not free.

A side effect we've come to like, not a goal: longer names push some lines past the 100-character limit, which forces multi-line formatting, and an argument per line is easier to diff and `git blame`.

## Decision

**No single-letter variable names and no banned abbreviations**, enforced by a custom linter (`CHU001` in the [`chumicro-checks`](../../workbench/checks/) package).

- `_` is the only allowed single-letter name in general code (throwaway / unused binding).
- **For-loop targets are exempt** — `for i in range(10)` and `for k, v in items()` are fine.  The exemption applies only to the loop variable itself; single-letter names in the loop body are still flagged.
- Common Python idioms like `e`, `f`, `k`, `v` must be spelled out in non-loop contexts: `error`, `file`, `key`, `value`.
- The following abbreviations are banned and must be spelled out: `env`, `buf`, `src`, `cmd`, `msg`, `err`, `ref`, `addr`, `exc`, `exec`.
- Banned abbreviations are also caught as **suffixes** in compound names (e.g., `base_ref` → `base_reference`, `build_env` → `build_environment`).  `_dir` is exempt — it is a short-but-complete word like `key` or `tag`.
- The check covers variables, parameters, exception handler names, and function/method names.
- The check runs automatically as part of `python scripts/run.py lint`.
- Suppress with `# noqa: CHU001` only when matching an upstream API that you cannot rename.

Short-but-complete words (`ok`, `tag`, `key`, `raw`, `pin`, `led`, `end`) and widely understood abbreviations (`dir`, `args`, `config`) are still fine — they are not on the banned list.

**AI agents** continue to use descriptive names like `index` even in for-loops — the exemption is a convenience for human contributors, not a style change for generated code.

## Consequences

- `CHU001` lives in the [`chumicro-checks`](../../workbench/checks/) workbench package; `scripts/run.py:lint()` shells out to `python -m chumicro_checks` after ruff finishes.
- `CHU001` runs on the same paths ruff scans.
- All existing single-letter violations fixed or suppressed.
- AGENTS.md hard rules and common pitfalls updated.
- CONTRIBUTING.md project rules table updated.
- Existing violations are caught on the next `lint` or `preflight` run — no silent regression.
