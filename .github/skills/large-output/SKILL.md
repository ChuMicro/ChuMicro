---
name: large-output
description: How to handle commands that produce large output (test suites, linting, builds, preflight). Use this skill when running commands whose output may exceed the terminal buffer.
---

# Large Output

Commands like `python scripts/run.py preflight`, `test --all`, or `lint` can produce hundreds of lines. The agent terminal may truncate output, hiding failures.

## Quick patterns

**See just the result** (most common):

```
python scripts/run.py preflight 2>&1 | tail -5
```

**Find failures in test output:**

```
python scripts/run.py test --all 2>&1 | grep -E "FAILED|ERROR|failed"
```

**Find lint violations:**

```
python scripts/run.py lint 2>&1 | grep -v "^+" | head -40
```

**Full output to a file, then inspect:**

```
python scripts/run.py preflight > .scratch/preflight.log 2>&1; tail -20 .scratch/preflight.log
```

Then read `.scratch/preflight.log` with a file tool if more context is needed.

## Key markers in this workspace

| Command | Success marker | Failure marker |
|---------|---------------|----------------|
| `preflight` | `Preflight passed` | `Preflight failed at: <step>` |
| `test` | `X passed` | `FAILED` or `ERROR` in pytest output |
| `lint` | `All checks passed!` | Ruff violation lines (file:line:col) |
| `build` | `Built N package(s)` | Python traceback |

## Rules

- **Always pipe through `tail`, `head`, or `grep`** when output may be large. Do not run long commands bare.
- **Use `2>&1`** to capture stderr alongside stdout — pytest and ruff both write to stderr in some modes.
- **Use `python -u`** for Python scripts that produce incremental output — disables buffering so partial results are visible.
- **Redirect to `.scratch/`** when you need to inspect the full output — the directory is gitignored.
