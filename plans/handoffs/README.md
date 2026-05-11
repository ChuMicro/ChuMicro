# Session Handoffs

Session-transition state-transfer notes. Each file captures the context a
fresh session would need to pick up where the previous one left off —
mental-model snapshots, half-formed hypotheses, dead ends, search terms
that rebuild context fast, open questions waiting on user input.

## What goes here vs. somewhere else

Handoffs are **only** for context that doesn't fit in the existing homes:

- Reusable code shape → [`patterns.md`](../patterns.md)
- Structural / pattern / tooling tradeoff → [`decisions/`](../decisions/) (use `new-decision` skill)
- Agent-facing rule whose violation cost time → [AGENTS.md](../../AGENTS.md) non-negotiables
- Hardware / runtime quirk near the workaround → inline `#`-comment + commit-message body
- Work scope that outgrew 5 sub-bullets → [`workstreams/`](../workstreams/)

Lift durable signal to its right home first; the handoff is for what's left.

## How to write one

Use the `session-handoff` skill (user-invoked: `/session-handoff`). The
skill walks the four homes above, captures session-only context, writes
the handoff file here, and adds a one-line pointer to
[`next-up.md`](../next-up.md) `## Now` so the next session's warm-up ritual
surfaces it.

When the work picked up *from* a handoff finishes, the bullet migrates to
`## Done (recent)` per the normal AGENTS.md rule, and the handoff file
becomes part of git history.
