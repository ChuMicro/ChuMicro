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
  - Bash(wc *)
  - Bash(python3 *)
  - AskUserQuestion
  - Agent
  - Workflow
when_to_use: Use even when the user describes the pattern without using the word "skill", as long as the intent is clearly to capture it for reuse. Do NOT use to edit an existing SKILL.md in place — that's a normal Edit task. Do NOT use to audit or fix up an existing skill — that's /audit-skill; regenerating a skill from scratch at the user's explicit ask stays here.
argument-hint: "[<slug>] [<free-form context>]"
---

# New Skill

Produce a skill at `<root>/.claude/skills/<slug>/` — the loader path; projects that keep skills under `.github/skills/` and symlink `.claude/skills` to it (this one does) get the files written there instead. The skill must be one a future agent can invoke cold and execute correctly on the first read. The route there: a real conversation about what the skill is, a draft on disk, the six-lens workflow plus measured routing probes against that draft, and fixes the user picks by number. The intake conversation is where vague descriptions get caught — once a SKILL.md lands wrong on disk, every later session that loads it inherits the drift.

## Clean-slate rule

While authoring, do not Read any other SKILL.md's body, persona file, or reference file in the tree — existing skills carry drift the new one is meant to escape, and even a glance paraphrases it into the draft. The one exception: the sibling survey below reads each sibling's `description:` line only (routing metadata, not body prose).

When a SKILL.md already exists at the chosen slug and the user did **not** explicitly ask to regenerate it, fire an `AskUserQuestion` that quotes the existing skill's `description:` line and its last-commit date, with options: regenerate from scratch (the old body stays unread), route to `/audit-skill <slug>` for in-place improvement, or pick a different slug. When the user explicitly asked to regenerate, skip the ask and proceed — the old body still stays unread (it is the drift being escaped); carry only its `description:` line into the sibling survey, and offer its `trigger-evals.json` rows as intake candidates for the user to re-confirm or replace.

## What a finished skill ships

| File | When |
|---|---|
| `SKILL.md` | Always |
| `trigger-evals.json` | Always — intake's positives + near-misses; schema: `skill_name`, `evals: [{query, should_trigger, expected_route?}]` |
| `TESTPLAN.md` | When the skill bundles scripts or a driver — layered per [`testplan.md`](testplan.md), written at draft time so the lenses validate it |
| Reference files | When the body links them (one hop deep) |
| `scripts/` | When the procedure needs code; entry points named per their job |
| Persona files at `.claude/agents/` | Only when the skill's work genuinely needs standing custom agents — most fan-outs are better as a Workflow script with inline lens prompts |

When the success criterion is *"the app started and a page rendered,"* a markdown file cannot click a button — build the driver now and commit it alongside.

## The question rule

Every question you ask the user must be decidable from the question plus what they just read. During validation that means findings go in front of them numbered, with quoted evidence, consequence, and the exact proposed change, **before** any ask. During intake it means pushing back in plain conversation, not routing every fork through an approval widget — `AskUserQuestion` is for genuine 2–4-option forks; everything else is dialogue.

## Definition of done

1. The `description:` routes the intake's trigger set — **measured** by the probe lane, not only judged.
2. The body walks top-to-bottom with a discriminating Success criterion per step (a clearly-wrong run must fail it) and a Done-when block distinct from the last step.
3. Every linked reference file exists; every code block ran in this session and succeeded.
4. The lens workflow ran against the on-disk draft; its findings were resolved by number or explicitly accepted.
5. `trigger-evals.json` sits next to the SKILL.md; driver-backed skills also ship TESTPLAN.md and the driver ran in-session.

## Process

### 1. Intake — a conversation, not a form

Run the slug-collision pre-flight and sibling survey first:

```bash
ls .github/skills/<slug>/SKILL.md .claude/skills/<slug>/SKILL.md 2>/dev/null
find . -path '*/skills/*/SKILL.md' -not -path '*/node_modules/*' -not -path './.tools/*' -not -path './.venv/*' -exec grep -H -m1 '^description:' {} \;
```

Then talk. Plain-chat questions, a few at a time, pushing back on vague answers until each of these artifacts is concrete:

- **The goal in one sentence** — what exists after the skill runs that didn't before.
- **Three real trigger messages** plus **3–5 near-misses with expected routes** (a sibling slug from the survey, or `none`). Written the way users type: a concrete path or symbol, some backstory, casual phrasing, the odd typo. Abstract queries measure nothing; obviously-irrelevant negatives test nothing. Offer to draft candidates with a fresh `claude -p` from the goal sentence plus the sibling survey, for the user to label — cold-model phrasing beats author-invented realism.
- **Scope** — what's in, and at least two things the skill refuses to do.
- **The procedure, walked once in the user's words** — including what each step observably produces and where a human must decide.
- **Tools and driver needs** — what the skill runs, not just guides.
- **Absolutes traced** — every "always/never" the user states gets a source (an incident, an ADR, three observations) or softens to a guideline.

[`interview.md`](interview.md) is the deep question bank — consult it when an area is murky (vocabulary sourcing, agent-architecture choices, stretch angles, pushback patterns). It informs what to ask; it is not a gate sequence to march through. Two rounds of pushback is normal; ten means the user doesn't yet know what the skill is — offer to pause until they've done the workflow once for real.

**Success criteria:** every artifact above captured concretely in chat, with at least one vague answer having been pushed back on — an intake with zero pushback means it ran too shallow or the user was unusually ready.

### 2. Draft to disk

Description first — it's the loader's only routing surface, so test it against the trigger set by eye before anything else ([`spec-loader-reader.md`](spec-loader-reader.md) carries the field rules, caps, and calibration table; [`template.md`](template.md) is the scaffold; [`spec.md`](spec.md) and [`spec-orchestration.md`](spec-orchestration.md) carry body patterns and multi-agent architecture guidance; [`spec-triggering-reader.md`](spec-triggering-reader.md) the structure and stance rules). Then the body: numbered steps, each with a discriminating Success criterion; a Done-when block that names the observed end-state, not the last action. For driver-backed skills, write TESTPLAN.md now so the lenses validate it with everything else. Write all of it to the real paths — the lenses and probes need files on disk, and git is the safety net.

**Success criteria:** SKILL.md on disk with a numbered Process whose every step carries a Success criterion, and a Done-when block distinct from the last step; `trigger-evals.json` parses and carries the intake's three positives and 3–5 near-misses with expected routes; any TESTPLAN.md, reference files, scripts, or personas the design calls for written alongside.

### 3. Validate — lenses and probes in one turn

- **Lenses:** call `Workflow` with `scriptPath: .github/skills/_shared/audit_wf.js` and `args: {skillPath, referenceFiles, personaFiles, scriptFiles, triggerMessages, sizing}` (`sizing` = a measured lines/est-tokens/longest-line table for the draft and its reference files, one string — tokens as chars/4; the cold-walk lens trusts it over its own count) — the same seven lenses `/audit-skill` runs: six blind (loader, cold-walk, craft, orchestration, surprise, ideas), each restricted to the files its prompt names, plus a web-searching research lens that sets prior art (including Anthropic's public skills repo), an ideal-version sketch, and live Claude Code docs against the fresh draft. All six are schema-forced to return evidence-carrying output. Your own read is not a substitute: you know what the skill is supposed to say, so you fill its gaps; the lenses cannot.
- **Probes:** `Bash(run_in_background: true)`: `python3 .github/skills/_shared/run_trigger_evals.py <skill-dir>/trigger-evals.json` — each probe is a fresh `claude -p` whose loader sees the draft competing against every sibling description: measured routing, which also covers sibling trigger overlap better than any judgment pass. When near siblings carry their own `trigger-evals.json`, re-run theirs too — a new description can steal queries that used to route to them, and only their evals show it.

Verify all findings marked `harness_claim` in one message of parallel `claude-code-guide` dispatches (doc URL required for each) before presenting them — the lens rules snapshot the docs and lag the product. A contradicted rule becomes its own numbered item in the Step 4 report (*"lens rule outdated — proposed `_shared/audit_wf.js` fix: <exact change>"*) for the user to apply or skip; never edit the shared script unprompted.

**Success criteria:** six lens objects and the probe table collected; every harness-claim resolved to confirmed-with-URL or contradicted-with-URL.

### 4. Resolve by number

Lens findings outrank your own read: every lens finding enters the report unfiltered, at the lens's tier — disagree in prose next to the number, never by dropping or re-tiering. Print one numbered report — findings first (tier, quoted evidence, consequence, exact proposed fix), then the ideas menu with each lens-recommended action. Whenever at least one item is open, render and serve the shared decision page (`webui/render_picker.py` + `serve_picker.py`, backgrounded; it posts to the surface hub, which owns the one browser tab — never `open` the URL or set `PICKER_NO_OPEN` — with `Monitor` on its stdout) — the evidence-rich layout earns its keep even for a single finding; picks and per-item notes come back as one submitted blob. Plain chat stays valid throughout: `apply 1, 3` · `discuss 2` · `edit 4: <wording>` · `skip the rest`.

Apply each pick visibly via `Edit`; re-read shifted regions between fixes. A probe FAIL means showing the user the failing query, the route it took, and the proposed description change (old clause → new clause) before re-running — and when the eval row's `expected_route` looks wrong instead, say so and propose fixing the row. Generalize: name the intent category the failing query represents, never paste the query's words as one more clause (clause-per-failure overfits the eval set and bloats the listing toward the combined cap in [`spec-loader-reader.md`](spec-loader-reader.md)). After all picks land, issue every re-verification as parallel `Agent` calls in a single message — one fresh agent with `model: "opus"` per substantive rewrite, given the finding plus the post-edit file, returning *resolved / not / new finding*.

**Success criteria:** every number resolved or explicitly accepted with a reason; probe table green or each FAIL user-accepted aloud; re-verification verdicts collected.

### 5. Finish

For driver-backed skills, run every self-executing TESTPLAN row now; list each remaining needs-human row in the closing block with the exact command or observation the human must perform. Print the closing block: files written with line counts, the `/<slug>` invocation form, and what the user should do next (read from disk, edit directly for small tweaks, `/audit-skill <slug>` for a later structural look).

**Success criteria:** closing block printed; for driver-backed skills, the self-executing rows ran green or each failure was surfaced to the user and accepted.

## Red flags — stop and reconsider

- You drafted to disk before the intake artifacts were concrete. A premature draft is a draft you stop pushing back on.
- The description opens with a vague stem (*"Tools for…"*, *"Helps with…"*). The loader will not route it.
- The intake produced no pushback and the trigger messages read abstract — it ran too shallow; re-open it.
- The Done-when block restates the last step. Name the observable end-state instead.
- You skipped the lenses because the draft "reads fine." Authors cannot read their own drafts cold.
- The skill needs a driver and you didn't write one, or a code block in the draft never ran this session.
- Everything worked first try. Either the skill is trivial or you copied commands without running them.

## Don'ts

- Don't restate a sibling's content in the new body — cite or extend; the probes will catch trigger overlap, but content overlap is yours to avoid at draft time.
- Don't accept *"always do X"* without an incident trail — trace it or soften it.
- Don't enumerate every option in the body. One default with an escape hatch; alternatives are noise to an agent mid-task.
- Don't write descriptions in first or second person — third person, or the loader misroutes.
- Don't treat patterns-to-avoid hits as find-replace targets — the sentence needs different content, not a synonym.
- Don't dump shell output into the body when dynamic-context injection does it cleaner ([`spec-loader-reader.md` § Dynamic context injection](spec-loader-reader.md#dynamic-context-injection--bangcommand)).

## Done when

- `<skill-dir>/SKILL.md` and `trigger-evals.json` exist with the agreed content; every linked reference file and script exists; any persona files sit at `.claude/agents/`.
- The probe table is in scrollback with every row green or its FAIL explicitly accepted; the lens report's numbers are all resolved.
- The user knows the invocation form and where every file landed.
