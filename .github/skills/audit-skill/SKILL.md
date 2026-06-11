---
description: Audits an existing skill on disk against the skill-writing rules in AGENTS.md and the skill's own stated goal. Use when a skill's flow feels off, contradicts itself, or routes wrong — or before relying on it for important work. Examples: "audit the audit-docs skill", "/audit-skill audit-library", "is the audit-library skill achieving its goal?".
allowed-tools: Read, Edit, Grep, Bash(ls *), Bash(cp *), Bash(mkdir *), Bash(date *), Bash(python3 *), AskUserQuestion, Agent
argument-hint: "<slug-or-path>"
arguments:
  - target
when_to_use: |
  Use when an existing skill routes the wrong messages, when its body
  contradicts its frontmatter, when its tool list is over-broad or skips
  AskUserQuestion at user-input forks, when its sub-agent dispatch is
  sequential where parallel was needed, or when a fresh cold-walk would
  surface drift the author normalized after weeks on the file. Also fires
  on "validate X against spec" / "check X for issues" phrasings. Do NOT
  use to author a new skill — that workflow is /new-skill. This skill
  detects the misroute at Step 1 and redirects.
---

# Audit Skill

Audits a SKILL.md, its reference files, and any persona files it dispatches. Five sub-agents read in parallel. Four apply checklists — loader-routing accuracy, body walkability and goal-derivability, tool-use craft, and sub-agent orchestration. The fifth proposes adjacent improvements. The director merges checklist findings into a tiered punch-list, prints ideas as a separate menu, then asks whether to apply inline fixes or hand off to `/new-skill` for a re-author.

## When to use this skill

- A skill's directives feel confusing or contradictory on a cold read.
- A skill's goal is hard to derive from reading its SKILL.md top-to-bottom.
- A skill never reaches for `AskUserQuestion`, sub-agents, or parallelism where they would obviously serve the user better.
- Before relying on a skill for important or repeated work.
- After significant edits to a skill, to check what drift landed.

**Don't use for:**

- Authoring a new skill — that's [`/new-skill`](../new-skill/SKILL.md). This skill detects the misroute at Step 1 and redirects.

## Invocation

| Form | Behavior |
|---|---|
| `/audit-skill <slug>` | Resolves the slug to `.claude/skills/<slug>/SKILL.md` or `.github/skills/<slug>/SKILL.md`, then audits |
| `/audit-skill <path>` | Audits the SKILL.md at the explicit path |
| `/audit-skill` (no arg) | Asks the user which skill via `AskUserQuestion` populated from the tree's slug list |

## Definition of done

You are done when **all** of these are true:

1. Pre-flight resolved a real SKILL.md, OR redirected cleanly to a different artifact's audit / authoring tool.
2. Five sub-agent readers ran in parallel; findings from the four checklist readers merged into a tiered punch-list (CRITICAL / IMPORTANT / MINOR / AMBIGUOUS) with source attribution per finding; ideas from the fifth reader surfaced in a separate menu (or "Ideas: none").
3. The user picked a next action for findings — apply inline fixes, route to re-author, or print as report-only — and that action ran to completion. (Ideas sign-off and Edits are tracked in item 5.)
4. If the target is being handed off to `/new-skill` (re-author), a backup landed at `.scratch/skills-backup/skills/<slug>-<UTC>/` where `<UTC>` is an ISO-8601 stamp from `date -u +%Y%m%dT%H%M%SZ`. Inline fixes (Step 8) rely on git for recovery; no backup needed.
5. When the ideas-reader returned ≥ 1 idea, the user worked through the per-idea action question for each picked idea. The available actions depend on the findings choice: in inline-fix / report-only modes, actions are apply / apply-with-edits / discuss / skip; in re-author mode, actions are include-in-seed / discuss / skip. The Ideas block in the report shows resolved outcomes (no `pending` entries remain).

## Process

### 1. Pre-flight — confirm the target is actually a skill

Resolve `<target>` to a SKILL.md path. When `<target>` is an explicit path containing `/`, `ls` it directly:

```bash
ls "<target>"
```

Otherwise treat `<target>` as a slug and check both common locations, capturing each result. `.claude/skills/` is the loader path; some projects keep the files under `.github/skills/` and symlink `.claude/skills` to them, in which case either `ls` resolves to the same file:

```bash
ls .claude/skills/<slug>/SKILL.md 2>/dev/null
ls .github/skills/<slug>/SKILL.md 2>/dev/null
```

If both `ls` outputs are empty (no path resolved), the request might be about a different artifact — fire a redirect `AskUserQuestion`:

> "I can't find a SKILL.md at `<target>`. What kind of artifact did you mean to audit?" `header: Artifact kind`
> Options:
> - "It's a SKILL.md — I'll give a different path"
> - "Prose doc (README / guide.md / INSTALL) — route to `/audit-docs`"
> - "Code comments / docstrings — route to `/audit-comments`"
> - "A persona file in `.claude/agents/` — I'll find the dispatching skill and print the re-route invocation"
> - "Authoring a new skill from scratch — route to `/new-skill`"

Each non-SKILL.md option carries a `preview` field showing the invocation form the user would land on after picking — for example, the `/audit-docs` option previews `/audit-docs <target>`; the `/audit-comments` option previews `/audit-comments <target>`; the `/new-skill` option previews `/new-skill <slug-or-description>`. AskUserQuestion previews render side-by-side on focus, so the user can compare destinations before picking. When the user picks a non-skill option, print the previewed invocation in chat and exit cleanly.

For the persona-file pick, fire a follow-up `AskUserQuestion` populated by `grep -lE '<persona-name>' .github/skills/**/SKILL.md` to confirm the dispatching skill, then print `Now run: /audit-skill <parent-slug>` and exit. The director does not auto-invoke `/audit-skill` on the parent (same hand-off pattern as Step 7's `/new-skill` re-author).

**Success criteria:** EITHER an absolute path to a real SKILL.md is printed AND the request is confirmed as a skill audit, OR a recommended-invocation print landed for a non-skill artifact and the skill exited.

### 2. Inventory the audit target

Print a structured inventory:

```bash
ls <skill-dir>/*.md 2>/dev/null
ls <skill-dir>/scripts/ 2>/dev/null
ls <skill-dir>/trigger-evals.json 2>/dev/null
grep -E 'subagent_type:|new-skill-|audit-skill-|.claude/agents/' <skill-dir>/SKILL.md
grep -E '^description:.*Examples:' <skill-dir>/SKILL.md
```

Capture: the SKILL.md path, any reference files in the skill directory, any bundled scripts, any custom persona files the skill dispatches (cited by `subagent_type:` or a path under `.claude/agents/`), and whether a `trigger-evals.json` exists (it feeds the measured-routing lane in Step 4). The `Examples:` grep surfaces the `"<m1>", "<m2>", "<m3>"` block on the description line.

If the description carries no `Examples:` block, salvage three trigger phrases from `when_to_use`. **If both sources are empty, surface a CRITICAL finding ("description carries no triggers") and stop before the Step 4 dispatch. Without trigger messages the loader-reader cannot run.**

After the inventory grep returns the persona names, check each one against the live agent registry. A persona file on disk but not in the registry (freshly written, session not restarted) cannot be dispatched at Step 4. When a persona is on disk but unregistered, stop and tell the user: *"Persona `<name>` is on disk but not in this session's agent registry. Restart the session and re-invoke `/audit-skill <slug>` to pick it up; or proceed with the remaining N readers and the audit will run with that lens missing."* Then fire one `AskUserQuestion` letting the user pick *Restart* or *Proceed with N readers*. *Proceed* records the missing lens as a director follow-up note in the Step 6 report.

**Success criteria:** an inventory block printed in chat naming every file the audit covers — SKILL.md absolute path, reference-file paths, persona-file paths — plus the three trigger messages (or a CRITICAL stop). Every persona file the SKILL.md cites resolves at `.claude/agents/<name>.md` AND is dispatchable from the live agent registry (or the user explicitly accepted the missing-lens fallback).

Steps 3, 4, and 6 consume these paths and triggers.

### 3. Director's own goal-derivability draft — before sub-agents

Read the SKILL.md and the reference files from a fresh, top-to-bottom pass. From that read alone, draft TWO things, holding both in chat:

(a) A 2–3 sentence goal: what the skill claims to do, what it actually walks through, and what a reasonable goal statement would be.

(b) An expected-findings list: 3–6 bullets naming what any well-formed audit of this skill type should surface (frontmatter structure, walkability, orchestration choice, persona shape, scope, blindness contracts, anything else worth surfacing). These are predictions, not observations.

The expected-findings list is the comparison baseline for Step 5's missing-content pass. Items in your list that no checklist sub-agent touched become director follow-up notes — that's the mechanical way to catch what's not in the body but should be.

**Success criteria:** both the goal draft and the expected-findings list are in chat, ready to compare against sub-agent findings in Step 5.

**Rules:**
- Do not Read any other audit-* skill in this repo. They may be wrong and would bias the draft.
- Do not Read the five `audit-skill-*` persona files. They carry the rules the sub-agents enforce; reading them now biases the director toward what the sub-agents will find.

### 4. Dispatch five sub-agent readers in ONE message

Fire five `Agent` tool calls **in one message**. The harness runs concurrent calls from a single message; sequential messages serialize them.

Pattern: 3c parallel lens-split (per the orchestration-reader's taxonomy) — same SKILL.md input, four checklist personas each judging a disjoint lens (loader / cold-walk / craft / orchestration) plus one generative persona (ideas). The director catalogs disjoint findings into one tiered punch-list (Step 5) and prints the generative menu separately (Step 6b). This is not the classic second-opinion 3b pattern (same input + same spec, consolidate agreement vs divergence); the lenses are disjoint by design and agreement-vs-divergence is not the merge criterion.

Pass the three trigger messages extracted at Step 2 (from the audited SKILL.md's `description: … Examples: "<m1>", "<m2>", "<m3>"` line, or the `when_to_use` salvage) to the loader-reader.

| Sub-agent | Lens | Inputs |
|---|---|---|
| `audit-skill-loader-reader` | Frontmatter contract — description voice + length, `name` rules, `when_to_use`, per-message routing | absolute SKILL.md path; the three example user messages |
| `audit-skill-cold-walker` | Body walkability + goal-derivability — per-step Success criteria, Done-when, reference-file links, AI-tic / hedging / moralizing patterns, stance | absolute SKILL.md path; reference-file paths from the inventory |
| `audit-skill-craft-reader` | Tool-use at user-interaction moments (`AskUserQuestion`, `multiSelect`, `preview`, `SendUserFile`, `Agent`), scope coverage vs minimum-deliverable stop, focused-step opportunities, repeated work that should be a bundled script, weak directives | absolute SKILL.md path |
| `audit-skill-orchestration-reader` | Sub-agent dispatch correctness, one-message batching, model selection, director-bias warning, persona-file structure, hook-vs-skill routing | absolute SKILL.md path; persona-file paths from the inventory |
| `audit-skill-ideas-reader` | Generative menu — alternative framings, adjacent problems to fold in, harness tools the skill could use but doesn't, scope expansion / contraction, lifecycle gaps, output-format rethinks, persona-lens reframings, cross-persona refactors | absolute SKILL.md path; persona-file paths from the inventory |

**Blindness contract (verbatim — do not paraphrase).** Prepend exactly this string to every dispatch's `prompt`:

```text
Read only what this prompt names. Do not Read any other audit-* skill, the director's draft, or any reference file outside the inputs.
```

Step 9a greps the SKILL.md body for this exact string. When a paraphrase slips in, the grep misses and the audit fails. The fence above keeps the verbatim source visually distinct, so an edit that breaks the grep stands out in review. Without that catch, a slow paraphrase drift in the body could ride into the dispatch unnoticed and sub-agents would lose blindness with no failing test.

Each dispatch prompt names: the absolute SKILL.md path, the auxiliary paths from the table (persona files for orchestration; reference files for cold-walker; the three trigger messages for loader), and one sentence framing the lens. The rules stay in each persona's system prompt rather than the dispatch prompt — a persona's system prompt stays in effect across the whole run, while a user-message rule gets diluted as the conversation grows.

**Measured-routing lane (when Step 2 found a `trigger-evals.json`).** In the same turn as the five dispatches, launch the shared probe runner in the background:

```bash
python3 .github/skills/_shared/run_trigger_evals.py <skill-dir>/trigger-evals.json --workers 4
```

Use `Bash(run_in_background: true)` — 20 queries × 3 runs is a few minutes of wall clock, and it overlaps the readers. Each probe is a fresh `claude -p` whose loader sees the real sibling registry, so the result is a routing *measurement* where the loader-reader's report is a routing *judgment*. Collect the PASS/FAIL table before the Step 5 merge.

**Success criteria:** five `Agent` calls land in one assistant message (one tool-call batch); five reports back (four checklist reports + one ideas menu, which may be `Ideas: none`); the probe table collected when a trigger-evals.json existed.

**Execution:** sub-agents (`Agent` tool, five parallel dispatches), plus one background Bash task for the probes.

**Rules:**
- A sub-agent returning *no findings* is a valid clean lens — accept it.
- A sub-agent that errors gets one re-dispatch with the same prompt.
- A sub-agent return that doesn't carry tier labels (CRITICAL / IMPORTANT / MINOR / AMBIGUOUS) gets one re-dispatch with the framing "tier each finding".
- More than one re-dispatch on the same lens means the prompt is wrong; surface the gap to the user rather than looping.

### 5. Merge findings into a tiered punch-list

For each finding from the four checklist sub-agents (the ideas-reader returns ideas, handled separately below), assign a tier:

- **CRITICAL** — goal not derivable from cold read; core flow wrong for the stated purpose; frontmatter would not route any of the trigger messages (judged, or measured: every positive probe query fails); Done-when missing; a procedure that fires on a tool event (`PreToolUse` / `PostToolUse` / `Stop`) mis-classified as a skill instead of a hook. Any CRITICAL finding defaults the recommendation toward re-author.
- **IMPORTANT** — missing per-step Success criteria on a non-trivial skill, or a Success criterion a clearly-wrong run would still satisfy; a measured routing failure (a positive query whose majority probe routes elsewhere, or a near-miss that routes here); `AskUserQuestion` missing at a clear user-input fork; sub-agent dispatch missing where the work needs cold-walk; AI-tic, defensive-hedging, or moralizing pattern in directives; persona file missing required frontmatter (`name`, `description`); persona tooling that breaks the persona's stated blindness contract.
- **MINOR** — single AI-tic word swap; voodoo constant without explanation; first-person plural in body prose; reference file > 100 lines without a table of contents; could-use-preview suggestion.
- **AMBIGUOUS** — sub-agents partially disagreed (2 / 4 or 3 / 4 agreement; 4 / 4 = clean finding, not AMBIGUOUS); the judgment isn't clearly in scope for the skill being audited; the rule the finding cites is itself a guideline rather than an absolute.

Compare sub-agent findings against the director's Step 3 expected-findings list:

- Items in your expected-findings list that no checklist sub-agent touched become **director follow-up** notes.
- Items in sub-agent findings absent from your expected-findings list are sub-agent finds — keep them in the punch-list at the tier the sub-agent's reasoning warrants; do not downgrade or omit on the basis that you didn't think of them yourself.

Sub-agent findings outrank director observations. On routing specifically, the measured probe table outranks both: when the loader-reader judges a message routable but the probes fail it (or the reverse), the measurement wins and the disagreement rides into the finding text.

**Ideas channel.** The ideas-reader returns up to 5 ideas covering improvements the author probably did not consider: alternative framings, adjacent problems to fold in, harness tools the skill could use but doesn't, scope adjustments, lifecycle gaps, output-format rethinks. The cap keeps the menu short enough that the user can weigh each idea individually in the Step 6 per-idea questions. Ideas do not get tiered — the CRITICAL / IMPORTANT / MINOR / AMBIGUOUS labels describe defects, and an idea is not a defect. The menu prints as a separate block in the Step 6 report. The user decides per-idea whether to apply inline (an Edit on the audited skill, same machinery as Step 8 but on its own per-idea question), discuss first, or skip. Ideas do not file to `plans/next-up.md`; resolve them in this audit.

**Success criteria:** one table with columns TIER · SOURCE (sub-agent or director) · FINDING · ACTION (inline-fix | re-author | human-judgment), plus a separate Ideas block (or `Ideas: none`).

**Rules:**
- The recommendation defaults to **re-author** when ≥ 2 CRITICAL findings land OR when any CRITICAL goal-derivability finding lands. Otherwise the default is **inline-fix**. The user can override either way.
- The director-bias warning is part of the literal output template at the bottom of this file; do not paraphrase it.

### Director's writing discipline — apply before showing any Edit

Steps 6b (idea Apply), 7 (seed paragraph), 8 (inline-fix), and any `AskUserQuestion` option label require YOU to draft prose the user will read. The personas now carry the writing-tone rules in their bodies; you do not by default. Before showing any drafted Edit, summary, or option label:

- **Read aloud.** Read each sentence the way you'd say it out loud to a colleague. If you would not say it to a person, rewrite it. See [`docs/contributing/agent-style-guide.md` § Say it out loud](../../docs/contributing/agent-style-guide.md#say-it-out-loud).
- **Concrete subject, real verb.** Reject your own draft when an abstract noun sits in the subject slot with a weak verb (*"Stance is the triggering-reader's lens"*, *"The win is…"*, *"Its floor is…"*) — find the real actor and let it act. No word-level scan catches this; per-sentence judgment. See [`docs/contributing/agent-style-guide.md` § Concrete subject, real verb](../../docs/contributing/agent-style-guide.md#concrete-subject-real-verb-the-structural-rule).
- **Voice-match.** Re-read 5–10 lines of the audited file's surrounding prose. Your Edit reads like that voice, not like your default — a tight imperative skill body does not want a discursive insert; a discursive body does not want clipped imperative.
- **Articles per noun (the forward-reference test).** Test each *"the X"* — use *"the X"* only when X is an established singular referent the reader already has; *"a X"* / *"an X"* for forward references; bare X for brand names and systems. *"the code fence"* fails when no specific fence was introduced; *"the Pi Pico W"* is decoration (drop the *the*). Inherited *the*s compound across rewrites — re-check per noun. See [`docs/contributing/agent-style-guide.md` § Definite-article tics](../../docs/contributing/agent-style-guide.md#definite-article-tics).

When a swap that would honor these rules reads worse than the original, surface the finding without a proposed Edit and let the user draft the replacement. *Word-soup fixes are regressions, not improvements.*

This discipline applies to YOUR prose, not to findings the sub-agents return — the personas already carry the writing-tone rules. The gap is the director (you) drafting replacement prose, and the four checklist readers cannot judge prose they did not produce.

### 6. Print the punch-list and offer the next action

Step 6 has two sub-steps: 6a prints the report and gates the findings-action, 6b runs the per-idea sequence (only when ideas surfaced). The split exists so a fresh agent can follow each gate without losing track of which AskUserQuestion belongs to which decision.

**Success criteria (parent):** the findings-action gate (6a) ran AND the per-idea sequence (6b) ran or was skipped per the `Ideas: none` clause; the user knows which mode the audit landed in before any Step 7 backup or Step 8 Edit fires.

#### 6a. Print the report and gate the findings next-action

Print the table in the [output format](#output-format) below. Then fire one `AskUserQuestion`. Show the **Route to re-author** option only when the Step 5 recommendation defaults to re-author (≥ 2 CRITICAL findings OR any CRITICAL goal-derivability finding); otherwise show only the inline-fix and report-only options:

> "Findings merged. What next?" `header: Next action`
> Options (conditional, per Step 5 recommendation):
> - "Apply inline fixes" — drills into each non-AMBIGUOUS finding for per-item sign-off (Step 8)
> - "Route to re-author" — only present when Step 5 recommended re-author; routes to Step 7
> - "Print as report only — no action"

**Success criteria:** report printed in chat in the [Output format](#output-format); user picked one of the conditional findings-action options; no filesystem change has occurred yet (Step 7 backup-and-handoff or Step 8 inline-fix runs in response to the picked action).

#### 6b. Per-idea ideas sequence (skip when `Ideas: none`)

When the ideas-reader returned ≥ 1 idea, fire a second `AskUserQuestion` for the Ideas menu (`multiSelect: true`):

> "The ideas-reader proposed N ideas. Pick which to engage with — each picked idea opens a per-idea action question. Unpicked ideas stay in the report only." `header: Ideas`
> Options:
> - One row per idea title (multiSelect; default unchecked)
> - *"Skip all — leave the menu in the report only"*

For each idea the user picked, fire a per-idea follow-up. The action set is conditional on the findings action chosen in 6a. Every per-idea question carries a default recommendation as the first option (with "(Recommended)" appended to the label), so the user is confirming-or-revising rather than picking blank-slate. The default depends on the idea's tag:

- `[WILD]` — recommend *"Discuss inline first"*. WILD ideas have loosened plausibility grounding and benefit most from one round of conversation before any commit. Surface this as a prose note: *"This idea is [WILD] — Discuss inline first recommended."*
- Single-file SKILL.md anchor, kind = harness-affordance or output-shape — recommend *"Apply inline"*. Narrow, well-anchored, the Edit either lands or doesn't.
- Cross-file anchor (`SKILL.md + <persona>`) or kind = scope-adjustment / lifecycle-gap — recommend *"Apply with edits"*. Likely to need user-tuned wording before the Edit lands cleanly across both files.
- Anchor lands in goal-bearing prose (description, opening paragraph, Done-when, or a persona's blindness contract) — recommend *"Discuss inline first"* and pair with the goal-change pushback below.

**When the findings action was *inline-fix* or *report-only*** — ideas Apply produces Edits in place. Before showing the question, parse the idea's `Anchor:` field to determine the **target file(s)** for the Edit: a SKILL.md anchor routes to the audited SKILL.md; a persona-file anchor routes to that persona file; a `SKILL.md + <persona>` anchor routes to both. Re-read every target file before proposing the edit — the file may have shifted since the cold-walk (from earlier per-idea applies or other in-session work):

> "Idea `<title>` — target: `<target-path-or-paths>` — how to handle?" `header: <title>`
> Options:
> - *"Apply inline"* — `Edit` per the idea against the target file(s). The director proposes the exact edit before applying. When the anchor names two files, the user gets one confirmation per file.
> - *"Apply with edits"* — director proposes the edit; user revises wording in plain chat; director applies the revised edit to the target file(s).
> - *"Discuss inline first"* — expand the idea in chat (rationale, tradeoffs, what changes if applied, which file(s) the Edit will touch); re-fire this question after the discussion.
> - *"Skip — leave in the report only"*

**When the findings action was *re-author*** — the skill is about to be rewritten via `/new-skill`, so Apply Edits against the about-to-be-thrown-away file are wasted motion. Ideas inform the rewrite by riding along in the Step 7 seed paragraph instead:

> "Idea `<title>` — how to handle? (Re-author mode: ideas inform the rewrite via the seed paragraph, not via Edits.)" `header: <title>`
> Options:
> - *"Include in `/new-skill` seed paragraph"* — appends a bullet to the seed's *"Ideas to fold into the rewrite"* block (added in Step 7).
> - *"Discuss inline first"* — expand the idea in chat; re-fire this question after the discussion.
> - *"Skip — leave in the report only"*

The Edits-vs-seed split keeps Step 7's backup accurate: in re-author mode no Edits land at Step 6, so the backup folder captures the true pre-rewrite state.

**Goal-change pushback.** When the user picks Apply on an idea whose anchor lands in the SKILL.md description, opening paragraph, or Done-when block — or in a persona's `## Blindness contract` section, required frontmatter (`name`, `description`, `tools`), or the persona's claimed lens declaration — fire a confirmation first: *"This idea touches the skill's stated goal or the persona's load-bearing contract. Confirm intentional change before the Edit lands?"* — Apply waits for the confirmation; Skip / re-frame the idea give the user a way out.

Ideas do **not** feed `plans/next-up.md`. The audit is the place to solve them, not a bullet that rots in a backlog.

**Success criteria:** user worked through the per-idea questions for each picked idea, and each per-idea action either landed an Edit (inline-fix / report-only modes) or was queued for the Step 7 seed paragraph (re-author mode) or was explicitly skipped / discussed; Step 9a's mechanical sweep will run over any Edits that landed during 6b.

### 7. Re-author handoff (only when CRITICAL findings warrant + user approved)

Back up the target before any further action:

```bash
mkdir -p .scratch/skills-backup/skills
cp -r <skill-dir> .scratch/skills-backup/skills/<slug>-$(date -u +%Y%m%dT%H%M%SZ)/
```

Print the seed paragraph for the user to feed to `/new-skill`:

```
Seed for /new-skill <slug>:

Original goal (preserved): <verbatim from the audit target's description / opening>
Triggers (preserved): <three messages — from the description's Examples or salvaged from when_to_use>
Exclusions (preserved): <out-of-scope items the audit target named>
Orchestration intent (preserved or revised): <what sub-agents / parallelism the target tried; revise per CRITICAL findings>
Architecture revisions from CRITICAL findings:
  - <one line per architectural change the re-author should make>
Reason for re-author:
  - <one line per CRITICAL finding>
Ideas to fold into the rewrite (from Step 6 ideas channel):
  - <title> [<kind>] — <one-line summary of what changes if this lands>
  - ...
  (omit this block entirely when no ideas were picked for "Include in seed paragraph")
```

Print the invocation form:

```
Manually invoke when ready:

  /new-skill <slug> <seed-text-above>

The audit target is backed up at .scratch/skills-backup/skills/<slug>-<UTC>/.
Audit-skill does not invoke /new-skill itself — review the seed paragraph above first.
```

**Success criteria:** backup folder exists at the printed path; seed paragraph printed in chat; user told the exact `/new-skill` invocation form and that audit-skill does not auto-invoke.

### 8. Inline-fix mode (only when re-author was NOT chosen)

Git on `main` is the recovery path for inline fixes; no separate backup step.

For each non-AMBIGUOUS finding, fire `AskUserQuestion` (use `multiSelect: true` to batch when ≥ 2 findings share the same action pattern — e.g., AI-tic word swaps can be batched into one multi-select question):

> "Apply this fix?" `header: Fix N`
> Options:
> - "Apply the suggested fix"
> - "Skip — leave as-is"
> - "Edit wording" — when picked, a follow-up free-form prompt collects the user's revision before applying via `Edit`
> - "Explain why this matters first" — surface the persona's rationale (from the finding text, or a one-off re-dispatch asking the persona to expand) before deciding, then re-fire this question with the user's choice

Apply via `Edit`. Re-read the file before any fix that depends on context several lines wide — the file may have shifted from earlier fixes in this same step, or from Step 6's per-idea Apply actions if any landed before Step 8 ran.

AMBIGUOUS findings surface in the same step but are flagged for human judgment, never auto-applied.

**Success criteria:** every non-AMBIGUOUS finding either applied or explicitly skipped; AMBIGUOUS findings flagged for human follow-up.

**Human checkpoint:** every fix is per-finding sign-off — no batched Edits across findings without an explicit multiSelect pick.

### 9. Final validation — re-check the edited skill (only when any Edits landed: Step 6 ideas Apply or Step 8 inline-fix)

Step 6's per-idea Apply and Step 8's inline-fix both apply Edits per the user's sign-off. Each Edit can introduce its own regression: a swap that re-introduces a banned word, a rewrite that drops a Success criteria field, an Edit that broke a markdown link. This step is the safety net, split into a mechanical pass (9a) and a judgment pass (9b).

**Skip clause:** skip all of Step 9 when Step 7 (re-author handoff) was chosen (files weren't edited in place) OR when neither Step 6 ideas Apply nor Step 8 findings Apply produced any Edits (everything was skipped / discussed / sent to report-only).

**Success criteria (parent):** the mechanical sweep (9a) ran on every applicable check AND, when substantive rewrites landed, the originating persona re-dispatched and returned a resolution verdict (9b); any FAIL or unresolved finding is appended to the report as a known-concern or post-edit follow-up tail.

#### 9a. Mechanical sweep — run when any Edits landed (Step 6 ideas, Step 8 findings, or both)

- `description` ≤ 1024 chars; combined with `when_to_use` ≤ 1536 chars (loader contract; restated inline in `audit-skill-loader-reader.md`) — when frontmatter was touched
- AI-tic ban-list grep against the body (regex in `AGENTS.md` § Writing tone, "Standing AI-tic regex")
- Abstract-subject probe — grep `\b(its|the) (win|cost|goal|point|floor|key|trick|catch|upshot|tradeoff|answer|fix|reason|issue|problem) is\b` against the post-Edit body. A hit is a candidate, not a verdict; the structural rule (`docs/contributing/agent-style-guide.md` § Concrete subject, real verb) needs a per-sentence read, not a regex — this probe catches the most common cluster, the rest is judgment
- Every Process step still has a Success criteria field (when the audited skill has > 2 steps)
- Done-when block still distinct from the last Process step
- Every persona file the SKILL.md references exists at `.claude/agents/<name>.md`
- Every reference-file link resolves in the skill directory
- Step 4's blindness-contract verbatim string is still present — grep `Read only what this prompt names. Do not Read any other audit-\* skill, the director's draft, or any reference file outside the inputs.` against the SKILL.md and confirm at least one match. Multiple matches are fine (a stray quote leaking in elsewhere doesn't break the contract check); zero matches means the fence was paraphrased and the contract drifted
- The blindness-contract section in each persona file still matches the SKILL.md fence in spirit — grep `## Blindness contract` against each persona file in `.claude/agents/audit-skill-*.md` and confirm the section restricts the persona to the inputs the dispatch prompt names. The two sources duplicate by design (agents anchor better on inlined rules than on file pointers), but a drift between them surfaces as a known concern, not an auto-fix

Print as a labeled PASS / FAIL block. When one FAIL lands, fire one `AskUserQuestion`: *"Post-edit regression — fix now, or land as a known concern in the report?"*. When ≥ 2 FAILs land, batch them in one `multiSelect: true` AskUserQuestion with a row per FAIL.

**Success criteria:** PASS / FAIL block printed for every applicable check; each FAIL either fixed inline or recorded as a known-concern in the report; the operator knows which mechanical contracts the post-edit body still satisfies.

#### 9b. Targeted re-dispatch — when Step 6b idea Apply or Step 8 fix rewrote a section (not a one-word swap)

Cap each finding at one re-dispatch — the persona's blindness contract is the same on a second pass, so a still-unresolved finding belongs in the post-edit follow-up tail rather than another auto-pass. For each substantive Step 8 fix, re-dispatch the sub-agent reader that originally raised the finding. For each substantive Step 6b idea Apply, re-dispatch the cold-walker instead — the ideas-reader is generative, not a verifier, and the cold-walker already judges AI-tic / hedging / moralizing in body prose. When an idea Apply touched frontmatter rather than body prose, re-dispatch the loader-reader. The dispatch prompt instructs the persona to re-read the file fresh and treat any included prior-finding text as context only, not as anchoring observation. When ≥ 2 fixes need re-dispatch, batch them in one assistant message per the Step 4 batching rule — sequential messages serialize. The reader returns *Confirmed resolved* / *Not resolved* / *New finding surfaced*. New findings append to the original Step 6 report as a *"post-edit follow-up"* tail.

Director-surfaced findings (from the Step 5 follow-up block) have no originating persona — the director re-reads the touched section and confirms *resolved* / *unresolved* inline rather than dispatching.

**Success criteria:** for every substantive rewrite, the originating persona has returned *Confirmed resolved* / *Not resolved* / *New finding surfaced*; new findings appended as a "post-edit follow-up" tail; the operator knows whether the rewrites landed clean.

## Output format

The punch-list, printed in chat at Step 6:

```
audit-skill report — <skill-dir>/<slug>/SKILL.md
================================================

Director draft of skill goal (Step 3):
  <2–3 sentences>

Findings
--------
TIER       | SOURCE                       | FINDING                                     | ACTION
-----------+------------------------------+---------------------------------------------+----------------
CRITICAL   | cold-walker                  | Goal not derivable from cold read.          | re-author
IMPORTANT  | craft                        | AskUserQuestion missing at the Step 3 fork. | inline
IMPORTANT  | orchestration                | Sub-agents dispatched sequentially.         | inline
MINOR      | loader                       | Description carries an AI-tic word.         | inline
AMBIGUOUS  | 2 of 4 sub-agents agree      | Step 7's Success criteria is borderline.    | human-judgment

Director follow-up (sub-agents missed):
  - <one note, or "none">

Director-bias warning: the director read the source and is therefore biased.
Sub-agent findings outrank director observations.

Recommendation: <inline-fix | re-author | report-only>

Ideas to consider (from ideas-reader)
-------------------------------------
  1. <title> [<kind>] [WILD]? — outcome: <pending | applied | edited-applied | included-in-seed | discussed | skipped | not-engaged>
     Anchor: <SKILL.md file:line or section>
     What changes if this lands: <one sentence>

  2. ...

  (or "Ideas: none")

----
Audit run: <UTC stamp from `date -u +%Y-%m-%dT%H:%M:%SZ`> · recommendation: <inline-fix | re-author | report-only>
```

The Ideas block prints once at Step 6 with every entry's outcome set to `pending`. After the user works through the per-idea questions, print a final updated block (only the Ideas section, not the full report) showing the resolved outcomes. `not-engaged` covers ideas the user did not pick in the multiSelect; the others reflect the per-idea action chosen.

The trailing `Audit run:` footer carries the run's timestamp + headline recommendation so a copy-pasted report retains context when it lands in a workstream file, GitHub issue, or chat days later. The recommendation field duplicates the inline `Recommendation:` line deliberately — when the body gets trimmed during paste, the footer survives.

## Companion agents

| Agent | Role | File | Dispatched from step |
|---|---|---|---|
| [`audit-skill-loader-reader`](../../../.claude/agents/audit-skill-loader-reader.md) | Frontmatter contract + description routing | `.claude/agents/audit-skill-loader-reader.md` | Step 4 |
| [`audit-skill-cold-walker`](../../../.claude/agents/audit-skill-cold-walker.md) | Body walkability + goal-derivability | `.claude/agents/audit-skill-cold-walker.md` | Step 4 |
| [`audit-skill-craft-reader`](../../../.claude/agents/audit-skill-craft-reader.md) | Tool-use, scope-expansion, focused-step opportunities, repeated-work-to-bundle | `.claude/agents/audit-skill-craft-reader.md` | Step 4 |
| [`audit-skill-orchestration-reader`](../../../.claude/agents/audit-skill-orchestration-reader.md) | Sub-agent / parallel-dispatch / model-selection / persona structure | `.claude/agents/audit-skill-orchestration-reader.md` | Step 4 |
| [`audit-skill-ideas-reader`](../../../.claude/agents/audit-skill-ideas-reader.md) | Generative menu — improvements the checklists miss, grounded in what the SKILL.md actually says | `.claude/agents/audit-skill-ideas-reader.md` | Step 4 |

Each persona carries its rule set inline (loaded once at session start); the five rule blocks mirror the five lenses in the Step 4 table (loader, cold-walk, craft, orchestration, ideas). When you change a lens here, also update the corresponding persona file. Each persona's blindness contract names the files that persona must not Read. None of the five may Read the director's draft or another audit-* skill.

## Red flags — stop and reconsider

Stop if:

- **The target isn't a SKILL.md.** Redirect at Step 1; do not run the cold-walk on the wrong artifact.
- **The director draft from Step 3 disagrees materially with what the sub-agents found.** Either the director read past a real issue (sub-agents win), or the sub-agents were under-prompted (re-dispatch with the missing input named). Don't paper over the divergence.
- **Three or more CRITICAL findings.** The skill is past the trim-and-rewrite line. Surface re-author rather than inline-fix.
- **The user picks inline-fix on a CRITICAL goal-not-derivable finding.** Re-confirm — the fix won't stick because the underlying scope is wrong.
- **Personas don't exist on disk or aren't loaded into the session registry before Step 4 fires.** Verify `.claude/agents/audit-skill-*.md` are present AND in the live agent registry before dispatching; a freshly-written persona requires a session restart to load. Step 2 owns the recovery prompt (restart vs proceed-with-fewer-readers).

## What to include

- A backup before re-author handoff (Step 7) — `cp -r` to `.scratch/skills-backup/skills/<slug>-<UTC>/` so the operator can diff or restore the pre-rewrite files outside the git history `/new-skill` is about to add to. Inline fixes (Step 8) rely on git.
- The director's own follow-up notes as a trailing block in the report, clearly separated from the sub-agent findings.
- Per-finding sign-off via `AskUserQuestion` for every inline fix, with `multiSelect` batching only when several findings share the same action pattern.
- AskUserQuestion options shown in body prose are sketches. At invocation time, split the short label (≤ 5 words — the chip text) from the description (the prose context). A line like "Prose doc (README / guide.md / INSTALL) — route to `/audit-docs`" maps to `label: "Prose doc"` + `description: "Routes to /audit-docs"`.

## What to leave out

- The five sub-agent rule sets in this body. They live inline in the five persona files in `.claude/agents/audit-skill-*.md`.
- Citations to `/new-skill`, `/audit-comments`, or other audit-* skills as authoritative references. The personas carry their own rules; the body does not restate.
- The `model: "opus"` directive per Agent call. All five persona files set `model: opus` in their frontmatter; the harness uses the persona's frontmatter when `subagent_type:` names one. A body-level `model:` override would be redundant.

## Don'ts

- **Don't dispatch sub-agents sequentially.** Batch all five `Agent` calls into one message — the harness runs concurrent calls from a single message.
- **Don't apply fixes without per-finding user sign-off.** Skill audits are judgment-heavy; one round-trip per `Edit` is cheap insurance.
- **Don't auto-invoke `/new-skill`.** The user reviews the seed paragraph and invokes manually.
- **Don't Read other audit-* skills as references during the audit.** They may be wrong; the personas carry their own rule sets.
- **Don't audit a persona file in isolation.** A persona is bound to its dispatching skill; audit the skill, and the persona is judged in that context.
- **Don't substitute the director's bias for the sub-agents' blindness.** When a sub-agent finding contradicts the director's read, the sub-agent wins.

## Done when

Observable post-state of a completed audit run:

- The tiered punch-list (or the non-skill redirect print) sits in the chat scrollback the user can copy out — with the `Audit run:` footer carrying the timestamp + headline recommendation.
- `git diff .github/skills/<slug>/ .claude/agents/audit-skill-*.md` shows either zero changes (report-only / re-author chosen / no fixes accepted) or the user-approved subset of inline fixes. No Edit went in without per-finding sign-off.
- In re-author mode: `.scratch/skills-backup/skills/<slug>-<UTC>/` exists and contains the pre-rewrite SKILL.md + reference files; the `/new-skill <slug> <seed>` invocation is sitting in chat ready for the user to fire.
- In inline-fix mode where any Edit landed: a Step 9a PASS / FAIL block is in chat, and any FAIL row either has a follow-up Edit or a *known-concern* note appended to the report.
- The Ideas block (when ideas surfaced) shows no `pending` outcomes — every idea is `applied`, `edited-applied`, `included-in-seed`, `discussed`, `skipped`, or `not-engaged`.

A reader scrolling back through this session can answer in one minute: what did the audit find, what did the user accept, what files moved, and what's the next handle.
