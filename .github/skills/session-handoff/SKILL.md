---
name: session-handoff
description: Capture session-transition context to plans/handoffs/ before clearing or switching sessions. User-invoked via /session-handoff — do not auto-trigger.
---

# Session Handoff

Used when you're about to `/clear`, switch to a fresh session, or otherwise leave conversation state behind, and the session produced context that would not survive `git log` + `plans/next-up.md` alone.

A handoff is a **faithful, complete state-transfer document** — as long as the session warrants. Not a tight summary. The next session should be able to pick up nearly fully informed by reading the handoff plus the warm-up ritual (`git --no-pager log --oneline -20` + `plans/next-up.md`).

## What belongs in a handoff vs. somewhere else

The handoff is for things that don't fit in the existing homes. **Lift durable signal first**, then capture what's left.

| Goes here (handoff) | Goes elsewhere |
|---|---|
| Mental model snapshots — how I was thinking about a system | Reusable code shape → `plans/patterns.md` |
| Half-formed hypotheses I didn't get to test | Structural / pattern / tooling tradeoff → `plans/decisions/NNNN-*.md` (use `new-decision`) |
| Failed attempts and dead ends, so future-me doesn't re-walk them | Agent-facing rule whose violation cost time → `AGENTS.md` non-negotiables |
| Things noticed but intentionally not fixed | Hardware / runtime quirk near the workaround → inline `# `-comment + commit-message body |
| Search terms / file paths that get you back into the headspace | What was tried and rejected with rationale → commit message body |
| Open questions waiting on user input | Work scope that outgrew 5 sub-bullets → `plans/workstreams/<name>.md` |
| Conversation-state context (where my reasoning was when we paused) | Anything that should be `git blame`-able |

If something belongs in one of the right-column homes, route it there — the handoff is for what's left over.

## Steps

### 1. Decide if a handoff is needed

```bash
git --no-pager status --short
git --no-pager log --oneline -10
```

Skip the handoff entirely if all of these are true:
- Working tree is clean (no uncommitted changes)
- `plans/next-up.md` `## Now` accurately reflects the next session's pickup state
- Nothing was learned this session that isn't already captured in the four homes above
- No open questions waiting on the user

If skipping, tell the user "no handoff needed — clean session, next-up is current" and stop.

### 2. Lift durable signal to its home first

Walk the four homes from the table above. For each thing the session produced, ask: does this belong in an ADR, in `patterns.md`, in `AGENTS.md`, in an inline comment, or in the next commit message body? If yes, route it there *now* (or tell the user it should be routed before the handoff is written). Don't dump durable lessons into the handoff — they'll rot there.

### 3. Capture session-only signal

Ask the user (or work from conversation context if it's already clear) — these prompts shape what goes in the handoff:

- What was this session about? What triggered it?
- What's in flight that didn't get committed?
- What was decided but not yet acted on?
- What was learned (about the codebase, a tool, a board, a bug) that hasn't been written up anywhere?
- What needs to be re-researched or verified next session?
- What were the dead ends — paths tried that didn't pan out, so future-me doesn't re-walk them?
- What are the open questions waiting on a user answer?
- What gotchas surfaced — workarounds applied, brittle assumptions, environmental quirks?
- If the next session has only the handoff and `git log`, what context would they still be missing? Add pointers (key files, ADRs, search terms) to rebuild fast.

### 4. Write the handoff file

Path: `plans/handoffs/<YYYY-MM-DD>-<slug>.md`. Use today's date (the actual current date, not a guess) and a short kebab-case slug describing the topic.

Template — include only the sections that have content; drop empty sections rather than leaving placeholders:

```markdown
# Handoff <YYYY-MM-DD> — <one-line topic>

## What this session was about

<paragraph: goal entering the session, what triggered it>

## What's in flight

<uncommitted changes, partial work, files mid-edit; cite paths>

## What got done

<items that landed; cite commit SHAs>

## Decisions made (not yet captured in ADRs)

<reasoning, tradeoffs, why we picked this over alternatives. If something here grows past a few sentences, promote it to an ADR via `new-decision` and link from here.>

## What was learned

<discoveries about the codebase, surprises, behaviors. If a discovery is durable cross-session signal, route it to the right home (table above) and link from here instead of duplicating.>

## To re-research / verify next session

<things needing eyes-on, hypotheses to check, missing data, follow-up questions for upstream>

## Dead ends

<paths tried that didn't pan out, with a one-line "why not" so future-me doesn't re-walk them>

## How to rebuild context fast

<key files to re-read, recent commits to look at, search terms / grep patterns, related ADRs/workstreams to skim, any external links>

## Open questions waiting on user

<things blocked on a decision the user hasn't made yet>

## Gotchas

<workarounds applied, brittle assumptions, environmental quirks, anything that would bite future-me>
```

Length follows the session — a 30-minute exploratory session might produce 20 lines; a multi-hour debugging marathon might produce 200. Both are fine. Don't pad, don't truncate.

### 5. Update `plans/next-up.md`

Append one top-level bullet to `## Now` pointing at the handoff:

```markdown
- [ ] **Resume <topic> from session handoff** — see [`handoffs/<YYYY-MM-DD>-<slug>.md`](handoffs/<YYYY-MM-DD>-<slug>.md).
```

Keep it to one line (CHU011 caps each top-level bullet at 5 lines including sub-bullets — a one-line top-level is the right shape here). When the work picked up *from* this handoff finishes, the bullet migrates to `## Done (recent)` per the normal AGENTS.md rule, and the handoff file becomes git history.

### 6. Show diff, commit

Show the user the diff (handoff file + next-up.md edit). Once approved, follow the `git-commit` skill — pass the message via a single-quoted heredoc (`git commit -m "$(cat <<'EOF' … EOF)"`). Commit message names the handoff topic and links any related workstream or ADR.

After commit, the handoff is durable — the user can `/clear` knowing the next session's warm-up will surface it via `next-up.md ## Now`.
