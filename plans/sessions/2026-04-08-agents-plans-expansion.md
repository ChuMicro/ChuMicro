# 2026-04-08 — AGENTS.md regressions and plans expansion

Participants: human + agent

## What happened

- Audited AGENTS.md against skills, plans, and contributing docs.  Found
  the main regressions were *operational* — no skills index, no context
  recovery guidance, no terminal rules — not in the development guidelines.
- Added "Agent operations" section to AGENTS.md: skills table, context
  recovery steps, terminal rules.  Added two common pitfalls (heredocs,
  large output).  Strengthened Contributing section with task-checkpoint
  and stronger git-commit skill triggers.
- Evaluated whether contributing docs (CLI, PyCharm, VS Code, PRs,
  releases, new-library) should be linked from AGENTS.md.  Decided no —
  the skills are the agent-optimized versions of the same knowledge, and
  linking human docs would create competing sources of truth.
- Discussed what was cut from `plans/` in ff9aa5f and whether it was too
  much.  Concluded the rationalization was healthy — the real value was in
  the deleted duplication, not lost content.
- Explored new planning infrastructure ideas: session logs, open questions,
  patterns cookbook, proposed decision status, decision cross-references.
  Human said yes to all five.

## Unfinished threads

- The patterns file draws from history.md's "Key technical patterns" —
  consider whether that section in history.md should now link to
  patterns.md to avoid drift, or whether history.md should keep its
  version as the "why it was hard" narrative while patterns.md is the
  "how to do it right" reference.
- Open questions were seeded from next-up.md and conversation.  Human
  and future contributors should review and add their own.

