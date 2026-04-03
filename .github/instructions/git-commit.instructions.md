---
applyTo: "**"
---

# Git Commit Mechanics

When making git commits from the terminal, **always** use a temporary scratch file for the commit message. Never use `git commit -m` with inline strings — shell quoting in zsh breaks on special characters, backticks, parentheses, quotes, and multi-line messages.

## Procedure

1. **Create the scratch directory** if it doesn't exist:
   ```
   mkdir -p .scratch
   ```

2. **Write the commit message to a unique temporary file** using a random suffix to avoid collisions with leftover files from previous failed commits:
   ```
   COMMIT_FILE=".scratch/commit-msg-$RANDOM.txt"
   cat > "$COMMIT_FILE" << 'COMMIT_EOF'
   Subject line here in imperative mood

   Body paragraph explaining why the change was made.
   Reference affected libraries, decisions, or workstreams.
   COMMIT_EOF
   ```
   - Use a heredoc with a **single-quoted delimiter** (`<< 'COMMIT_EOF'`) so the shell performs no interpolation inside the message body.
   - `$RANDOM` is a zsh/bash built-in that produces a different integer each invocation.

3. **Commit using the file**:
   ```
   git commit -F "$COMMIT_FILE"
   ```

4. **Clean up all scratch commit files** (not just the one from this commit — catch any orphans from previous failures):
   ```
   rm -f .scratch/commit-msg-*.txt
   ```

5. Steps 2–4 as a **single copy-paste block**:
   ```
   COMMIT_FILE=".scratch/commit-msg-$RANDOM.txt" && \
   mkdir -p .scratch && \
   cat > "$COMMIT_FILE" << 'COMMIT_EOF'
   Subject line here

   Body here.
   COMMIT_EOF
   git commit -F "$COMMIT_FILE" && \
   rm -f .scratch/commit-msg-*.txt
   ```

## Rules

- **Never use `git commit -m "..."`** — it is the source of repeated quoting failures.
- **Never use double-quoted heredoc delimiters** (`<< COMMIT_EOF` without quotes) — the shell will expand `$variables` and `` `backticks` `` inside the message.
- **Always clean up** with `rm -f .scratch/commit-msg-*.txt` after the commit, even if the commit fails. This catches orphans from previous attempts.
- The `.scratch/` directory is gitignored and should never be committed.
- If `git commit` fails (e.g., nothing staged), still run the cleanup step.

