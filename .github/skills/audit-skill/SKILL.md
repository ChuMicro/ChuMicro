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
* **AI-tic phrasing** — same vocabulary list as `audit-docs` dim 2

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

### 4. Cold-agent loadability

Can an agent invoke this skill with no session context and know what *"done"* looks like?

* **When-to-use clause** — explicit, near the top.  Either in the description (frontmatter) or in an opening section.
* **Success / exit condition** — somewhere the body says when the skill is finished.  Audit skills carry an *"After-action sweep + exit condition"* block; procedural skills carry a *"Done when…"* clause.  Skills without an exit condition tend to over-run.
* **No implicit prior-conversation context** — flag phrasings like *"continue from the previous pass"*, *"as we discussed"*, *"the user mentioned earlier"*.  The skill can be invoked fresh.
* **Arguments documented** — if the skill takes a path / name argument, the body says so and shows examples.
* **Single-pass walkable** — can an agent walk top-to-bottom and execute, or does the body require jumping around?  Procedure section should be linear.

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
* **Tone bans cite `feedback_doc_writing_taste`** — the writing-tone memory is the source of truth; the skill should match it, not invent its own list.  If the project's AI-tic list has new entries (`feedback_doc_writing_taste.md`), the AI-tic regex in `audit-docs` dim 2 should mirror them, and any skill that carries its own AI-tic list is drift.

### 7. Composability with sibling skills

The end-of-work bookend (`task-checkpoint`) and the commit step (`git-commit`) are *their own skills*.  Other skills should defer, not re-implement.

* **Re-implemented bookend** — if the body has its own *"now run preflight, update plans/next-up.md, commit, push"* paragraph, that's `task-checkpoint`'s job.  Cite it instead.
* **Re-implemented commit prose** — heredoc commit-message recipes belong in `git-commit`; skill bodies should cite.
* **Sibling-skill references that resolve** — if the body says *"see [`task-checkpoint`](../task-checkpoint/SKILL.md)"*, the link should resolve (covered by dim 5 too).
* **Skill-set internal references (multi-skill mode)** — when auditing a related set, check that members cross-reference each other appropriately.  `audit-library` and `audit-embedded` should both mention they complement (not replace) each other; `session-handoff` and `session-resume` should bookend explicitly.

### 8. Tone — AI-tics + skill-specific anti-patterns

Run the **AI-tic grep from [`audit-docs` dim 2](../audit-docs/SKILL.md#2-vocabulary--grammar-tics)** — that regex is the source of truth.  Treat hits the same way `audit-docs` does (drop / replace / case-by-case).  Same rules apply to skill bodies as to user-facing docs.

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

Walk these in order:

1. **Frontmatter + discoverability pass** (dims 1, 2) — read the YAML, run the description through *what* + *when* check, flag jargon / vagueness.
2. **Body shape + loadability pass** (dims 3, 4) — `wc -l`, section grep (`grep -nE '^## ' <file>`), check for explicit when-to-use + exit-condition clauses.
3. **Reference rot pass** (dim 5) — extract every `Decision NNNN`, `scripts/run.py`, `CHU0NN`, sibling-skill name, file path, intra-doc anchor link, and embedded grep / awk snippet.  Resolve / dry-run each.
4. **Drift pass** (dim 6) — for each restated AGENTS.md / ADR rule, diff against the source.
5. **Composability pass** (dim 7) — does the skill defer to `task-checkpoint` / `git-commit` / siblings where it should?
6. **AI-tic + anti-pattern grep** (dim 8) — run the `audit-docs` regex; add the skill-specific patterns from this dim.
7. **Cross-skill pass** (dim 9) — only if multi-skill mode.  Trigger overlap, directive extraction, redundancy.
8. **Justification pass** (dim 10) — for each absolute rule in the body, locate the why.

### Punch-list

Group findings by confidence and tag by dimension (see Output format).

### Execute the HIGH-confidence batch

After the user gives the go-ahead, execute the HIGH-confidence fixes as a single edit pass.  MEDIUM items wait for user confirmation; LOW items wait for user answers.

### After-action sweep + exit condition

Re-run the dim 8 AI-tic grep on the changed file(s).  Re-run dim 5 reference checks on any citations that were edited.  The audit is done when:

* AI-tic grep returns no unjustified hits.
* Every accepted punch-list item has a corresponding edit (or a deferred-to-`plans/next-up.md` entry if the fix is bigger than the audit).
* In multi-skill mode, dim 9 finds no remaining overlap that the user hasn't explicitly accepted.

If new stumbles surface after the edit pass, file as a follow-up rather than expanding the current one.

End-of-work (preflight, plans-doc update, commit, push) is `task-checkpoint`'s job — defer to it rather than re-implementing.

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
* `ai-tic` — vocabulary / phrasing (dim 8, lifted from `audit-docs`)
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
* **Don't run `task-checkpoint` inline.**  This skill ends at the edit batch + after-action sweep.  Preflight, plans-doc update, commit, push are the next agent step (the `task-checkpoint` skill), not part of this one.

## Defer / out of scope

* **`README` files inside `.github/skills/`** — index docs, not skills.  Use `audit-docs` if a README needs review.
* **Plugin-namespaced skills (`plugin:skill`)** — out of project tree; can't be edited from here.
* **Anthropic-recommended frontmatter fields not yet in use** (`when_to_use`, `argument-hint`, `disable-model-invocation`, etc.) — flag as a *low-confidence question*, not a finding.  Project convention may not adopt every field; ask before adding.
* **Whole-tree skill audit** — auditing every skill in `.github/skills/` in one pass is a workspace-level concern.  If the user asks for it, surface that this is closer to an `audit-workspace`-style pass on the skills directory and ask whether to scope down or escalate.
