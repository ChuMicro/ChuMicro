# Decision 0022: Variable and Parameter Naming Conventions

Status: `accepted`
Date: `2026-04-09`
Related: none

## Context

The project's naming guidance ("Descriptive names, not abbreviations") has been too vague to prevent regressions.  Single-letter variables and cryptic abbreviations keep appearing in both agent-written and human-written code, requiring repeated cleanup passes.  The existing rule in AGENTS.md's Naming & style section didn't specify what's allowed, what's banned, or why — so every contributor rediscovered the boundary independently.

## Decision

### No single-letter variables

Single-letter variable names are not allowed, with one exception:

- `_` — throwaway / unused binding (e.g., `for _ in range(n)`)

Common Python idioms like `e`, `f`, `i`, `k`, `v` must be spelled out: `error`, `file`, `index`, `key`, `value`.  Readability matters more than keystroke savings, especially for contributors reading unfamiliar code across 3+ runtimes.

### Allowed abbreviations

Short forms that a Python developer would understand without surrounding context:

| Abbreviation | Meaning |
|---|---|
| `dir` | directory |
| `args` | arguments |
| `cmd` | command |
| `env` | environment |
| `err` | error |
| `msg` | message |
| `ref` | reference (git context) |
| `dep` / `deps` | dependency / dependencies |
| `config` | configuration |
| `info` | information |
| `spec` | specification |
| `params` | parameters |

If an abbreviation isn't on this list, spell it out.  The list can grow via a PR that updates this decision — the bar is "would any Python developer recognize this instantly?"

### Banned patterns

| Instead of | Write |
|---|---|
| `n` | `count`, `length`, `limit` — whatever it represents |
| `t` | `tag`, `timestamp`, `target` — whatever it represents |
| `s` | `text`, `source`, `seconds` |
| `p` | `path`, `pattern`, `port` |
| `svc` | `service` |
| `dut` | `test_device` |
| `cb` | `callback` |
| `fn` | `function` or the specific name |
| `ctx` | `context` |
| `mgr` | `manager` |
| `impl` | `implementation` |
| `tgt` | `target` |

## Consequences

- AGENTS.md hard rules and common pitfalls updated.
- CONTRIBUTING.md project rules table updated.
- No automated enforcement — ruff has no variable-name-length rule.  This is enforced in code review and agent instructions.
- Existing violations should be fixed when the surrounding code is being modified, not in drive-by cleanup PRs.

