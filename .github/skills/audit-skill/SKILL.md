---
name: audit-skill
description: Audit one `.github/skills/<name>/SKILL.md` (or a related set) for frontmatter shape, trigger discoverability, reference rot, drift from AGENTS.md / ADRs, sibling composability, AI-tic phrasing, and absolute rules without an incident trail.  Produces a punch-list, executes safe cleanups with sign-off.  Use when a SKILL has drifted, a new one has landed, or two look like they compete for the same trigger.
---

# Skill audit

Audit one SKILL.md file under `.github/skills/<name>/` (or a related set — e.g. the audit-* family, the session-* pair) for the things that make a skill drift away from its trigger or duplicate what a sibling already does.  Output a prioritized punch-list, execute the high-confidence batch with the user's go-ahead.  Surface medium / low confidence items as questions rather than guessing.

> **About this skill's own prose.**  The target is internal docs (`.github/skills/`) — same audience as this body, so the rules don't invert the way they do for `audit-docs`.  The AI-tic grep applies here normally; the impl-leak / jargon-used-before-defined dimensions from `audit-docs` are *not* relevant because SKILL.md bodies legitimately cite `Decision NNNN`, `CHU0NN`, and `plans/` paths.

## Scope

`.github/skills/<name>/SKILL.md` files (also reachable at `.claude/skills/<name>/SKILL.md` via symlink — same file).  Out of scope: API-reference skills generated from code.

**Arguments.**

* `/audit-skill <name>` — single skill (e.g. `/audit-skill audit-docs`).  Runs every dimension except the cross-skill ones.
* `/audit-skill <name> <name> ...` — related set (e.g. `/audit-skill audit-library audit-embedded audit-integration`, or `/audit-skill session-handoff session-resume`).  Enables cross-skill dimensions (overlap, redundancy, composability against siblings).

When auditing a set, dims 7, 9, and the cross-skill parts of dim 10 fire in addition to the per-skill checks.

## Audit philosophy

Three agents land on the same SKILL.md and want different things.  The skill's job is to find prose that loses any one of them:

* **Loader agent** — Claude Code reads the `description` (and any `when_to_use`) at session start to decide whether this skill should appear in the picker for a given user message.  Bails when the description is vague, jargon-heavy, or doesn't name *what* and *when*.
* **Triggering agent** — Claude is mid-task, decides this skill matches, opens the body cold (no prior conversation context).  Bails when the body doesn't say what to do, what success looks like, or assumes context only the previous session had.
* **Sibling-skill author** — adding a new skill next to this one, needs to know whether the new task overlaps with what's here.  Bails when two skills compete for the same trigger or restate each other's rules.

Most skill drift falls into:

* **Trigger vagueness** — `description` doesn't carry *what* + *when* concretely enough to route a user message
* **Trigger overlap** — two skills' descriptions would both match the same plain-language ask
* **Reference rot** — `Decision NNNN` / `scripts/run.py <cmd>` / `CHU0NN` / sibling-skill name cited but no longer resolves
* **Drift from source of truth** — body re-states an AGENTS.md / ADR rule that has since changed
* **Speculative rules** — rules with no incident trail behind them ("always do X") that the agent can't tell apart from load-bearing ones
* **Sibling duplication** — re-implementing what `task-checkpoint` / `git-commit` already covers instead of deferring
* **Bloat** — body grown past the point where the agent reads it carefully
* **Anti-self-assertions** — *"I have read all rules"* / *"always follow X"* style affirmations that backfire (Cline community failure mode)
* **AI-tic phrasing** — phrase bans and standing regex live in [`agent-style-guide.md`](../../../docs/contributing/agent-style-guide.md)

## Audit dimensions

Run each.  Capture findings as `<line>` (or section name) + one-line description + dimension tag (see "Output format" below).

### 1. Frontmatter shape

Open the frontmatter block; check against Anthropic's published SKILL.md spec.

* **`name`** — present (or implicitly the directory name).  ≤64 chars, lowercase + digits + hyphens only.  Not `anthropic` / `claude` / other reserved words.  Should match the parent directory.
* **`description`** — present.  Names both *what the skill does* and *when to invoke it*.  Length: keep the *triggering* portion under ~400 chars; the loader reads the description text into every session-start reminder, so verbose descriptions tax every session uncached.
* **Person / mood** — Anthropic recommends third-person (*"Audits SKILL.md files for…"*).  The project's existing audit-* skills use imperative (*"Audit a user-facing markdown doc…"*).  Flag the mismatch only if it actually hurts trigger matching — both forms route correctly in practice.  Keep the project's imperative convention unless an explicit decision moves it.
* **Conditional fields** — if `context: fork` is set, `agent:` must be specified.  If `disable-model-invocation: true`, the skill is purely procedural (a `/command`-style entry point); verify the body reads that way.  If `allowed-tools:` is set, the listed tools must be ones the skill actually uses.
* **Reserved-word collision** — flag any `name` or filename that collides with Anthropic-reserved patterns.

### 2. Discoverability — does the trigger phrase route?

The loader agent matches user messages against the `description` text.  The body never enters that decision.

* **Concrete-action first** — *"Audits SKILL.md for X"* routes; *"Tools for working with skills"* / *"Helps you with skills"* does not.  Vague stems: `tools for`, `helps with`, `utilities`, `things related to`, `working with` — flag.
* **Jargon in description** — internal vocabulary in the description line burns the only signal the loader has.  *"runner-shaped"*, *"the canonical X"*, *"CHU0NN"* in the description specifically (the body is fine) — flag.
* **Missing *when*** — descriptions that say *what* but not *when to invoke* leave the loader with no triggering signal.  Look for an explicit *"Use when…"* / *"Use this skill when…"* clause.
* **Description bloat** — the description is part of every session-start cost.  Anything over ~400 chars of trigger text without a clear payoff is a tax on every session.
* **Trigger phrase obviousness** — would a user actually say the phrasing the description matches?  *"Use when a SKILL has drifted"* matches *"audit this skill"* and *"check if these skills overlap"*; *"For SKILL.md governance"* matches almost nothing a user would type.

### 3. Body shape

* **Length** — Anthropic recommends ≤500 lines for the SKILL.md body (see [Skills best practices](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices)); existing audit-* skills land 190–390 lines.  Past 500, signal-to-noise degrades because the agent skims rather than reads.  Past 800, the agent will partial-read with `head` and miss the back half.
* **Reference files** — supporting `.md` files in the skill directory.  One hop deep from SKILL.md only — deeper nesting causes the same partial-read pattern.  Reference files >100 lines need a table of contents at the top.
* **Procedure-first vs narrative** — skill bodies are read by an agent mid-task, not browsed by a human.  Flag long narrative preambles before any actionable step.  *"In this skill we will explore how to…"* / *"This skill covers many aspects of…"* — drop, start with the procedure.
* **Section ordering** — most skills want: Scope → Philosophy/Why → Dimensions/Checks → Procedure → Output format → Don'ts → Defer.  Bodies that bury Procedure below 400 lines of philosophy are unloadable.
* **Heading depth** — usually H1 (title) + H2 (top-level sections) + H3 (subsections).  Past H4, the structure is over-nested.
* **Rule-first vs example-first** — when teaching a principle, state the rule (with its reasoning) before the example.  *Good/bad* contrasts that leave the principle implicit force the reading agent to reverse-engineer it from the shape of the example — two reasoning hops instead of one, and the inferred rule covers only the cases the example covers.  Flag long *"common mistakes"* / *"good vs bad"* / *"❌ … ✅ …"* blocks doing the work that a single principle sentence would do.
* **Tool calls that could be invocation-time injection** — when a body opens with *"first, run X via Bash to get [state]"* and that value is invariably needed up front (git status, file listing, env vars), Claude Code's invocation-time shell expansion (a `!` prefix followed by a backticked shell command in slash-command / skill prose) substitutes stdout before the first agent step, saving a tool round-trip.  Flag the prose pattern; verify the current injection syntax in Claude Code docs before rewriting.  *(Don't write the literal bang-backtick sequence in a SKILL.md body — the preprocessor will fire it at load time.  Describe in prose instead.)*

### 4. Cold-agent loadability

Can an agent invoke this skill with no session context and know what *"done"* looks like?

* **When-to-use clause** — explicit, near the top.  Either in the description (frontmatter) or in an opening section.
* **Success / exit condition** — somewhere the body says when the skill is finished.  Audit skills carry an *"After-action sweep + exit condition"* block; procedural skills carry a *"Done when…"* clause.  Skills without an exit condition tend to over-run.
* **No implicit prior-conversation context** — flag phrasings like *"continue from the previous pass"*, *"as we discussed"*, *"the user mentioned earlier"*.  The skill can be invoked fresh.
* **Arguments documented** — if the skill takes a path / name argument, the body says so and shows examples.
* **Single-pass walkable** — can an agent walk top-to-bottom and execute, or does the body require jumping around?  Procedure section should be linear.
* **Mental simulation** — pick a representative user invocation and walk the body as a cold agent.  Flag *divergence points* (steps where two Claude instances would produce meaningfully different outputs because the spec is under-specified), *stuck points* (steps that need info not yet gathered or argued), and *dead ends* (the skill's workflow stops but the user's goal isn't accomplished — the user has to do something manually after).
* **Edge-case probe** — try 2–3 adversarial inputs: missing argument, malformed path, contradictory request, an input from outside the skill's intended domain.  Does the skill detect + surface a useful error, or silently produce wrong output?  Flag the latter as `loadability`.

### 5. Reference rot

Every citation in the body should still resolve.  Walk the file and verify:

* **`plans/decisions/NNNN-*.md`** — the file exists; the status enum is still meaningful (`proposed` / `accepted` / `superseded` / `deferred`).  A skill citing a `superseded` ADR is rot.
* **`scripts/run.py <cmd>`** — the command exists in the runner.  Quick check:
  ```
  grep -nE "scripts/run\.py \w[-\w]*" <SKILL.md> | awk -F"run.py " '{print $2}' | awk '{print $1}' | sort -u
  ```
  Each command should appear in `python scripts/run.py --help` output.
* **`CHU0NN`** — the lint code exists in `workbench/checks/`.
* **File paths** — every `libraries/<name>/...`, `workbench/<name>/...`, `support/<name>/...` path resolves.
* **Sibling skill names** — every `audit-docs` / `task-checkpoint` / `git-commit` reference points to a real `.github/skills/<name>/` directory.
* **Intra-doc + reference-file anchors** — SKILL.md bodies link into anchored sections of sibling reference files (`field-reality.md#stale-cli-...`).  A renamed anchor breaks the link silently.  Check with:
  ```
  grep -nE '\(#[a-z0-9-]+\)|\([a-z0-9-]+\.md#[a-z0-9-]+\)' <SKILL.md>
  ```
  For each `(file.md#anchor)` hit, verify the anchor exists in the target file (GitHub slug rules: lowercase, spaces → hyphens, em-dashes / parens dropped).
* **Embedded snippets** — grep / awk / regex blocks shown as audit checks must actually fire.  When the skill says *"grep for X"* and shows a pattern, dry-run the pattern against a representative target in the repo.  A regex that was right at write-time but whose target has since moved (renamed method, restructured directory, changed lint code) is rot the same way a dead citation is.
* **External URLs** — flag, don't verify by default (cost / flakiness); only verify if the URL is load-bearing for the procedure.

### 6. Drift from source of truth

`AGENTS.md` and `plans/decisions/` are the source of truth.  Skills should *cite* them, not re-state and then drift from them.

* **Re-stated AGENTS.md rules** — if the skill restates a non-negotiable rule (test-skip loudness, runner-shape, absolute-imports-in-libraries, etc.) and the AGENTS.md wording has changed, flag.  Prefer a one-line citation: *"Per AGENTS.md → Testing, test skips must be loud (see [Decision 0058](../../../plans/decisions/0058-test-skips-must-be-loud.md))"*.
* **Re-stated ADR content** — same.  If the skill explains *why* a Decision exists, that explanation can drift from the ADR body.  Cite, don't restate.
* **Tone bans cite [`agent-style-guide.md`](../../../docs/contributing/agent-style-guide.md).**  The agent style guide is the source of truth for the phrase bans, the standing regex, and per-word handling.  Any skill that carries its own AI-tic list, restates the per-word handling, or maintains a parallel regex is drift.  Cite, do not restate.  When a new word lands, it goes into the right § Phrase bans subsection and the regex in § Standing AI-tic regex; every audit skill picks it up automatically.

### 7. Composability with sibling skills

The end-of-work bookend (`task-checkpoint`) and the commit step (`git-commit`) are *their own skills*.  Other skills should defer, not re-implement.

* **Re-implemented bookend** — if the body has its own *"now run preflight, update plans/next-up.md, commit, push"* paragraph, that's `task-checkpoint`'s job.  Cite it instead.
* **Re-implemented commit prose** — heredoc commit-message recipes belong in `git-commit`; skill bodies should cite.
* **Sibling-skill references that resolve** — if the body says *"see [`task-checkpoint`](../task-checkpoint/SKILL.md)"*, the link should resolve (covered by dim 5 too).
* **Skill-set internal references (multi-skill mode)** — when auditing a related set, check that members cross-reference each other appropriately.  `audit-library` and `audit-embedded` should both mention they complement (not replace) each other; `session-handoff` and `session-resume` should bookend explicitly.

### 8. Tone — AI-tics + skill-specific anti-patterns

Run the **AI-tic grep from [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex)** — that section is the source of truth.  Treat hits per [§ Phrase bans](../../../docs/contributing/agent-style-guide.md#phrase-bans) (drop / replace / case-by-case).  Same rules apply to skill bodies as to user-facing docs.

**Degraded passages get rewritten, not re-trimmed.**  SKILL.md bodies rot exactly the way code comments and READMEs do.  These skills are long and have been trimmed pass after pass, each removing a word, none asking *what should this say?*  An `ai-tic` or `shape` finding whose passage has rotted that far (illegible, says nothing, would lose nothing it doesn't already lack if deleted) is not fixed by removing another word.  Discard it and rewrite from a fresh read of *what this skill does and when it fires*, applying the cold-loader / cold-triggering-agent test (Audit philosophy).  Tag it `rewrite` and show the proposed replacement text inline.  MEDIUM by default, since the rebuilt prose is a judgment call.

*Testable criterion.*  If the proposed edit changes ≤1 sentence and leaves the surrounding paragraph structure intact, it is a strip (`ai-tic` / `shape`), not a `rewrite` — even if the word *"rewrite"* came up while drafting.  A rewrite reconsiders the passage from **source** (the dim 4 three-agent personae: what the loader needs from the description, what the triggering agent needs from the body, what a sibling-skill author needs from the scope), not from the existing prose.  Drafting with the original in view biases toward minimal edits — read source, look away, draft fresh, *then* compare.  If you cannot draft from source alone, that itself is a finding (the prose carried knowledge the skill's scope doesn't make obvious — revisit dim 2 or dim 3).

This is [`agent-style-guide.md` § Degraded prose is rewritten, not trimmed again](../../../docs/contributing/agent-style-guide.md#degraded-prose-is-rewritten-not-trimmed-again) applied to SKILL.md bodies.  `/audit-comments` and `/audit-docs` make the same move for their scopes.  Re-trimming the wreckage manufactures the residue the rule exists to stop.

Skill-specific anti-patterns on top of the standard list:

* **Anti-self-assertions** — *"I have read all the rules"*, *"always follow these guidelines"*, *"I will not skip steps"* in the body.  Known Cline-community failure mode: the assertion reads as completed work and the agent skips the actual rule.  Flag every occurrence.
* **Time-sensitive phrasing** — *"before August 2025"*, *"as of 2026-05-13"*, *"in the current release"*.  Skills outlive their dates.  Drop dates, name the condition that was true at the time (*"on CircuitPython 9.x"*) instead.
* **Inconsistent terminology** — using *"audit"* / *"check"* / *"review"* interchangeably within one skill where they should be one term.
* **"Voodoo constants"** — magic numbers / paths in procedural snippets without a why.  *"Run with `--timeout 47`"* without an explanation of why 47.
* **First-person plural** — *"we run"*, *"our convention"* in a skill body.  The agent is reading instructions, not co-authoring them.  Switch to imperative.

### 9. Cross-skill overlap (multi-skill mode only)

When auditing a related set, check that the skills don't compete with or duplicate each other.

* **Trigger phrase overlap** — extract the *"Use when…"* clause from each description.  Two skills whose triggers would route the same user message → flag.  Concrete approach: for each pair of descriptions, extract noun-phrases after *"use when"* / *"use this when"* / *"audit a"* etc., and look for substantial lexical overlap.
* **Directive extraction + conflict** — lift the cursor-doctor approach.  Extract imperative directives from each body (regex on `\b(use|prefer|never|avoid|always|don'?t|must|should)\s+\w+`).  Cross-file diff: same noun, opposite verb → contradiction.  Same noun, same verb in two skills → candidate for moving the rule to a single source of truth (AGENTS.md or one skill).
* **Redundancy** — line-overlap >60% between two skills → merge candidate.  Approximate with:
  ```
  diff -y --suppress-common-lines <skill1>/SKILL.md <skill2>/SKILL.md | wc -l
  ```
  vs the line count of each.  Not exact, but surfaces obvious duplication.
* **Coverage gap** — for a family like audit-* or session-*, ask: is there an obvious case the set doesn't cover?  *"audit-library covers libraries, audit-workspace covers cross-library, but nothing covers `support/`"* — surface as a question, not a finding.

### 10. Rule justification — incident trail vs speculation

Rules without an incident behind them are hard for the agent to weigh against contradicting signals.

* **"Always do X" without context** — rules phrased as absolutes should be traceable to an incident, an ADR, or a feedback memory.  *"Always run preflight before commit — preflight enforces coverage (see [Decision 0025](../../../plans/decisions/0025-dual-coverage-thresholds.md))"* is grounded; *"Always run preflight before commit"* alone is harder to weigh.  Flag rules without a why or a pointer.
* **Cross-check against `feedback_*` memories** — the user's auto-memory carries the *incident → rule* pairs (`feedback_dont_unmount_circuitpy`, `feedback_never_persist_microcontroller_reset`, etc.).  If a skill encodes a rule that should be there but isn't, surface as a question: *"Is this rule captured in feedback memory, or should it be?"*.
* **Rule of Three** — borrowed from refactoring guidance (Fowler, *Refactoring*: "Three Strikes and You Refactor"; recently applied to agent-rule discipline in the agentic-tooling community).  A rule codified after the agent fails the same pattern once is often premature; three observations is the rough cut-off.  Skills that read like a defensive catalog of every possible mistake usually have premature rules; ask the user *"do you want to keep this, or is it covered by [memory / ADR / regex check]?"*.

## Procedure

**Two passes, in order.**  Pass 1 makes the subtractive edits — AI-tic strips, anti-self-assertion strips, dated-phrasing strips, voodoo-constant flags, frontmatter normalization, reference-rot fixes, drift one-line citation swaps, composability strip-to-citation moves, and description vague-stem fixes where the swap is mechanical.  Pass 2 re-reads the post-Pass-1 state cold against the three personae (loader, triggering agent, sibling-skill author): with the tic noise and dead citations cleared, the structural and judgment-level failures that survive are legible as failures.  Pass 2 surfaces body-shape moves, cold-agent loadability gaps, cross-skill overlap (in multi-skill mode), rule-justification rewrites, and the `rewrite` findings where a fresh-read replacement is the right fix.  **Run Pass 1 to a commit before starting Pass 2** — strips routinely reveal that the surrounding prose, not the tic, was the actual defect, and reading the original state biases Pass 2 toward minimal edits and degraded prose perpetuates.  This is the same boundary `/audit-docs` and `/audit-comments` enforce, for the same reason.

**Clause-paced reading in Pass 2.**  Pass 1's strips leave paragraphs that read fine at paragraph scale while a mid-paragraph parenthetical, a buried clause, or a single item in a long bulleted dimension list still encodes the defect.  Pass 2 reads clauses individually inside each paragraph, not paragraphs as units.  Paragraph-paced reads leave residue; clause-paced reads catch it.

**Cross-section sweep before per-passage rewrites.**  In Pass 2, read related parts of the body together — frontmatter `description` + opening Scope + the first procedural step often state the same trigger.  Name a home (usually the description, since the loader sees only that) and collapse the others to one cohesive statement.  Per-section review misses this because each site reads fine alone.

### Pass 1 — subtractive sweep

1. **AI-tic + anti-pattern grep** (dim 8).  Run the standing regex from [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex), plus the skill-specific patterns in dim 8 (anti-self-assertions, dated phrasing, voodoo constants, first-person plural).  Hard-ban hits and anti-self-assertions almost always need a strip; soft hits are case-by-case.
2. **Frontmatter normalization** (dim 1).  Mechanical shape fixes: `name` matches directory, `description` exists and carries *what* + *when*, conditional fields satisfy their constraints.  Description rewrites that need new prose (subjective wording) defer to Pass 2.
3. **Reference-rot fix** (dim 5).  Extract every `Decision NNNN`, `scripts/run.py <cmd>`, `CHU0NN`, sibling-skill name, file path, intra-doc anchor, embedded grep / awk snippet.  Resolve or dry-run each.  Dead citations get a one-line fix (corrected number, current command name) or removal where the surrounding sentence still holds.  Anchor renames get the new slug.
4. **Drift one-line citation swap** (dim 6).  For each restated AGENTS.md / ADR rule that has diverged from source, replace the restatement with a one-line citation (*"Per AGENTS.md → Testing, test skips must be loud (see [Decision 0058](...))."*).  Restatements that have *not* diverged but still re-implement source content also get cited rather than mirrored, per dim 6.
5. **Composability strip-to-citation** (dim 7).  Replace duplicated `task-checkpoint` / `git-commit` paragraphs with one-line citations.  Same for sibling-skill content that's restated rather than referenced.
6. **Description vague-stem fix** (dim 2 — mechanical subset).  Vague openers (*"Tools for…"*, *"Helps with…"*, *"Utilities for…"*) get swapped to concrete-action openers when the swap is mechanical (the rest of the description already names the action; only the stem was vague).  Vague descriptions that need new content defer to Pass 2.

**Pass 1 punch-list and execution.**  Group by confidence.  HIGH: AI-tic hits, anti-self-assertions, dated phrasing, dead citations, anchor fixes, one-line drift citations, composability strip-to-citation moves, mechanical vague-stem swaps.  MEDIUM: drift cases where one sentence of the local restatement should survive the citation swap, frontmatter rewrites that need a judgment call.  Execute HIGH as one cohesive commit; MEDIUM as separate commits if accepted.

### Pass 2 — reconstructive sweep

The three-persona walk runs against the cleaned state.  Pass 1's strips remove tic noise and dead citations, so the structural failures that survive are legible rather than camouflaged.

7. **Cold-agent loadability walk** (dim 4).  Walk the body as a cold loader, then a cold triggering agent, then a sibling-skill author against one representative invocation (mental simulation), and probe 2–3 adversarial inputs (missing arg, malformed path, contradictory request, input from outside the skill's intended domain).  Flag divergence points (steps where two Claude instances would meaningfully diverge), stuck points (steps needing info not yet gathered), and dead ends (workflow stops short of the user's goal).  Apply the clause-paced rule.
8. **Body shape evaluation** (dim 3).  `wc -l`, section grep (`grep -nE '^## ' <file>`).  Procedure-first vs narrative, section ordering against the recommended arc (Scope → Philosophy → Dimensions → Procedure → Output → Don'ts → Defer), heading depth, rule-first vs example-first, reference-file table-of-contents on files >100 lines.  Length thresholds are more legible after Pass 1 since the padding that masked them is gone.
9. **Description reconstructive rewrite** (dim 2).  Descriptions that survived Pass 1 but still fail the triggerability test (no *when*, jargon-heavy, no obvious user phrasing match) get rewritten.  Draft from source per the discipline below — what the skill does, when it fires, who calls it — *before* re-reading the existing description.
10. **Cross-skill overlap** (dim 9 — multi-skill mode only).  Trigger phrase overlap, directive extraction + conflict detection, redundancy diff, coverage gap.  Rewrites here are MEDIUM (which skill owns the contested phrase is a judgment call); pure deletions of duplicated paragraphs are HIGH.
11. **Rule justification rewrites** (dim 10).  For each absolute rule without an incident trail: trace to an ADR / `feedback_*` memory and add the pointer, soften to a guideline, or remove.  Drafting the pointer prose follows the source-first discipline (read the ADR or memory; draft the cited sentence fresh; compare).
12. **Reconstructive rewrites** (dim 8 — `rewrite` findings).  For each passage flagged as degraded in Pass 1's grep but where stripping further would leave the prose opaque or ambiguous, draft replacement text from a fresh read of *what this skill does and when it fires* (the dim 4 three-persona test) — *before* re-reading the original.  Order is load-bearing: read the skill's scope from its own dimensions and procedure, look away, draft fresh, *then* compare against the original.  Drafting with the original in view biases toward minimal edits and degraded prose perpetuates.  Apply the cold-loader / cold-triggering-agent test to your proposed text, not just the original.

**Pass 2 punch-list and execution.**  Group by confidence.  HIGH: structural moves with clear cold-agent benefit, mechanical loadability gaps (missing exit-condition clause, missing arguments section).  MEDIUM: `rewrite` findings with proposed replacement text (judgment call about which scope-framing is load-bearing); description rewrites; rule-justification rewrites where the soften-vs-trace call needs sign-off.  LOW: stumbles where the agent-persona is unclear.  Execute HIGH as one cohesive commit; MEDIUM as separate commits, one per rewrite — small reversible edits; if one rewrite reads worse on a second look, the rest stand.

### After-action sweep + exit condition

Re-run the dim 8 AI-tic grep on the changed file(s).  Re-run dim 5 reference checks on any citations that were edited.  Rewrites pull in new tics, so the second grep catches what fresh prose introduced.  The audit is done when:

* AI-tic grep returns no unjustified hits.
* Every accepted punch-list item has a corresponding edit (or a deferred-to-`plans/next-up.md` entry if the fix is bigger than the audit).
* In multi-skill mode, dim 9 finds no remaining overlap that the user hasn't explicitly accepted.
* A cold re-walk of the changed sections against the three personae does not surface a new stumble.

If new stumbles surface after the edit pass, file as a follow-up rather than expanding the current one.

After the after-action sweep, invoke the `task-checkpoint` skill — it owns preflight, plans-doc update, commit, and push.  Don't stop without invoking it.

## Output format

Single-skill mode:

```
Skill audit: .github/skills/<name>/SKILL.md
===========================================

HIGH-CONFIDENCE (safe to fix):

  frontmatter  L<n>  — <one-line description>
  discover     L<n>  — <one-line description>
  shape        L<n>  — <one-line description>
  loadability  L<n>  — <one-line description>
  rot          L<n>  — <one-line description>
  ai-tic       L<n>  — <one-line description>
  ...

MEDIUM-CONFIDENCE (sign-off needed):

  rewrite      §<section>  — <passage rotted by prior trim passes;
                              proposed replacement text shown inline>
  drift        §<section>  — <restated rule diverged from AGENTS.md / ADR>
  composability §<section> — <duplicates task-checkpoint / git-commit>
  justify      L<n>  — <rule absolute, no why or pointer>
  ...

LOW-CONFIDENCE (questions for the user):

  shape        §<section>  — <is this section earning its length?>
  ...
```

Multi-skill mode adds an "Across the set" block:

```
Across the set (audit-library, audit-embedded, audit-integration):

  overlap     <skillA> ↔ <skillB>  — trigger phrases would match the same ask
  redundant   <skillA> ↔ <skillB>  — N% line overlap in section §X
  conflict    <skillA>:<line> ↔ <skillB>:<line>  — directives contradict
  gap         — set doesn't cover <obvious case>
```

**Worked example** (synthetic — illustrative, not a real audit):

```
Skill audit: .github/skills/audit-widget/SKILL.md
=================================================

HIGH-CONFIDENCE (safe to fix):

  frontmatter  L2  — description has *what* but no *when* clause
  discover     L2  — description opens with "Tools for widget review" (vague stem)
  ai-tic       L47 — "comprehensive widget coverage" — list what's covered
  ai-tic       L91 — "under the hood" — name the verb concretely
  rot          L66 — cites scripts/run.py widget-check; not in --help output
  loadability  §Procedure — no exit-condition clause; agent will over-run

MEDIUM-CONFIDENCE (sign-off needed):

  composability §After-action — duplicates task-checkpoint's preflight + commit
                                paragraph; replace with citation
  drift         L120 — restates Decision 0025 coverage rule; ADR wording has
                       since shifted to "94% for agent-generated" — body says 96%
  justify       L140 — "Always run widget-check before commit" — no why, no
                       ADR pointer; trace or remove

LOW-CONFIDENCE (questions for the user):

  shape         §Philosophy — 80-line preamble before first procedural step;
                              compress or move to a reference file?
```

## Tag taxonomy

* `frontmatter` — frontmatter shape (dim 1)
* `discover` — description quality / triggerability (dim 2)
* `shape` — body length, structure, ref-file depth (dim 3)
* `loadability` — cold-agent loadability (dim 4)
* `rot` — reference rot (dim 5)
* `drift` — restated rule diverged from source of truth (dim 6)
* `composability` — sibling-skill duplication or missing deferral (dim 7)
* `ai-tic` — vocabulary or phrasing flagged by [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex) (dim 8)
* `rewrite` — passage degraded by prior subtractive passes; discard and rebuild from a fresh read of what the skill does (dim 8, per [`agent-style-guide.md` § Degraded prose is rewritten, not trimmed again](../../../docs/contributing/agent-style-guide.md#degraded-prose-is-rewritten-not-trimmed-again)).  *Testable criterion:* if the proposed edit changes ≤1 sentence and leaves the surrounding paragraph intact, it is a strip (`ai-tic` / `shape`), not a `rewrite` — tag accordingly.  Replacement shown inline; MEDIUM by default — rebuilt prose is a judgment call.
* `overlap` — cross-skill trigger / directive overlap (dim 9)
* `redundant` — line-overlap merge candidate (dim 9)
* `conflict` — cross-skill directive contradiction (dim 9)
* `gap` — set doesn't cover an obvious case (dim 9)
* `justify` — absolute rule without an incident trail (dim 10)

## Surface questions instead of guessing

| Symptom | Question to surface |
|---|---|
| Description vague but skill clearly does one thing | *"`description` opens with `<vague stem>` — want me to rewrite the first clause to name the concrete action?  Suggested: `<draft>`"* |
| Restated AGENTS.md / ADR rule | *"This paragraph re-states [rule X] from [source].  Replace with a one-line citation, or keep the local copy because of [reason]?"* |
| Skill re-implements task-checkpoint / git-commit | *"This section duplicates [`task-checkpoint`](...) — replace with citation, or is there a reason this skill needs its own copy?"* |
| Trigger overlap between two skills in the set | *"`<skillA>` and `<skillB>` both trigger on `<phrase>`.  Disambiguate by trigger, merge into one, or accept and document the split?"* |
| Same rule restated in multiple skills | *"`<rule>` appears in `<skillA>`, `<skillB>`, `<skillC>`.  Hoist to AGENTS.md and cite from each, or designate one as the source?"* |
| Absolute rule without a why | *"`<rule>` is phrased as an absolute but I can't find an incident or ADR behind it.  Trace it, soften to a guideline, or remove?"* |
| Body past ≤500 lines | *"SKILL.md is `<N>` lines.  Extract `<section>` to a reference file, or keep inline?"* |
| Section heading promises more than the section delivers | *"`## <heading>` reads broader than what's in it (one paragraph).  Rename, fold up, or expand?"* |
| Description in person/mood that differs from siblings | *"Project skills use imperative (`Audit a ...`); this one uses third-person (`Audits ...`).  Match the project pattern, or keep?"* |

## What NOT to do

**Content don'ts**

* **Don't propose merging two skills based on tag overlap alone.**  Two audit-* skills sharing the AI-tic regex doesn't mean they overlap — they're both citing the same source.  Look at the *trigger* and the *target*, not the shared boilerplate.
* **Don't flag every absolute rule.**  Absolutes with a clear `Decision NNNN` / `feedback_*` / *"after the [date] incident"* pointer are grounded.  Flag the ungrounded ones, not the well-cited ones.
* **Don't restructure based on taste.**  *"I'd write the Scope section last"* is not a finding.  The three-agent walk gives the objective lens.

**Verification don'ts**

* **Don't trust `description` length without checking the live cap.**  Anthropic's documented cap has moved between 1024 and 1536 chars across docs versions; verify against current docs before flagging a hard threshold.  The principle holds either way: the description rides in every session-start cost, keep it tight.
* **Don't assume a citation is rot without resolving it.**  `Decision 0042` might just be the next one in a sequence — `ls plans/decisions/0042-*.md` first, then flag.
* **Don't run dim 9 (cross-skill) on unrelated skills.**  *"audit-docs and git-commit don't overlap"* is not useful information.  Multi-skill mode is for sets that genuinely interact.

**Process don'ts**

* **Don't auto-commit.**  Skill edits are governance; user reviews before commit.  Surface as punch-list first; execute HIGH-confidence batch only after explicit go-ahead.
* **Don't expand scope mid-pass.**  If a reference rot finding surfaces an outdated AGENTS.md paragraph, file as a follow-up — don't fold it into the current edit batch.
* **Don't inline `task-checkpoint`'s steps.**  Preflight, plans-doc update, commit, push aren't part of this skill's procedure — but invoking the `task-checkpoint` skill *is* the required next agent step once this skill's exit condition is met.  "Don't re-implement" never means "skip the invocation".

## Defer / out of scope

* **`README` files inside `.github/skills/`** — index docs, not skills.  Use `audit-docs` if a README needs review.
* **Plugin-namespaced skills (`plugin:skill`)** — out of project tree; can't be edited from here.
* **Anthropic-recommended frontmatter fields not yet in use** (`when_to_use`, `argument-hint`, `disable-model-invocation`, etc.) — flag as a *low-confidence question*, not a finding.  Project convention may not adopt every field; ask before adding.
* **Whole-tree skill audit** — auditing every skill in `.github/skills/` in one pass is a workspace-level concern.  If the user asks for it, surface that this is closer to an `audit-workspace`-style pass on the skills directory and ask whether to scope down or escalate.
