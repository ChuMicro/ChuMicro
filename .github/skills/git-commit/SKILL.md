---
name: git-commit
description: How to write and execute git commits in this workspace. Use this skill whenever committing code to git.
---

# Git Commit Mechanics

Pass the commit message inline via a **single-quoted heredoc** consumed by `git commit -m "$(cat <<'EOF' … EOF)"`.  The single quotes around the `EOF` delimiter disable shell expansion inside the heredoc, so backticks, `$`, parentheses, and newlines pass through literally.  This was bench-validated 2026-05-10 against backticks, em-dashes, arrows, and `\x`-escapes.

Earlier versions of this skill required writing the message to `.scratch/commit-msg.txt` first.  That rule was a workaround for a different agent harness (GitHub Copilot's terminal truncated multi-line input); it doesn't apply here.  The scratch-file path still works if you prefer it, but the heredoc form is the canonical pattern.

## Prerequisite

This skill is the commit-mechanics layer.  The discipline that gates the commit — preflight + `plans/next-up.md` refresh + durable-lesson lift — lives in [`task-checkpoint`](../task-checkpoint/SKILL.md), which invokes this skill at its commit step.  Calling `git-commit` directly without `task-checkpoint` having just run is a procedural gap, not an option (per AGENTS.md "always invoke task-checkpoint at end of work" — applies per coherent unit of work, including doc / plans / handoff units).  The only valid direct entry is re-staging after a commit-time failure where preflight already ran in the prior `task-checkpoint` cycle (e.g. a hook rejected the message and the fix is purely textual).

## Procedure

### Step 1 — Compose and run the commit

```bash
git add <files>
git commit -m "$(cat <<'EOF'
imperative subject line — under 70 chars

Body explaining *why*, not *what*.  The diff explains what.  Use blank
lines between paragraphs.  Reference workstreams / decisions / patterns
by name where they motivate the change.
EOF
)"
```

Use `git add <files>` with explicit paths rather than `git add -A` so unrelated in-flight work in the working tree doesn't get bundled in.  Check `git --no-pager diff --cached --stat` before committing to confirm only the intended files are staged.

Follow the project's commit-message conventions: imperative subject line, body explaining *why*.  No `Co-Authored-By: Claude …` trailer — this repository's convention is that commits are authored by the human running the agent.  Claude Code's default commit template includes such a trailer; omit it.  A local `commit-msg` hook (`.git/hooks/commit-msg`, not tracked) strips any that slip through, so don't be surprised if a trailer you typed disappears in `git log`.

### Step 2 — Verify

```bash
git --no-pager log -1 --format='%H%n%s%n---body---%n%b'
git --no-pager show --stat --format= HEAD
```

The first command confirms the subject + body landed intact.  The second lists the files the commit actually contains — compare it against the files the message claims to change.  A parallel agent session or linter hook can stage files in the window between your `diff --cached --stat` check and the commit, and those riders land silently.  If a file you didn't intend appears: do **not** `--amend`.  Revert the rider with a follow-up commit (`git restore --source=HEAD~1 -- <path>` then commit the restoration, naming the scramble), and tell the user which session's work was swept.

## Notes

- The single-quoted `<<'EOF'` is load-bearing.  An unquoted `<<EOF` would let the shell expand backticks and `$VAR` inside the message — a backtick-quoted code reference in the body could trigger a shell call and break the commit.
- If a hook fails after the commit runs, the commit did not land — create a *new* commit after the fix.  Never `--amend` to recover from a hook failure (that would rewrite the previous commit).
- `.scratch/` remains gitignored — handy for log captures and one-off temp files.  No commit-message workflow depends on it.
