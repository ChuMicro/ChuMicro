# Handoff 2026-05-26 — Apply /regen-comments interactive-walk pattern to audit skills

## What this session was about

Built `/regen-comments` from scratch — a slash command that regenerates docstrings + comments on a target tree using a writer subagent + verifier subagent pair, orchestrated by the director (the assistant invoking the skill). Validated end-to-end via bench test on `libraries/events/src/`. The user ran the bench test in a separate session and observed something that hasn't shown up in any existing audit skill: the director walked the verifier's findings one at a time, presenting 2-4 concrete options per finding via `AskUserQuestion`, with a "Recommended" tag on the option the director leaned toward.

The user named the contrast: `/audit-library`, `/audit-comments`, etc. produce a wall of findings the user has to read in full and respond to in free text — typically ~20 minutes of typing per audit. The walk-with-options pattern in `/regen-comments` reduces each judgment to a click + optional "Other" custom text. This handoff captures what to do about that in the next session.

## What got done (committed)

- `d139e882` — `chumicro_timing 0.4.4: docstring rewrite via commenter-casual-friendly persona`. 13-iteration converged comment-style applied to the timing library. [VERIFIED: `git --no-pager show d139e882 --stat`]
- `b62a8eb4` — `Add /regen-comments skill: strip + writer + verifier orchestration`. The skill, the AST stripper, the `strip-comments` run.py subcommand, the verifier persona, and updates to the writer persona (rare-body exception + `Exposes the X shape/surface` AI-tic ban). [VERIFIED: `git --no-pager show b62a8eb4 --stat` shows 5 files / 811 insertions]

## What's in flight (uncommitted)

- `libraries/events/{VERSION, src/chumicro_events/*}` — the docstrings the bench test produced. The user ran the bench test in a separate session; whether to keep these changes is undecided. Verifier flagged 1 CRITICAL, 4 IMPORTANT, 7 AMBIGUOUS; the user walked all findings and accepted edits during the bench test. Files differ from `main` but the diff lives in the other session's working tree, not this one's. [HYPOTHESIS: cheapest test = `git --no-pager diff libraries/events/ | head -40` in the bench-test session reveals the final state] If discarding, `git restore libraries/events/`. If keeping, bump VERSION (already at 0.2.4 in the bench session) and commit. The user can decide independently of the audit-skill work.
- `.idea/chumicro.iml` — IDE drift, ignore as usual.

## What the next session is asked to do

Look at the existing audit skills under `.github/skills/audit-*/SKILL.md`:

- `audit-comments`
- `audit-library`
- `audit-docs`
- `audit-embedded`
- `audit-integration`
- `audit-workspace`
- `audit-skill`
- `audit-publishable-isolation`

Decide where to apply the patterns from `/regen-comments`. The three load-bearing patterns are:

1. **Director / verifier separation with bias notice.** The director is biased after reading the code; a second agent (verifier persona, system prompt only) reads the output blind to the prior context. Director acknowledges its bias explicitly and defers to the verifier's tiered findings. See `.claude/agents/commenter-verifier.md` for the verifier persona structure and `.github/skills/regen-comments/SKILL.md` § "The director's bias problem".

2. **Tiered findings: CRITICAL / IMPORTANT / MINOR / AMBIGUOUS.** Each finding carries a category tag (`paraphrase`, `body-paragraph`, `mechanism-verb`, `cold-reader-fail`, etc.) and tier. MINOR filtered by default. AMBIGUOUS explicitly means "needs human judgment" — surfaces a question, not a recommendation.

3. **Interactive walk-findings flow with per-finding `AskUserQuestion` option lists.** Director surfaces ONE finding at a time, shows the current state, proposes 2-4 concrete options (with "(Recommended)" on the lean), accepts user choice, applies the edit, moves to next finding. User confirmed this is the first interaction shape that materially reduced the cognitive load of audit review.

The user pain point this targets: "*audit skills usually have me spend 20 minutes typing my reply from the huge output, and think deeply about what its asking. having the options presented to me really helps me understand what youre proposing as a fix, and gives me the opportunity to provide better judgement if needed.*"

## Riskiest assumption

**The patterns generalize from `/regen-comments` to audit skills.** Comment regen has naturally discrete, locally-fixable findings (one docstring at a time). Some audit skills produce findings that are *entangled* — a structural refactor in `/audit-library` might touch six files where flagging once + walking once isn't the right shape. Cheapest test: take `/audit-comments` (closest in spirit to `/regen-comments`) and try retrofitting the verifier + walk pattern. If the findings naturally fit the per-finding `AskUserQuestion` shape, the broader retrofit is worth pursuing; if they fight the shape, the pattern is comment-pass-specific and shouldn't be force-fit.

## What audit-library already does (read end-of-session before the handoff was finalized)

After writing the first draft of this handoff, the user asked the director to read `audit-library/SKILL.md` to ground judgment.  [VERIFIED: read in full from `.github/skills/audit-library/SKILL.md`]  Findings that shape the retrofit:

- **Confidence tiers already exist:** `HIGH-CONFIDENCE / MEDIUM-CONFIDENCE / TASTE-CALL / ESCALATE` with dimension tags (`honesty / duplicate / shape / dead-code / wiring / perf / flow / prose / lean / policy / cross-lib / sibling-cohesion`).  The skill is more sophisticated than my reflection document credited.  Output-format section at lines 199-251.
- **HIGH items are batch-executed** (step #6: "Execute high-confidence items as one cohesive commit") — *no per-finding user review*.  That's correct as-is.  Forcing `AskUserQuestion` on every HIGH finding (dead code, obvious dupe, lying class name) would be friction-addition, not friction-reduction.
- **MEDIUM items are one-per-commit but free-text-surfaced** (step #7: "Execute medium-confidence items as separate commits, one per finding").  This is the retrofit lever — currently the user reads the punch-list and replies in free text, then the agent acts.  Per-finding `AskUserQuestion` with rewrite/edit/skip/defer options would land here.
- **TASTE-CALL findings are explicitly user-judgment-required** ("Hand off remaining low items to the user").  Same retrofit lever as MEDIUM.
- **Prose findings already route to `/audit-comments`** (lines 93, 99) — the audit-library skill defers comment-rewrite work to the comment-rewrite skill.  Existing precedent for skill chaining; the retrofit shouldn't break this.
- **The auditor reads the entire library top-to-bottom first** (step #1).  Same shape as the `/regen-comments` director bias problem: one agent reads everything, then judges its own findings.  Verifier-blind separation is *technically* applicable here, but heavier-handed than what's needed — the bench-test value came from per-finding option lists, not from a separate verifier agent.  The verifier-blind insight may matter more for `/audit-skill` and the audit-* family at large than for `/audit-library` in isolation.

The targeted retrofit, then, is narrower than the original handoff framing suggested:

1. **Step 5 ("Present the punch-list")** — when surfacing MEDIUM + TASTE findings to the user, use `AskUserQuestion` per finding with options sized to that finding's category.  For a `prose` finding routed to `/audit-comments`, the options might be `{Run /audit-comments on this file now, defer to next session, accept the trim suggestion inline, write my own replacement}`.  For a `shape` finding, options might be `{Inline as proposed, leave for /audit-library follow-up, write the refactor differently, skip}`.
2. **Step 7 ("Execute medium-confidence items")** — keep one-commit-per-finding shape; replace free-text user input with the AskUserQuestion-derived choice.
3. **HIGH batch stays as-is** — mechanical fixes don't benefit from per-finding option lists.
4. **ESCALATE handling is broken; fix it as part of the retrofit.**  Currently ESCALATE means "file a one-line bullet under `## Next` in `plans/next-up.md` pointing at `/audit-integration <name>,<other>` or `/audit-workspace`."  Context loss is severe: the file:line, the dimension tag, the specific concern, the surrounding-code awareness the auditor had at the moment of finding all collapse to a one-liner that ages further as related code shifts.  [VERIFIED: `plans/next-up.md` lines 17, 19, 30, 31, 32, 34, 35, 36 all show audit-escalation residue at varying context fidelity; line 19 in particular is "both are large libraries left over from the prior session's 'next session' list" — pure inheritance, no grounding for the pickup session.]  This is a meaningful design gap that hides behind the existing `## Next` mechanism.  Candidate fixes the next session can design (don't pre-commit to one):
   - Audits write a per-run findings file (`plans/audits/<library>-<YYYY-MM-DD>.md`) with full context for every finding including ESCALATEd ones; the `## Next` bullet is a pointer to that file, not the canonical record.
   - ESCALATE findings auto-attach to the relevant existing workstream file if one matches, or seed a new workstream stub with the captured context.
   - The audit's punch-list output is itself archived under `plans/audits/` so an escalation is never written without its surrounding findings being co-located.
   None of these is a finished design; the next session should pick one based on what's cheap to adopt across the audit-* family.

The next session can validate this read against the actual skill text and propose specific edits.

## What the audit-* family looks like collectively (uneven priority for retrofit)

[ASSUMED] My read after only audit-library:

- `/audit-library` — biggest output, highest user-pain.  Targeted retrofit on steps 5/7 (above).  Highest-priority pickup.
- `/audit-comments` — closer in spirit to `/regen-comments`.  Already runs in two passes (subtractive Pass 1, reconstructive Pass 2).  Output format is similar punch-list shape.  May benefit from the same retrofit, but smaller output per pass so lower urgency.
- `/audit-skill` — meta-skill that audits other skills.  HIGH/MEDIUM/LOW confidence already used.  Could absorb the new "candidate findings" (director-bias acknowledgement, AskUserQuestion-walk, persona-content-embedding) as new dimension tags once validated.
- `/audit-docs`, `/audit-embedded`, `/audit-integration`, `/audit-workspace`, `/audit-publishable-isolation` — not read this session.  [HYPOTHESIS: cheapest test = the four sibling skills share the same punch-list output format and step 5/7 shape, so a retrofit pattern that works for `/audit-library` and `/audit-comments` should mechanically apply to them.  Confirm by reading one before committing to a generalization.]

## To re-research / verify next session

- [ ] Skim each audit skill's current "report findings" / "surface to user" section. The natural retrofit candidates (high-volume discrete findings, low cross-file entanglement) come first. [HYPOTHESIS: cheapest test = `for s in .github/skills/audit-*/SKILL.md; do echo "=== $s ==="; grep -n -A3 'Output\|Punch\|Findings\|Surface' "$s" | head -20; done`]
- [ ] Look at the bench-test transcript pattern in this session's history (won't survive `/clear` — but the *shape* is reproduced in `regen-comments/SKILL.md` § 7 "Consolidate and surface findings"). The director's per-finding script: show current state, paste the verifier's diagnostic, propose 2-4 options including "Recommended", call `AskUserQuestion`, apply choice.
- [ ] Decide whether `/audit-skill` (the skill that audits other skills) should flag absence of the walk-pattern as a finding. May be premature — codify after one or two audit skills have been retrofitted and the pattern proves durable.
- [ ] `[VERIFY: web]` — Anthropic SDK's `AskUserQuestion` tool: confirm the "multiSelect" behavior, the 4-option cap, "Other" auto-injection on single-select. The patterns I used worked but my recall is from `AskUserQuestion`'s tool description in *this* session's context — re-read it at the top of the next session before designing retrofits.

## Dead ends (so next session doesn't re-walk)

- **Embedding persona content into a `general-purpose` subagent prompt as a workaround for "custom subagents weren't loaded at session start"** — looked necessary mid-session because the new persona files didn't appear in this session's `subagent_type` enum. The bench test in a *fresh* session proved the harness auto-discovers `.claude/agents/*.md` files at startup; `subagent_type: "commenter-casual-friendly"` and `subagent_type: "commenter-verifier"` work natively. Don't reach for the embedding workaround when retrofitting other skills — register the persona as a `.claude/agents/<name>.md` file and dispatch natively.
- **Director-edits-inline for mechanical fixes (E501 trims)** — looked harmless until the user noticed the bench-test report. The director has read the baseline and is biased; inline trims inject editorial word-choices the verifier never recognizes as such. Fix: re-dispatch the writer with the offending lines + "shorten while preserving meaning". Skill text now reflects this in § 5; for audit skills, the same principle applies — *mechanical fixes route back to the analyst agent, not patched by the director*.
- **Iterating on the persona by running it on a single library across many versions** — produced a converged voice but took 13 rounds. Half the iterations were chasing metrics (verb dominance %, unique-verb count) that turned out not to be quality signals once verbs were honest. Lesson for audit-skill retrofits: don't optimize on metric counts; optimize on whether each finding the verifier produces is actually useful to the user.

## Gotchas

- **`.claude/skills/` is a symlink to `../.github/skills/`** — I checked this wrong twice mid-session before the user corrected me. Canonical write path is `.github/skills/<name>/SKILL.md`. Don't try to sync them or stage both; they're the same file.
- **`.claude/agents/` is a *real* directory, tracked via `.gitignore` whitelist (`!.claude/agents`)**. Not a symlink. Add new persona files there directly.
- **The `AskUserQuestion` "(Recommended)" suffix on the first option is the convention I used**. Worked well — gave the user a default while preserving room to redirect. Document this pattern explicitly in any retrofit's SKILL.md so future authors know the convention.
- **"Other" is auto-injected for single-select questions** — don't manually add "(Other)" as an option; the tool handles it. (re-confirm against tool description on resume — [VERIFY: web])
- **MINOR findings default-filtered** — the verifier produces them but the director suppresses by default unless the user asks for exhaustive review or there are fewer than 3 findings total. This was a deliberate choice to avoid drowning the user; preserve it in retrofits.
- **AMBIGUOUS tier is the human-only category** — never resolve these in the director or in MINOR-filtering passes. The verifier flags AMBIGUOUS because it lacks project context; only the user can resolve them.

## How to rebuild context fast

Key reads (in order):

1. `.github/skills/regen-comments/SKILL.md` — the orchestration pattern in full. Sections 3 (writer dispatch), 5 (lint→writer re-dispatch), 6 (verifier dispatch), 7 (consolidate + surface) are the templates to crib from.
2. `.claude/agents/commenter-verifier.md` — the verifier persona structure: scope guard, tier definitions with examples, structured output format, "what you don't do" section.
3. `.claude/agents/commenter-casual-friendly.md` — the writer persona, in particular the rare-body exception (rules sometimes need a narrow carve-out, not absolute bans).
4. The two relevant commits: `d139e882` (the converged voice in action) and `b62a8eb4` (the skill itself).
5. The user's bench-test summary in the previous session's conversation history — the format the director used to surface findings, the structured output the verifier produced, the per-finding walk.

Memory entries that explain the design choices (all under `~/.claude/projects/-Users-chuxor-circuitpython-chumicro/memory/`):

- `feedback_dont_feed_history_to_comment_passes.md` — why the writer prompt is minimal.
- `feedback_persona_ab_test_pattern.md` — methodology for testing whether rules earn their keep.
- `feedback_exposes_the_x_shape_ai_tic.md` — the AI-tic the user caught during the bench test (an instance of how the system self-improves).
- `feedback_no_docstring_bodies.md` — the rule that has the carve-out; useful template for "default no, narrow exception" rule shape.

Search terms / patterns to scan codebase fast:

- `grep -l 'Walk findings\|punch.list\|surface findings' .github/skills/` — find existing audit-skill report sections to retrofit.
- `grep -l 'subagent_type' .github/skills/` — find existing skills that already dispatch subagents (to model the verifier-dispatch pattern on).
- `ls .claude/agents/` — current persona inventory (writer + verifier as of this commit).
