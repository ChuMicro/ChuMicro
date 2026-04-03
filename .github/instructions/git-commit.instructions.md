---
applyTo: "**"
---

# Git Commit Mechanics

When making git commits, **never** use `git commit -m` — shell quoting in zsh breaks on special characters, backticks, parentheses, quotes, and multi-line messages. **Never** write the commit message via the terminal (heredocs, `echo`, `cat`, `printf`) — the agent terminal can truncate multi-line input and lose the closing delimiter.

Instead, **always** use the file-creation tool to write the message, then run only single-line terminal commands.

## Procedure

1. **Write the commit message to `.scratch/commit-msg.txt`** using a file tool (not the terminal):
   - **First commit in a session:** use `create_file` to create `.scratch/commit-msg.txt`.
   - **Subsequent commits:** use `insert_edit_into_file` to replace the entire content of `.scratch/commit-msg.txt`.

   Write the full commit message as the file content, following the project's commit-message conventions (imperative subject, body explaining *why*).

   **`insert_edit_into_file` behaviour warning:** this tool tries to merge edits intelligently. If you only provide the new message, it will *append* rather than replace. You must make it clear that the entire file content is being replaced — provide only the new commit message as the complete file content with no `...existing code...` comments.

2. **Commit using the file** (single-line terminal command):
   ```
   git commit -F .scratch/commit-msg.txt
   ```

## Rules

- **Never use `git commit -m "..."`** — it breaks on special characters in zsh.
- **Never write the commit message via the terminal** — no heredocs, no `echo`, no `cat`, no `printf`. The agent terminal truncates multi-line input. Always use a file tool.
- **Use `create_file` for the first commit, `insert_edit_into_file` for subsequent commits** — `create_file` cannot overwrite a path it already created in the same session.
- If `create_file` fails because the file already exists (leftover from a previous session), fall back to `insert_edit_into_file`.
- The `.scratch/` directory is gitignored and should never be committed.
