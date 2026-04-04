---
name: terminal-recovery
description: How to recover from a stuck or hung terminal. Use this skill when a terminal command does not produce output, hangs, or shows a continuation prompt.
---

# Terminal Recovery

The agent terminal can get stuck when a command has unclosed quotes, broken heredocs, dangling pipes, or other syntax errors. The shell waits for more input and the command never finishes.

**The fastest fix is always Ctrl-C.** Do not try to "fix" the input by sending a closing quote or delimiter — it rarely works and wastes turns.

## Symptoms of a stuck terminal

- A command produces no output and does not return.
- The shell shows a continuation prompt (`>`, `quote>`, `dquote>`, `heredoc>`).
- A background process or pager is blocking (e.g., `less`, `man`, `git log` without `--no-pager`).

## Recovery procedure

1. **Send Ctrl-C** by running a single character command: press Ctrl-C or use the interrupt mechanism available in the terminal tool. This sends SIGINT and returns to a clean prompt.
2. **Verify recovery** — run a trivial command (e.g., `echo ok`) to confirm the shell is responsive.
3. **Retry the original task** with a corrected command. Do not repeat the broken command verbatim.

## Prevention

- **Never use heredocs** (`<< EOF`) in the agent terminal. They are fragile and frequently lose the closing delimiter.
- **Never use multi-line quoted strings** passed directly to the terminal. Write file content using file tools instead.
- **Always disable pagers** — use `git --no-pager`, pipe through `| cat`, or set `GIT_PAGER=cat`.
- **Quote variables** — use `"$var"` not `$var` to prevent word splitting.
- **Prefer single-line commands.** If a command must span lines, chain with `&&` or `;` on one line rather than using backslash continuations.

