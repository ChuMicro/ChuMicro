# chumicro-checks

Workspace-internal lint rules — `CHU0NN` codes — shared between the
chumicro mono-repo and the
[ChuMicro-Workspace-Template](https://github.com/ChuMicro/ChuMicro-Workspace-Template)
starter repo.

The rules enforce policies that ruff can't express:

| Code | Rule |
|------|------|
| CHU001 | Descriptive names — no single-letter variables outside an allowlist |
| CHU006 | No mono-repo-internal references in publishable trees |
| CHU007 | Workbench packages must not import library packages |
| CHU008 | No upstream-derivative framing in workspace-template trees |
| CHU009 | Test bodies must not silently `return` / `pass` |
| CHU010 | Test functions must contain at least one assertion |
| CHU011 | Plans-doc brevity — bullet caps on `plans/next-up.md` |
| CHU012 | No dated narration / workstream-phase pointers in code comments |

## Install

```bash
pip install chumicro-checks
```

## Use

```bash
# Lint the current repo with all applicable rules
chumicro-checks

# Run a specific rule
chumicro-checks --select CHU006

# Skip a rule
chumicro-checks --ignore CHU012
```

Each rule walks the paths it targets and silently no-ops in repos
where those paths don't exist — `chumicro-checks` is safe to run in
either the chumicro mono-repo, the workspace-template repo, or a
downstream user workspace.

## Configure

Per-repo defaults via `pyproject.toml`:

```toml
[tool.chumicro-checks]
ignore = ["CHU012"]
```

CLI flags (`--select` / `--ignore`) override the config file.

## Suppress an individual finding

`# noqa: CHU0NN` on the offending line (Python, TOML, INI), or
`<!-- noqa: CHU0NN -->` for Markdown. Pair every suppression with a
one-line *why* a reviewer can verify.
