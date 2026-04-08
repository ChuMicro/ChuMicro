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

Use `create_file` to write the full commit message to `.scratch/commit-msg.txt`. This overwrites any previous content.

Follow the project's commit-message conventions: imperative subject line, body explaining *why*, name affected libraries or decisions.

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
