---
name: git-commit
description: How to write and execute git commits in this workspace. Use this skill whenever committing code to git.
---

# Git Commit Mechanics

**Never** use `git commit -m` — it breaks in zsh on special characters, backticks, parentheses, and multi-line messages.

**Never** write the commit message via the terminal — no heredocs, `echo`, `cat`, or `printf`. The agent terminal truncates multi-line input and loses closing delimiters.

**Always** write the message to `.scratch/commit-msg.txt` using a file tool, then commit with a single terminal command.

## Procedure

### Step 1 — Write the commit message

`insert_edit_into_file` **will append to the file** if it thinks the new content is an addition. This produces a commit message containing the previous commit's message concatenated with the new one. **This has happened repeatedly and must be prevented.**

When using `insert_edit_into_file` to write a new commit message:

1. **Provide only the new commit message as the complete file content.**
2. **Do not use `...existing code...` comments.** There is no existing code to preserve — the entire file is being replaced.
3. **Do not reference or include any part of the previous message.**

Use a **file tool** (not the terminal) to write the full commit message to `.scratch/commit-msg.txt`.

1. Check whether `.scratch/commit-msg.txt` exists (e.g., `read_file` or `list_dir`).
2. **If it does not exist:** use `create_file`.
3. **If it already exists:** use `insert_edit_into_file` to **replace** the file contents

**Never delete `.scratch/commit-msg.txt`** — not with `rm`, not from the terminal, not with any other tool. Always overwrite it in place with `insert_edit_into_file`.

Follow the project's commit-message conventions: imperative subject line, body explaining *why*.

### Step 2 — Stage and commit

```bash
git add -A && git commit -F .scratch/commit-msg.txt
```

Or stage selectively first, then commit:

```bash
git add <files>
git commit -F .scratch/commit-msg.txt
```

### Step 3 — Verify

```bash
git log --oneline -1
```

## Rules

- The `.scratch/` directory is gitignored — never commit it.
- Always verify the commit succeeded before moving on.
