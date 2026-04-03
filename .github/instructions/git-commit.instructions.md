---
applyTo: "**"
---

# Git Commit Mechanics

When making git commits, **never** use `git commit -m` — shell quoting in zsh breaks on special characters, backticks, parentheses, quotes, and multi-line messages. **Never** write the commit message via the terminal (heredocs, `echo`, `cat`, `printf`) — the agent terminal can truncate multi-line input and lose the closing delimiter.

Instead, **always** use the file-creation tool to write the message, then run only single-line terminal commands.

## Procedure

1. **Delete any leftover scratch file** (single-line terminal command):
   ```
   rm -f .scratch/commit-msg.txt
   ```

2. **Write the commit message to a scratch file using the create_file tool** (not the terminal). Use a fixed path:

   Path: `.scratch/commit-msg.txt`

   Write the full commit message as the file content, following the project's commit-message conventions (imperative subject, body explaining *why*).

3. **Commit using the file** (single-line terminal command):
   ```
   git commit -F .scratch/commit-msg.txt
   ```

## Rules

- **Never use `git commit -m "..."`** — it breaks on special characters in zsh.
- **Never write the commit message via the terminal** — no heredocs, no `echo`, no `cat`, no `printf`. The agent terminal truncates multi-line input. Always use the file-creation tool.
- **Always delete `.scratch/commit-msg.txt` before writing** — the create_file tool cannot overwrite an existing file.
- The `.scratch/` directory is gitignored and should never be committed.
