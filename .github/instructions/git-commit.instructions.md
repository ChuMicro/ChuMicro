---
applyTo: "**"
---

# Git Commit Mechanics

When making git commits, **never** use `git commit -m` — shell quoting in zsh breaks on special characters, backticks, parentheses, quotes, and multi-line messages. **Never** write the commit message via the terminal (heredocs, `echo`, `cat`, `printf`) — the agent terminal can truncate multi-line input and lose the closing delimiter.

Instead, **always** use the file-creation tool to write the message, then run only single-line terminal commands.

## Procedure

1. **Write the commit message to a scratch file using the create_file tool** (not the terminal). Use a fixed path:

   Path: `.scratch/commit-msg.txt`

   Write the full commit message as the file content, following the project's commit-message conventions (imperative subject, body explaining *why*).

2. **Commit using the file** (single-line terminal command):
   ```
   git commit -F .scratch/commit-msg.txt
   ```

3. **Clean up** (single-line terminal command):
   ```
   rm -f .scratch/commit-msg*.txt
   ```

## Rules

- **Never use `git commit -m "..."`** — it breaks on special characters in zsh.
- **Never write the commit message via the terminal** — no heredocs, no `echo`, no `cat`, no `printf`. The agent terminal truncates multi-line input. Always use the file-creation tool.
- **Always clean up** with `rm -f .scratch/commit-msg*.txt` after the commit, even if the commit fails.
- The `.scratch/` directory is gitignored and should never be committed.
