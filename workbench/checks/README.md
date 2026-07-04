# chumicro-checks

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**The workspace lint rules ruff can't express — for ChuMicro mono-repos and downstream workspaces.**

A small CLI + rule set (`CHU001`–`CHU034`, with `CHU021`–`CHU023` retired) covering descriptive names, mono-repo-vs-published-tree isolation, workbench-doesn't-import-libraries, silent test skips, plans-doc brevity, command-table parity, docstring-capability honesty, cross-runtime example imports, coverage-claim honesty, whitespace / line-ending hygiene in doc + plan trees ruff never sees, archived-decision marker consistency, ADR-authoring discipline, governance-doc orphan detection, demo-surface isolation, the no-async-in-library-code contract, the one-device-staging-path reservation, and other policies that ruff doesn't have a check for.  Drop it on any CPython 3.11+ workspace; rules silently no-op in repos where their target paths don't exist, so it's safe in the mono-repo, the workspace-template, or a downstream user workspace alike.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all workbench tools.](https://github.com/ChuMicro/ChuMicro/tree/main/workbench)
> This is a [workbench tool](https://github.com/ChuMicro/ChuMicro/blob/main/docs/contributing/workbench.md) — runs on your laptop, not on the board.

## Install

```bash
pip install chumicro-checks
```

## Quick example

```bash
# Lint the current repo with all applicable rules
chumicro-checks

# Run a specific rule
chumicro-checks --select CHU006

# Skip a rule
chumicro-checks --ignore CHU012
```

Each rule walks the paths it targets and silently no-ops in repos where those paths don't exist — `chumicro-checks` is safe to run in either the chumicro mono-repo, the workspace-template repo, or a downstream user workspace.

## What's included

### Rules

| Code | Rule |
|---|---|
| `CHU001` | Descriptive names — no single-letter variables outside an allowlist |
| `CHU002` | File must end with exactly one newline |
| `CHU003` | No more than two consecutive blank lines |
| `CHU004` | No trailing whitespace |
| `CHU005` | No blank line immediately after a Python block opener |
| `CHU006` | No mono-repo-internal references in publishable trees |
| `CHU007` | Workbench packages must not import library packages |
| `CHU008` | No upstream-derivative framing in workspace-template trees |
| `CHU009` | Test bodies must not silently `return` / `pass` |
| `CHU010` | Test functions must contain at least one assertion |
| `CHU011` | Plans-doc brevity — bullet caps on `plans/next-up.md` |
| `CHU012` | No dated narration / workstream-phase pointers in code comments |
| `CHU013` | No mid-tick `ticks_ms` refetch — use the runner-supplied `now_ms` |
| `CHU014` | Workspace CLI command-table parity — no phantom/hidden commands |
| `CHU015` | Module-docstring "future work" claims must match shipped symbols |
| `CHU016` | Example imports must resolve on every declared runtime |
| `CHU017` | Coverage % must not be cited as a whole-codebase guarantee |
| `CHU018` | Files must use LF line endings — no CR / CRLF |
| `CHU019` | Dead ADRs must carry a filename lifecycle marker matching status / `Archived:` |
| `CHU020` | Closed AI-tic phrase set — drop unfounded adjectives + sentence-opener filler in user-facing prose |
| `CHU024` | No history banners on accepted ADRs — edit the body in place |
| `CHU025` | `Superseded by:` pointers and filename markers must name an existing ADR |
| `CHU026` | Governance docs referenced from AGENTS.md must be auto-loaded via CLAUDE.md's `@`-include chain |
| `CHU027` | No cross-site duplicate comment / docstring blocks — explain once in a canonical home |
| `CHU028` | No cross-ADR principle duplication — one invariant, one home |
| `CHU029` | Every ADR must carry a non-empty `Summary:` frontmatter field |
| `CHU030` | Demo drivers may reach only `chumicro_workspace.deploy_api` and must pin `deploy_mode="flash"` |
| `CHU031` | noqa / pragma explanations use ` - ` separators, not em-dash / en-dash / double-hyphen |
| `CHU032` | No cross-reference pointer phrases in publishable comments — each stands alone for a cold reader |
| `CHU033` | No `async` / `await` / `asyncio` in first-party package code — use generators |
| `CHU034` | Device-staging primitives are `chumicro_deploy`-internal — stage code through `Deployer.deploy_diff()` |

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

Leaf — no upstream ChuMicro deps.  Used directly by `python scripts/run.py lint` in the mono-repo and by `chumicro-workspace lint` in downstream workspaces.

## Platform support

CPython 3.11+ only.  Workbench tool — runs on your laptop, never on a board.

## Contributing

Working on `chumicro-checks` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
```

## Find this library

- **PyPI:** [chumicro-checks](https://pypi.org/project/chumicro-checks/)
- **Source:** [workbench/checks](https://github.com/ChuMicro/ChuMicro/tree/main/workbench/checks)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
