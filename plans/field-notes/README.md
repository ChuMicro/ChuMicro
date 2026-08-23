# Field notes

Observed behavior that no rule captures: hardware quirks, bench measurements, tooling traps, and what a session actually did.

This is the drain. Detail that would otherwise swell AGENTS.md, a code comment, a docstring, or `plans/next-up.md` lands here instead. Nothing here is loaded into an agent session, so nothing here costs context until someone opens it.

## What goes where

| Content | Home |
|---|---|
| A rule every session must hold | `AGENTS.md` |
| A rule for one tree | `.claude/rules/` |
| A tradeoff and its rejected alternatives | `plans/decisions/` |
| A reusable implementation recipe | `plans/patterns.md` |
| A multi-phase plan being executed | `plans/workstreams/` |
| One line per item in flight | `plans/next-up.md` |
| Everything below | here |

- Hardware behavior a board actually showed, with the board and runtime named.
- Bench numbers: allocation deltas, flash and RAM figures, timings.
- Tooling traps that cost a session.
- Session narration: what was tried, what was ruled out, what remains. One file per topic, appended to.

## Rules for entries

- Date each entry and name the board, runtime, and command.
- Record what happened, not what it means. A conclusion that holds becomes an ADR or a rule and gets deleted from here.
- Never point at a field note from a code comment or a docstring. Comments stand alone.
