---
name: new-skill
description: Authors a new SKILL.md that passes a cold-reader test on first invocation. Use when the user wants to write a new skill, rewrite an existing one from scratch, capture a repeatable session as a skill, build a slash command, or skillify a workflow. Examples: "write a skill that does X", "skillify this", "make this a slash command", "I want a /foo that does Y", "regenerate /<existing> from scratch".
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash(ls *)
  - Bash(grep *)
  - Bash(find *)
  - Bash(python3 *)
  - AskUserQuestion
  - Agent
when_to_use: Use when the user wants to author a new skill, regenerate an existing skill from scratch, capture a repeatable session as a skill, build a slash command, or skillify a workflow — including when the user describes the pattern without using the word "skill", as long as the intent is clearly to capture it for reuse. Trigger phrases include "write a skill", "make a skill that", "skillify", "turn this into a slash command", "I want a /<name> that…", "new skill for", "build a skill", "regenerate /<existing>". Do NOT use to edit an existing SKILL.md in place — that's a normal Edit task; the pre-flight in Step 1a catches slug collisions and routes to the right adjacent path. The interview is the only place vague descriptions get caught — once a SKILL.md lands wrong on disk, every later session that loads it inherits the drift.
argument-hint: "[<slug>] [<free-form context>] [--spec]"
arguments:
  - slug
  - --spec
---

# New Skill

Produce a skill at `<root>/.claude/skills/<slug>/` — the path the Claude Code loader expects.  Some projects (including this one) keep the skill files under `<root>/.github/skills/<slug>/` so they ride with the rest of the GitHub-tooling tree, and symlink `.claude/skills` to it; in that layout, write the new files into `.github/skills/<slug>/` and the loader still finds them via the symlink.  The skill must be one a future agent can invoke cold and execute correctly on the first read.

This skill carries the following references:

- **Correctness rules.** [`spec.md`](spec.md) (root, general author guidance) plus four split files: [`spec-loader-reader.md`](spec-loader-reader.md), [`spec-triggering-reader.md`](spec-triggering-reader.md), [`spec-sibling-author.md`](spec-sibling-author.md) — each mirrors one cold-walk persona — and [`spec-orchestration.md`](spec-orchestration.md) (sub-agent dispatch patterns).
- **Deep interview.** [`interview.md`](interview.md).
- **Starter skeleton.** [`template.md`](template.md).
- **Worked walkthrough.** [`examples.md`](examples.md).
- **Test-plan skeleton.** [`testplan.md`](testplan.md) — the layered TESTPLAN.md a driver-backed skill ships with, and the row-discipline rules (every row discriminates; every row runnable from the file alone).

## Clean-slate rule

While authoring a new skill, you (the agent driving `/new-skill`) do not Read any other SKILL.md, persona file, or reference file in the tree. The one exception lives in Step 1b: the sibling-overlap scan reads only the `description:` line of each sibling — routing metadata, not body prose.

Existing skills carry drift the new skill is meant to escape. Reading even a small slice — *"just to see the pattern"* — paraphrases that drift into the draft. The four cold-walk sub-agents in Step 5 enforce the same rule on themselves; their personas in `.claude/agents/` name exactly what each one may read.

The slug-collision check (Step 1a) stops and asks how to proceed when a SKILL.md already exists at the chosen slug. Auditing an existing skill and authoring a new one are different jobs.

The skill being authored has two parts that live together:

```
<root>/.claude/skills/<slug>/
  SKILL.md      ← agent-facing instructions. SHORT. Points at the references.
  interview.md  ← (optional) deep question bank
  spec.md       ← (optional) rules / criteria the skill enforces (split into
                  spec-loader-reader.md / spec-triggering-reader.md /
                  spec-sibling-author.md when one file grows past the
                  splitting threshold and the personas mirror it)
  template.md   ← (optional) starter skeleton the skill emits
  examples.md   ← (optional) one or two worked walkthroughs
  scripts/      ← (optional) bundled scripts; entry points named per their job
                  (driver.<ext> / smoke.sh / validate.py / etc.)
```

When the success criterion is *"the app started and a page rendered,"* a markdown file by itself cannot click a button. Build the driver now and commit it alongside the SKILL.md.

## Definition of done

You are done when all of these are true:

1. **The frontmatter passes the loader test.** The `description:` line in isolation routes the three example user messages from Phase 1 — verbs match, scope matches, *when* is named.
2. **Every step in the Process that warrants it has a Success criteria field.** *"Do X and confirm `<observable artifact>`,"* not *"do X."* Required when the skill has more than two steps or any step has a non-obvious success state.
3. **The body has a Done-when block** that an agent reading cold can use to stop. Vague exit conditions are the dominant failure mode of agent-invoked skills.
4. **Every reference file the SKILL.md links to exists** on disk. One-hop nesting only.
5. **Four sub-agents walked the draft cold** (loader, triggering, sibling-author, ideas). The first three return findings; the gaps they raised were fixed before write. The fourth returns a curated ideas menu; the user picked which (if any) to fold in.
6. **If the skill needs a driver,** the script exists, you ran it in this session, and the SKILL.md documents the invocation.
7. **Every code block in the generated SKILL.md is a command you ran this session and saw succeed.** Not from the README, not inferred. Setup commands carry the version that worked.
8. **Routing is measured, not just judged.** `trigger-evals.json` (Phase 1's positives + near-misses) sits next to the SKILL.md, and at the full-lifecycle tier the Step 8b probe run printed its PASS/FAIL table. A skill that bundles scripts also ships a TESTPLAN.md per [`testplan.md`](testplan.md).

When (1) or (3) is missing at write time, stop. Run the interview from `interview.md` until they land.

## Process

### 0. Decide mode

Three modes: interview (default), spec-in (`--spec`), and slug-plus-context (slug followed by free-form text).

```
/new-skill                            → interview, slug derived from trigger
/new-skill <slug>                     → interview, slug candidate locked
/new-skill <slug> <free-form text>    → slug-plus-context: slug locked, text
                                         seeded as a mini-spec for the interview
/new-skill --spec                     → spec-in, ask for a paragraph
```

Slug-plus-context parsing rules:

- The first whitespace-delimited token is the slug (validate against the rules in [`spec-loader-reader.md` § `name`](spec-loader-reader.md#name)).
- Everything after the first token is the trailing context.
- Parse the trailing context for goal sentences (→ procedure-form candidates, fed to interview Phase 6), trigger-style phrases like *"should be able to X"* or *"want to Y"* (→ trigger-message candidates, fed to Phase 1), out-of-scope statements (→ scope-exclusion candidates, fed to Phase 2), architecture hints — sub-agents, director, parallel (→ flagged for the agent-architecture branch in Phase 6b, which fires only when Phase 6 picks a multi-agent procedure form), and quality asks (*"go the extra mile"* → flagged for the vocabulary-sourcing pass in Phase 9).
- Reference / source material (*"using X as reference"*) is an author hint for you. Never carry it into the produced SKILL.md body.
- Print the parsed seeds to the user as a structured pre-fill before the interview opens — grouped by category (trigger-message candidates, scope-exclusion candidates, procedure-form candidates, architecture hints, quality asks). Then fire a `multiSelect` `AskUserQuestion`: *"Which seed categories do you accept as-is? Un-picked categories get revisited at their phase."* Options: one entry per non-empty parsed category. When zero categories parsed cleanly, skip the question and open the interview from Phase 0 normally.

#### Pre-fill ≠ skip

Rich trailing context makes each phase faster. It does not skip a phase. Every phase the complexity table (Step 2) calls for still fires its `AskUserQuestion`. Pre-filled candidates only change the question's form: *"Confirm or revise this draft"* instead of *"What would you like?"*.

The interview's job is sourcing, not just elicitation — Phase 7 traces success-criteria vocabulary to a source; Phase 9 traces every label, tier, verdict, severity scale, finding-type name. Skipping these phases on the strength of the brief is how unsourced training-data vocabulary leaks into the draft.

For each phase, fire its question even when the seed pre-fills the answer. Options become: *"Accept the pre-fill as drafted"* | *"Edit"* | *"Reject — re-draft from scratch"*.

**Success criteria:** mode named, slug captured (or `none yet`), trailing context parsed and confirmed when any was provided. No phase silently skipped.

### 1. Pre-flight — slug-collision and sibling survey

**1a. Does a SKILL.md already exist at the candidate slug?**

```bash
ls .github/skills/<slug>/SKILL.md 2>/dev/null || ls .claude/skills/<slug>/SKILL.md 2>/dev/null
```

When a file exists, stop and ask the user how to proceed. `/new-skill` is a clean-slate generator; reading the existing file would bias the new draft. Fire an `AskUserQuestion` with:

- *Audit the existing file with `/audit-skill <slug>` and improve in place*
- *Move the existing file to `<path>.bak` outside the `*/skills/*` tree (so the loader does not pick it up) and re-invoke `/new-skill <slug>`*
- *Delete the existing file outright and re-invoke*

Do not Read the existing file.

**1b. Survey sibling descriptions.**

List every existing skill's `description:` line — the new one will be checked against the loader's view of them:

```bash
find . -path '*/skills/*/SKILL.md' -not -path '*/node_modules/*' \
  -exec grep -H -m1 '^description:' {} \;
```

Hold this list. It feeds Phase 5 of the interview and the sibling-author cold-walk in Step 5. Reading description lines only is fine; the bias risk lives in body prose.

**Success criteria:** no SKILL.md at the candidate slug; a printed list of `<path>: description: …` lines covers every other skill in the tree.

### 2. Run the interview

Direct execution. Pick the widget per artifact:

| Artifact the question gathers | Widget |
|---|---|
| One path from a known set of choices | `AskUserQuestion` single-pick |
| Subset of M items from a finite K of predefined items | `AskUserQuestion` with `multiSelect: true` |
| Free-text content the user types (list, paragraph, code) | Plain chat, optionally gated by a one-pick *"ready to type, or show examples first?"* |

Free-text artifacts (three trigger messages, a multi-step walk, a description paragraph) do not belong in `AskUserQuestion` options — single-select reads the options as the universe of choices. Use plain chat.

Read [`interview.md`](interview.md) in full before opening the first question. Walk phases in the order the complexity table below calls for; don't skim, don't skip a phase the table fires. The intro + widget-selection table + **Pushback patterns** at the top of `interview.md` are **load-bearing for every phase** — re-reference them whenever you're driving a question, not only at the start.

If context fills up mid-interview, re-extract on demand:

```bash
# A single phase (replace 2/3 with the actual numbers; for Phase 11 use /^## Appendix:/ as the end anchor)
awk '/^## Phase 2:/,/^## Phase 3:/' .github/skills/new-skill/interview.md

# The framing block (intro + widget table + Pushback patterns)
awk '/^# Interview/,/^## Phase 0:/' .github/skills/new-skill/interview.md
```

Each phase opens 1–4 questions. For single-pick and multi-select, present 2–4 substantive options; the user's "Other" escape is always available and is where the interesting answers usually land. Lay out alternatives at every fork.

Match interview depth to skill complexity. After Phase 2 (scope) and Phase 6 (procedure form) land, draft an inferred tier from the table below — then fire an `AskUserQuestion` confirming or revising it:

| Skill complexity | Phases to run |
|---|---|
| Two-step trivial (*"run `npm test` and report exit code"*) | 0, 1, 4, 7 (light), 11. One Done-when block covers it; skip per-step annotations. Phase 6.5 not offered at this tier. |
| Three-to-five steps, no fork, no driver | 0, 1, 2, 4, 5, 7, 8, 10, 11. Skip 3 (default inline), 6 (default prose), 9 (no absolutes to trace). Phase 6.5 optional via its in-phase opt-in gate. |
| Full lifecycle (fork, driver, multi-step, citations) | All 11 phases + Phase 6.5 (stretch-angles, default-on at this tier). |

> *"Based on the scope and procedure form, this looks like a `<tier>` skill — fire phases `<list>`. Confirm or upgrade / downgrade."* `header: Interview depth`
> Options:
> - *"Confirm — fire the inferred tier"*
> - *"Upgrade to the next tier (more phases)"*
> - *"Downgrade to the previous tier (fewer phases)"*
> - *"Walk all eleven — I want maximum coverage"*

When in doubt, walk all eleven — the user can short-circuit by typing *"that's enough — write it."*

Push back when answers are vague. Two rounds of pushback is normal; four is fine; ten means the user does not yet know what the skill is. At that point offer to stop the interview and resume after they have done the work in a real session. The full pushback table lives in [`interview.md` § Pushback patterns](interview.md#pushback-patterns).

Rules:
- Never write the SKILL.md to disk during the interview. Hold the draft in chat.
- Lay out alternatives at every fork. *"Here are two ways to draw this scope: (A) only X, (B) X and Y. Which?"*
- When two phases produce contradicting artifacts (Phase 1 trigger does not match Phase 2 scope), call it out and re-run the earlier phase.

**Success criteria:** every phase the complexity table called for is closed with its artifact captured. Artifacts: the slug, the candidate `description:`, three example user messages, an in-scope / out-of-scope list, a procedure outline with per-step success criteria, the arguments list, the `allowed-tools` list, the context decision (inline vs fork), citation pointers for any absolute rules.

### 3. Draft frontmatter, then body

Order matters. The `description:` is what the loader matches against user messages, so it earns the most scrutiny. Draft it first, run the trigger-match test against the three example user messages from Phase 1, iterate, *then* fill in the body.

Use [`template.md`](template.md) as the starter skeleton. Use [`spec-loader-reader.md` § Frontmatter contract](spec-loader-reader.md#frontmatter-contract) as the reference for every field, the validation caps (1024 hard / 1536 combined), and the dynamic-context-injection syntax. Use [`spec-loader-reader.md` § String substitutions](spec-loader-reader.md#string-substitutions) for `$ARGUMENTS`, `$<name>`, `${CLAUDE_SKILL_DIR}`, and friends.

**Success criteria:** YAML frontmatter parses and every field satisfies the rules in [`spec-loader-reader.md` § Frontmatter contract](spec-loader-reader.md#frontmatter-contract); description routes the three example user messages from Phase 1; combined `description` + `when_to_use` ≤ 1,536 chars; body has a Process section with per-step Success criteria; body has a Done-when block.

### 4. Annotate Process steps

Per-step annotation discipline. Success criteria is required on every step when the skill has more than two steps or any step has a non-obvious success state. A trivial two-step skill gets a Done-when block instead. The rest of the annotations are conditional:

| Annotation | When to include |
|---|---|
| **Success criteria** | Every step. Observable artifact or assertion that proves the step is done. |
| **Execution** | Only when not Direct. Values: `Task agent`, `Teammate`, `[human]`. |
| **Artifacts** | When a later step needs data this step produces (PR number, commit SHA, file path). |
| **Human checkpoint** | For irreversible actions (merging, sending messages), error judgment (merge conflicts), or output review. |
| **Rules** | Hard rules for the workflow. User corrections during the interview are especially load-bearing here. |

**Success criteria:** every step has a Success criteria field; no step has narration without a verifiable outcome.

### 5. Cold-walk via four sub-agents in parallel

You cannot do the cold-walk alone. By Step 5 you have read the user's interview answers, drafted the description, and written every Process step. Your *"this looks fine"* is unreliable — you know what the skill is *supposed* to do, so you fill the gaps the draft leaves. The cold-walk exists exactly because of that bias.

The step splits into 5a (dispatch + consolidate, blind) and 5b (per-finding sign-off + apply, where your context is useful again — every fix goes through the user).

#### 5a. Dispatch + consolidate

Dispatch four sub-agents in **one message** (the harness runs concurrent `Agent` calls from a single message; sequential messages serialize). Each persona file in `.claude/agents/` already carries its blindness contract, the full inline rule set it judges against, and the output format — the personas do not Read the spec files at dispatch time (the rules they enforce are mirrored into the persona body from the matching `spec-*.md`, with a *Source of truth* pointer at the top). Your dispatch prompt names only the per-invocation inputs.

Three of the four readers enforce closed checklists and return findings. The fourth (`new-skill-ideas-reader`) is generative — it returns a curated menu of up to 5 improvements the author probably did not consider. Ideas are **not findings**: they don't get tiered (CRITICAL / IMPORTANT / MINOR / AMBIGUOUS describe defects), they don't gate sign-off, and they surface in a separate block of the Step 7 summary. The user decides per-idea whether to fold in, discuss inline first, or skip. Ideas do **not** get filed to `plans/next-up.md` — the interview is the place to solve them, not a bullet that rots.

| Sub-agent | What it judges (full rules inline in the persona body) | Per-invocation inputs |
|---|---|---|
| [`new-skill-loader-reader`](../../../.claude/agents/new-skill-loader-reader.md) | Per-message routing (incl. near-miss probe); description-text quality; name + when_to_use rules | Absolute path to the SKILL.md, the three example user messages, the Phase 1 near-misses with expected routes |
| [`new-skill-triggering-reader`](../../../.claude/agents/new-skill-triggering-reader.md) | Body length / section ordering / walkability; per-step Success criteria; frontmatter-vs-body consistency; patterns-to-avoid; stance | Absolute path to the SKILL.md |
| [`new-skill-sibling-author`](../../../.claude/agents/new-skill-sibling-author.md) | Trigger overlap; restated content from siblings or spec; reading-rule violations; reference-file layout; MCP tool naming | Absolute path to the SKILL.md, the sibling `<path>: description: …` list from Step 1b |
| [`new-skill-ideas-reader`](../../../.claude/agents/new-skill-ideas-reader.md) | Generative menu — alternative framings, adjacent problems to fold in, harness affordances not reached for, scope expansion / contraction, lifecycle gaps, output-shape rethinks, persona-lens reframings, cross-persona refactors | Absolute path to the SKILL.md, absolute paths to every custom persona file the draft dispatches |

Prepend this preamble to every dispatch prompt:

> Do not Read any other skill file, persona file, or reference file beyond what this prompt names. Sibling descriptions in your session-start metadata are fine; opening the bodies is not.

Consolidate the four reports into one block — three checklist readers fill the findings table; the ideas-reader fills the Ideas menu underneath:

```
Cold-walk results for <skill-dir>/<slug>/SKILL.md
=================================================

Findings (from the three checklist readers)
-------------------------------------------
Reader               | Findings
---------------------+----------------------------------------------
Loader               | <one row, or "none">
Triggering           | <one row, or "none">
Sibling-author       | <one row, or "none">

Ideas to consider (from ideas-reader)
-------------------------------------
  1. <title> [<kind>] — <anchor>
     <what changes if this lands, one sentence>
  2. ...
  (or "Ideas: none")
```

Your job at 5a is dispatch and consolidate, **not** judge or apply. When you noticed something the sub-agents missed, mention it as a single follow-up note — but the sub-agents' findings outrank yours. Don't substitute your bias for their blindness.

**Success criteria for 5a:** four sub-agents dispatched in one parallel message; four reports received; consolidated block printed with the findings table and the Ideas menu (which may be `Ideas: none`). When all three checklist sub-agents independently returned `none` AND the ideas-reader returned `Ideas: none`, skip 5b and proceed to Step 6. When only the checklist readers returned `none` but ideas surfaced, still skip the findings part of 5b but route the ideas through the per-idea sign-off described below.

#### 5b. Per-finding sign-off and fix application

Walk findings one at a time. For each non-AMBIGUOUS finding, fire `AskUserQuestion`:

> *"Finding: `<one-line summary>` (from `<reader>`). Apply?"* `header: Fix N`
> Options:
> - *"Apply the proposed fix"*
> - *"Apply with edits — I'll revise the wording"*
> - *"Skip — leave as-is"*
> - *"Explain why this matters first"* — then surface the persona's rationale, re-fire the question

When several findings share the same action pattern (e.g., multiple AI-tic word swaps from one reader), batch them into a single `multiSelect` question.

AMBIGUOUS findings surface in the same loop but never auto-apply — the option set is *"Apply (treat as IMPORTANT)"* / *"Skip"* / *"Park as a known concern for the report"*.

Your context from the interview (user intent, the conversation arc, why each paragraph reads the way it does) is the right input for proposing fix wording — that's where the director's context earns its keep. The bias check is per-finding user sign-off, not removal of the director from the loop.

When a finding rests on a documented-Claude-Code-behavior assertion — a frontmatter field's support status, a cap value, loader or tool semantics — verify it via the `claude-code-guide` agent (with a doc URL) before proposing the fix. The spec files snapshot the docs and lag the product; a contradicted rule means the fix is to `spec-loader-reader.md` and its mirroring persona, not to the draft.

Apply via `Edit` to the in-memory draft. Drafts live in the chat context until Step 8.

**Ideas channel — separate from the per-finding sign-off.** When the ideas-reader returned ≥ 1 idea, walk the menu after the findings loop closes. Fire one `AskUserQuestion` with `multiSelect: true`:

> *"The ideas-reader proposed N ideas. Fold any in before write?"* `header: Ideas`
> Options:
> - One row per idea title (multiSelect; pre-checked = none).
> - *"Skip all — leave ideas in the report only"* (radio-equivalent: when picked alone, no ideas are folded in).

For each picked idea, parse the `Anchor:` field to determine the **target file(s)** for the Edit: a SKILL.md anchor routes to the in-memory draft; a persona-file anchor routes to that persona file's in-memory draft (when authored in this session via Phase 6b) or its on-disk version (when pre-existing); a `SKILL.md + <persona>` anchor routes to both. When the idea title carries the `[WILD]` tag (the ideas-reader's wild-pass quota), the per-idea question should default-recommend *"Discuss inline first"* — WILD ideas have loosened plausibility grounding and benefit most from one round of conversation before any commit. Surface this in the question as a prose note: *"This idea is [WILD] — Discuss inline first recommended."* Then fire the per-idea question:

> *"Idea `<title>` — target: `<target-path-or-paths>` — how to handle?"* `header: <title>`
> Options:
> - *"Apply as-drafted"* — Edit the target file(s) per the idea. When the anchor names two files, the user gets one confirmation per file.
> - *"Apply with edits — I'll revise the wording"* — capture revision via plain chat, then Edit the target file(s).
> - *"Discuss inline first"* — expand the idea in chat (rationale, tradeoffs, what changes if applied, which file(s) the Edit will touch); re-fire this question after the discussion.
> - *"Skip — leave in the report only"*

Ideas never gate write. Unselected and skipped ideas surface in the Step 7 report as a read-only menu.

**Stance check, before declaring 5b done.** A SKILL.md is read by an agent mid-task — write to a capable practitioner, not a beginner. Re-read for defensive hedging (*"should usually work"*), moralizing (*"be careful when…"*), apologetic scope notes, step-by-step narration of self-evident agent actions, over-cautious checkpointing on routine steps. Mechanical sweeps miss these; the cold read catches them. Each stance hit goes through the same per-finding `AskUserQuestion` loop — propose a fix, the user signs off.

**Success criteria for 5b:** every non-AMBIGUOUS finding has an outcome (applied / applied-with-edits / skipped); AMBIGUOUS findings either landed in the report-as-known-concern bucket or were promoted to IMPORTANT with the user's call; stance check has surfaced any hits through the same per-finding sign-off loop.

### 6. Final validation — re-check the post-edit draft against spec

Step 5b applied fixes the cold-walk surfaced. Each fix can introduce its own regression: a swap that re-introduces a banned word, a rewrite that drops a Success criteria field, an Edit that broke a markdown link. This step is the safety net — a lightweight mechanical sweep, plus targeted re-dispatch when 5b rewrote a section substantively. Patterns-to-avoid are *not* re-checked here — the triggering-reader covered that list in 5a, so re-checking in 6 would be the biased director redoing the cold-walk's work.

**Skip clause:** when Step 5a returned no findings (so 5b applied no fixes), skip Step 6 — there's nothing to revalidate. Proceed to Step 7.

**Mechanical sweep — always run when 5b applied fixes.**

- `description` ≤ 1024 chars; `description` + `when_to_use` combined ≤ 1536 chars
- AI-tic ban-list grep against the body (regex from [`spec-triggering-reader.md` § Patterns to avoid](spec-triggering-reader.md#patterns-to-avoid))
- Every Process step has a Success criteria field (when the skill has > 2 steps)
- Done-when block exists and is distinct from the last Process step
- Every `allowed-tools` entry is invoked by some Process step
- Every persona file the body references exists at `.claude/agents/<name>.md`
- Every reference-file link (`[<file>](<file>.md)`) resolves in the skill directory
- The trigger-evals draft parses and carries ≥ 3 positive and ≥ 3 near-miss queries, each near-miss with an `expected_route`

Print the sweep results as a labeled PASS / FAIL block. For any FAIL, route back to Step 5b's per-finding sign-off loop with the regression as a new finding.

**Targeted re-dispatch — only when 5b rewrote a section (not a one-word swap).**

For each substantive 5b fix, re-dispatch the persona that originally flagged the finding with the post-edit draft + the original finding text. The persona returns one of:

- *Confirmed resolved* — drop the finding
- *Not resolved* — route back to 5b for another pass
- *New finding surfaced* — add to 5b's queue, loop the sign-off

Cap at one re-dispatch per finding to avoid infinite ping-pong. When a finding still doesn't resolve after one round, surface as *"known concern — ship anyway?"* in Step 7's sign-off.

**Success criteria:** mechanical sweep printed; any FAIL routed back to 5b or surfaced as a known concern; targeted re-dispatch results (when run) consolidated; draft ready for Step 7 sign-off.

### 7. Print a structured summary, get sign-off

Do not dump the full SKILL.md or reference files into chat. For any reasonable size the dump is hundreds of lines the user cannot review in scrollback. Print a compact summary the user can scan in seconds, then ask for sign-off. The user reads the actual files from disk after the write.

Print this summary as plain text:

```
Proposed skill: <skill-dir>/<slug>/

Files to write
--------------
<path>                                <line count>  <one-line purpose>
<path>                                <line count>  <one-line purpose>
...

Frontmatter
-----------
name:        <slug>
description: <first ~120 chars of description line>...
allowed-tools: <comma-separated list>
context:     <inline | fork>

Procedure sections
------------------
1. <Step 1 name> — Success: <criterion>
2. <Step 2 name> — Success: <criterion>
...

Done when: <one-line summary of the Done-when block>

Cold-walk results (from Step 5)
-------------------------------
Loader         | <finding | none>
Triggering     | <finding | none>
Sibling-author | <finding | none>

Ideas to consider (from ideas-reader)
-------------------------------------
  1. <title> [<kind>] [WILD]? — applied | edited | discussed | skipped
  2. ...
  (or "Ideas: none")
```

Then fire a single `AskUserQuestion`:

> *"Save these files? (You'll review them from disk after the write.)"* `header: Save?`
> Options:
> - *"Yes — write to disk"*
> - *"Show me one or more files inline before writing"*
> - *"Edit one or more files"*
> - *"Discard — start over"*

When the user picks *Show* or *Edit*, fire a follow-up `AskUserQuestion` with `multiSelect: true` listing each candidate file by name (SKILL.md, each reference file, each persona file) — the file inventory is right there in the structured summary above.  For *Show*: print each selected file as a fenced code block, then re-fire the Save question.  For *Edit*: for each selected file, capture the revised content via plain chat, update the in-memory draft, then re-fire the Save question.

**Human checkpoint:** the user signs off on the summary. Full file content lives on disk for editor review, not in the chat scrollback.

**Success criteria:** structured summary printed; `AskUserQuestion` answered with *yes* / *edit* / *discard*. No file-content dump in chat unless the user explicitly asked for one.

### 8. Write the files

Create the directory and write the files at the agreed paths. Multi-file output is the norm:

| Output file | When written | Path |
|---|---|---|
| `SKILL.md` | Always | `<skill-dir>/<slug>/SKILL.md` |
| `trigger-evals.json` | Always (Phase 1's positives + near-misses, regen-comments schema: `skill_name`, `evals: [{query, should_trigger, expected_route?}]`) | Next to `SKILL.md` |
| `TESTPLAN.md` | When the skill bundles scripts or a driver — layered per [`testplan.md`](testplan.md) | Next to `SKILL.md` |
| Reference files (`interview.md`, `spec.md`, `template.md`, `examples.md`, …) | When the SKILL.md links to them | Next to `SKILL.md` (one hop deep) |
| Bundled scripts | When Phase 6 specified one or more | `<skill-dir>/<slug>/scripts/<entry>.<ext>` |
| Custom agent persona files | When the interview's agent-architecture branch (Phase 6b) authored new personas | `.claude/agents/<agent-name>.md` — at the repo root, not inside the skill directory |

Agent files live alongside other agents (`.claude/agents/`), not inside the skill that dispatches them. The skill body cites them by `subagent_type` name; the harness loads them from `.claude/agents/` at dispatch time.

**Success criteria:** every file in the agreed plan exists at the agreed path; `ls <skill-dir>` shows the SKILL.md + reference files; `ls .claude/agents/<agent-name>.md` confirms each new persona. No agent file the SKILL.md references is missing from `.claude/agents/`.

### 8b. Measure routing (full-lifecycle tier; offer at lower tiers)

The cold-walk *judged* routing; this step *measures* it. The probes need the file on disk — each one is a fresh `claude -p` from the repo root whose loader sees the new skill competing against every sibling description, which is what production routing actually is.

```bash
python3 .github/skills/_shared/run_trigger_evals.py <skill-dir>/<slug>/trigger-evals.json --workers 4
```

Roughly 15–60 s per probe; 8 queries × 3 runs at 4 workers lands in a few minutes. Tell the user it's running, then read the table. For each FAIL: a positive query routing elsewhere means the description is under-pushy for that phrasing — revise the `description` / `when_to_use`, re-run the failed rows (`--limit` after reordering, or the full set), and show the user the before/after. A near-miss routing here means over-pushy — same loop. A FAIL the user decides to accept (the query was unrealistic, the overlap is intentional) gets that reason said aloud, not silence.

**Success criteria:** the probe table printed with a PASS/FAIL row per query; every FAIL either resolved by a description revision + re-run or explicitly accepted by the user with a stated reason.

### 9. Tell the user what to do next

Print a compact closing block — paths to read, invocation form, the next action:

```
Skill written
=============
  <skill-dir>/<slug>/SKILL.md                  <line count>
  <skill-dir>/<slug>/<ref-file>.md             <line count>   (if any reference files)
  .claude/agents/<agent-1>.md                  <line count>   (if any new agent personas)

Invoke as: /<slug> [<args>]

Next:
  - Open the files above in your editor to review.
  - Edit directly to refine — no need to re-run /new-skill for small tweaks.
  - For a structural rewrite, run /audit-skill <slug> first; if the audit
    recommends regeneration, the audit guides that decision.
```

**Success criteria:** paths + invocation form printed.

## Project-type patterns

| Skill type | Body structure | Frontmatter notes |
|---|---|---|
| Procedural (audit, scan, lint) | Scope → Dimensions/Checks → Procedure → Output format | Often `context: inline` so the user can steer mid-pass |
| Generation / interview (this skill, `/new-decision`, `/init`) | Process → per-step annotations → cold-walk → write | `AskUserQuestion` in `allowed-tools` |
| Action / driver-backed (run, deploy, verify) | Definition of done → Process → Driver invocation → Gotchas → Troubleshooting | `Bash(<command> *)` patterns in `allowed-tools`; driver file committed next to SKILL.md |
| Reference / cookbook (patterns docs, design guides) | Tables of when-to-use / what-to-expect | Often `disable-model-invocation: true` so they load on demand by topic, not by trigger |

Pick the structure matching the new skill's job.

## Driver graduation

A driver script lives next to the SKILL.md by default — `driver.mjs`, `smoke.sh`, `probe.py`. When a second consumer wants the helpers — the project's own test suite, another tool — move the driver to `scripts/` or `e2e/` and update the SKILL.md to reference the new path. The skill stays put; the driver finds a better home.

## Fork-mode briefing

When the new skill sets `context: fork`, the sub-agent starts cold — no conversation history, no shared state. The skill body briefs the fork the way you would brief a smart colleague who just walked into the room: the goal, the inputs, what is already known or ruled out, the exact form of the expected output. Terse command-style instructions produce shallow work in a fork. Inline (default) skills can rely on the surrounding conversation; fork skills cannot.

## What to include

- Frontmatter with verbs the user would actually type in the `description`.
- A Process section with numbered steps and one Success criterion per step.
- A Done-when block the agent uses to stop.
- One worked invocation example showing what the skill does end-to-end.
- Output format (text or table) when the skill produces structured output.
- Driver / harness code committed in the skill directory when the skill needs to run code, not just guide.

## What to leave out

- Anything the skill does not do. Aspirational scope rots into wrong instructions within a release.
- Generic troubleshooting (*"if the build fails, check your Node version"*). Only include errors you actually hit while writing the skill.
- Architecture prose. That belongs in other docs.
- Exhaustive options. Prescribe one path; alternatives are noise to the agent reading mid-task.
- History / changelog narration (*"previously this skill did X"*). The commit log carries history; the SKILL.md describes current behavior.

## Red flags — stop and reconsider

Stop if:

- You wrote the SKILL.md before completing the interview. A draft on disk during interviewing is a draft you stop pushing back on.
- The description starts with a vague stem. *"Tools for…"*, *"Helps with…"*, *"Utilities for…"*. Loader will not route it.
- You restated a sibling skill's content in the new body (re-inlining commit mechanics, copying another skill's cold-walk checklist) instead of citing or extending. The sibling-author cold-walker will flag it.
- The Process has steps without Success criteria. The agent will declare done mid-step.
- Two phases of the interview produced contradicting artifacts and you papered over it. The contradiction lands on first real invocation.
- The Done-when block matches Process step N. That is not a Done-when; it is just the last step. A real Done-when names the observable end-state, not the last action.
- You skipped the cold-walk because the draft "reads fine." Authors cannot read their own drafts cold.
- The skill needs a driver and you did not write one. *"An agent could figure out how to launch this"* is the README's job. The skill's job is to make it certain.
- The interview produced no pushback. Either the user was unusually concrete or you accepted a vague answer. Re-read Phase 1's trigger messages and Phase 7's success criteria — when either reads abstract, the interview ran too shallow.
- Everything in the produced SKILL.md worked first try. Either the skill is trivial or you copied commands without running them. Real Gotchas sections carry the specific weird errors that real execution produced.

## Don'ts

- Don't auto-write before sign-off. The Human checkpoint at Step 7 is load-bearing.
- Don't accept *"always do X"* rules without an incident trail. Trace to an ADR, prior failure, or three observations — or soften to a guideline.
- Don't dump shell output inside the body when dynamic-context injection would do it cleaner. The supported form runs the command at load time and substitutes the output. The literal syntax lives in [`spec-loader-reader.md` § Dynamic context injection](spec-loader-reader.md#dynamic-context-injection--bangcommand). Use deliberately — the command runs every time the skill is invoked.
- Don't expand scope mid-interview. When a deeper need lands (*"we also want it to write libraries"*), file as a follow-up — finish the current skill first.
- Don't treat the patterns-to-avoid list as a search-and-replace. A pattern's appearance means the surrounding sentence needs different content — not that a word swap will fix it. Read the line aloud and write what you would actually say.
- Don't use Windows-style paths. Forward slashes always (`scripts/helper.py`). Windows paths break on Unix.
- Don't enumerate every option. Give a default with one escape hatch. *"You can use A or B or C or D…"* creates decision paralysis for the agent invoking the skill.
- Don't write descriptions in first or second person. *"I can help you process Excel files"* and *"You can use this to…"* break loader matching. Use third person.

## Done when

- `<skill-dir>/SKILL.md` exists with the agreed frontmatter and body.
- Every reference file the SKILL.md links to exists on disk.
- Every custom agent persona the SKILL.md references exists at `.claude/agents/<name>.md`, either confirmed pre-existing or authored during the interview's agent-architecture branch (Phase 6b).
- For each authored agent: frontmatter (`name`, `description`, plus opt-in fields) is complete; body is second-person with no narrative preamble; the persona names the blindness contract when the agent is a verifier.
- `name` ≤ 64 chars, lowercase + digits + hyphens, not `anthropic` or `claude`.
- `description` ≤ 1024 chars (hard validation cap). Written in third person.
- The `description:` line, read in isolation, would route the three example user messages from Phase 1.
- `trigger-evals.json` sits next to the SKILL.md with Phase 1's positives and near-misses; at the full-lifecycle tier, the Step 8b probe table is in the chat scrollback with every FAIL resolved or user-accepted.
- When the skill bundles scripts or a driver, TESTPLAN.md exists per [`testplan.md`](testplan.md) — every row discriminating and runnable from the file alone.
- Every Process step carries a Success criteria field (or the skill is a two-step trivial one with a Done-when block only).
- The body carries a Done-when block distinct from the last Process step.
- When the skill uses a director pattern, the body carries the director-bias warning (sub-agent findings outrank director observations).
- The user has been told the invocation form (`/<slug>`) and where the files landed.
