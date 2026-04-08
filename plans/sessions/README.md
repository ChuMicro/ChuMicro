# Session Log

Short entries capturing what happened in a working session — especially
context that doesn't survive in commit messages alone.

## When to write an entry

- A meaningful direction was set or changed during conversation.
- Something was tried and abandoned *before* a commit captured it.
- A human gave feedback that shaped design choices.
- An agent session ended with unfinished threads worth preserving.

**Not every session needs an entry.**  If the commits tell the whole story,
skip it.

## Format

Filename: `YYYY-MM-DD-<slug>.md` (e.g., `2026-04-08-settings-api-design.md`).
Multiple entries on the same day get different slugs.

```markdown
# <Date> — <One-line summary>

Participants: <who worked — human, agent, both>

## What happened

<!-- 3-10 bullet points. What was attempted, decided, or discovered.
     Link to commits, decisions, or open questions when relevant. -->

## Unfinished threads

<!-- Anything that needs follow-up but isn't in next-up.md yet.
     Move to next-up.md or open-questions.md when appropriate. -->
```

## Rules

- Keep entries short — 10-30 lines.  This is a log, not a design document.
- Link to decisions and commits rather than duplicating their content.
- Delete entries older than ~2 months if their content has been absorbed
  into decisions, history, or commit messages.  Session logs are ephemeral
  context, not permanent records.

