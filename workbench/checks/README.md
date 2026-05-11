# chumicro-checks

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**The workspace lint rules ruff can't express — for ChuMicro mono-repos and downstream workspaces.**

A small CLI + rule set (`CHU001`–`CHU012`) covering descriptive names, mono-repo-vs-published-tree isolation, workbench-doesn't-import-libraries, silent test skips, plans-doc brevity, and other policies that ruff doesn't have a check for.  Drop it on any CPython 3.11+ workspace; rules silently no-op in repos where their target paths don't exist, so it's safe in the mono-repo, the workspace-template, or a downstream user workspace alike.

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
| `CHU006` | No mono-repo-internal references in publishable trees |
| `CHU007` | Workbench packages must not import library packages |
| `CHU008` | No upstream-derivative framing in workspace-template trees |
| `CHU009` | Test bodies must not silently `return` / `pass` |
| `CHU010` | Test functions must contain at least one assertion |
| `CHU011` | Plans-doc brevity — bullet caps on `plans/next-up.md` |
| `CHU012` | No dated narration / workstream-phase pointers in code comments |

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
