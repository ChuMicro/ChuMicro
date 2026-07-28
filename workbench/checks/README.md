# chumicro-checks

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Lint rules for the things ruff has no check for: naming discipline, prose and doc-tree hygiene, and the policies a project decides for itself.**

A CLI and a rule set, `CHU001`-`CHU037` (`CHU021`-`CHU023` are retired), covering checks that live outside Python syntax: descriptive naming, whitespace and line-ending hygiene in the doc and plan trees ruff never reads, docstrings that promise capabilities the module doesn't ship, examples that import a module one of their declared runtimes doesn't have, and standing policies such as the ban on `async` in library code.  Drop it on any CPython 3.11+ workspace and run it with no configuration.  The table below lists every rule.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md): it runs on your laptop, not on the board.

## Install

```bash
pip install chumicro-checks
```

## Quick example

```bash
# Lint the current repo with all applicable rules
chumicro-checks

# See every registered rule and its one-line description
chumicro-checks --list

# Run a specific rule
chumicro-checks --select CHU006

# Skip a rule
chumicro-checks --ignore CHU012

# Lint a repo other than the one you're standing in
chumicro-checks --root ~/code/my-workspace
```

Without `--root`, `chumicro-checks` lints the nearest ancestor directory holding a `.git` or a `pyproject.toml`.

Each rule walks the paths it targets.  When a rule's target paths aren't there, the rule reports nothing and the run carries on, so a repo that has only some of the trees these rules know about still gets a clean, useful run.

## What's included

### Rules

| Code | Rule |
|---|---|
| `CHU001` | Descriptive names: no single-letter variables outside an allowlist |
| `CHU002` | File must end with exactly one newline |
| `CHU003` | No more than two consecutive blank lines |
| `CHU004` | No trailing whitespace |
| `CHU005` | No blank line immediately after a Python block opener |
| `CHU006` | No mono-repo-internal references in publishable trees |
| `CHU007` | Workbench packages must not import library packages |
| `CHU008` | No upstream-derivative framing in workspace-template trees |
| `CHU009` | Test bodies must not silently `return` / `pass` |
| `CHU010` | Test functions must contain at least one assertion |
| `CHU011` | Plans-doc brevity: bullet caps on a repo's `plans/next-up.md` |
| `CHU012` | No dated narration / workstream-phase pointers in code comments |
| `CHU013` | No mid-tick `ticks_ms` refetch; use the runner-supplied `now_ms` |
| `CHU014` | Workspace CLI command-table parity: no phantom or hidden commands |
| `CHU015` | Module-docstring "future work" claims must match shipped symbols |
| `CHU016` | Example imports must resolve on every declared runtime |
| `CHU017` | Coverage % must not be cited as a whole-codebase guarantee |
| `CHU018` | Files must use LF line endings, never CR or CRLF |
| `CHU019` | Dead ADRs must carry a filename lifecycle marker matching status / `Archived:` |
| `CHU020` | Closed AI-tic phrase set: drop unfounded adjectives and sentence-opener filler from user-facing prose |
| `CHU024` | No history banners on accepted ADRs; edit the body in place |
| `CHU025` | `Superseded by:` pointers and filename markers must name an existing ADR |
| `CHU026` | Governance docs referenced from AGENTS.md must be auto-loaded via CLAUDE.md's `@`-include chain |
| `CHU027` | No cross-site duplicate comment or docstring blocks: explain once in a canonical home |
| `CHU028` | No cross-ADR principle duplication: one invariant, one home |
| `CHU029` | Every ADR must carry a non-empty `Summary:` frontmatter field |
| `CHU030` | Demo drivers may reach only `chumicro_workspace.deploy_api` and must pin `deploy_mode="flash"` |
| `CHU031` | noqa / pragma explanations use ` - ` separators, not em-dash / en-dash / double-hyphen |
| `CHU032` | No cross-reference pointer phrases in publishable comments: each stands alone for a cold reader |
| `CHU033` | No `async` / `await` / `asyncio` in first-party package code; use generators |
| `CHU034` | Device-staging primitives are `chumicro_deploy`-internal; stage code through `Deployer.deploy_diff()` |
| `CHU035` | Example `helpers.py` copies must stay byte-identical to `scripts/templates/examples_helpers.py` |
| `CHU036` | Device code must use subscript syntax, not `.__setitem__` / `.__getitem__` / `.__delitem__` (unavailable on CircuitPython / MicroPython built-ins) |
| `CHU037` | No em-dashes in user-facing prose: markdown docs and the templates that scaffold them |

### Configuration

Per-repo defaults via `pyproject.toml`:

```toml
[tool.chumicro-checks]
ignore = ["CHU012"]
```

CLI flags (`--select` / `--ignore`) override the config file.

### Suppressing an individual finding

`# noqa: CHU0NN` on the offending line (Python, TOML, INI), or `<!-- noqa: CHU0NN -->` for Markdown.  Pair every suppression with a one-line *why* a reviewer can verify.

## Where this fits

No upstream ChuMicro dependencies.  Run `chumicro-checks` on its own, or let [`chumicro-workspace`](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/workspace) run it: `chumicro-workspace lint` runs ruff and then `chumicro-checks` by default, and tells you to install this package if it isn't there.

## Platform support

CPython 3.11+ only.  This is a workbench tool: it runs on your laptop, never on a board.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on my own workspace and here's what it flagged", some of the most useful feedback a lint tool can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Find this library

- **PyPI:** [chumicro-checks](https://pypi.org/project/chumicro-checks/)
- **Source:** [workbench/checks](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/checks)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
