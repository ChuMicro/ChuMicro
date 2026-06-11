# Spec — Triggering-reader scope

Body-structure, per-step annotation, patterns-to-avoid, and stance rules for skill authors.  The cold-walk lens in `.github/skills/_shared/audit_wf.js` carries a condensed version of these rules; when this file changes materially, re-check that lens prompt.

For frontmatter rules see [`spec-loader-reader.md`](spec-loader-reader.md).  For sibling-overlap and reference-file rules see [`spec-sibling-author.md`](spec-sibling-author.md).  For general authoring guidance see [`spec.md`](spec.md).

## Table of contents

- [Body structure rules](#body-structure-rules) — length · ordering · headings · narrative · walkability · lifecycle · ultrathink
- [Per-step annotation discipline](#per-step-annotation-discipline)
- [Patterns to avoid](#patterns-to-avoid)
- [Stance toward the reading agent](#stance-toward-the-reading-agent)

---

## Body structure rules

### Length

- Target ≤500 lines for the SKILL.md body.  Past that the reading agent skims, and a partial-read with `head` / `offset` misses the back half.
- When the body wants to grow past 500, factor reference files (one hop deep).  Reference files load on demand from body links.

### Section ordering

For **action / procedural** skills (audit, run, generate), the recommended ordering is:

1. **One-paragraph intro** — what the skill is, who calls it, what the deliverable is.  No narrative preamble.
2. **Scope** or **When to use this skill** — bullets of in-scope cases, and a *Don't use for* list.
3. **Definition of done** — verifiable criteria the agent uses to know the skill ran correctly.
4. **Process** — numbered steps with per-step annotations.
5. **Output format** — text or table the skill produces.
6. **Red flags / Don'ts** — failure modes to recognize.
7. **Done when** — observable end state (distinct from the last Process step).

For **interview / generation** skills (this skill, `new-decision`, `init`):

1. One-paragraph intro.
2. When to use this skill.
3. Invocation forms.
4. Modes (interview vs spec-in, etc.).
5. Process — phases with per-step annotations.
6. What to include / What to leave out.
7. Red flags.
8. Done when.

For **reference / cookbook** skills (patterns docs, design guides):

1. One-paragraph intro.
2. When to use this skill.
3. Topic tables with When-to-use / What-to-expect columns.
4. Worked examples.

### Heading depth

- H1 — title (one per file).
- H2 — top-level sections.
- H3 — subsections.
- H4 — rare.  If a body has H5+, the structure is over-nested; refactor.

### Procedure-first vs narrative-first

Bury narrative.  Skill bodies are read by an agent mid-task — they want the procedure top-to-bottom.  *"In this skill we will explore how to…"* / *"This skill covers many aspects of…"* are stripped without a second look.

### Rule-first vs example-first

State the rule with its reasoning before the example.  *Good / bad* contrasts that leave the principle implicit force the reader to reverse-engineer it from the example — two hops where one suffices.

### Linear walkability

The Process steps go top-to-bottom.  A step that says *"first do what Step 5 says"* is a re-order bug, not procedure.

### Skill content lifecycle

When a skill is invoked, the rendered SKILL.md content enters the conversation **as a single message** and stays for the rest of the session.  Claude Code does not re-read the file on later turns.  Write standing instructions, not one-time steps.

**Compaction behavior.**  Under auto-compaction, the most recent invocation of each skill is re-attached after the summary.  Each re-attached skill is capped at 5,000 tokens; combined budget across all re-attached skills is 25,000 tokens.  Claude fills the budget starting from the most recently invoked skill, so older skills can drop entirely.  If a skill stops influencing behavior after compaction, re-invoke it.

### `ultrathink` keyword

To request deeper reasoning when the skill runs, include the literal word `ultrathink` anywhere in the skill content.  Triggers the model's extended reasoning for that invocation.

---

## Per-step annotation discipline

Every step in the Process section carries these annotations:

| Annotation | Requirement | Notes |
|---|---|---|
| **Success criteria** | Required on every step | One observable artifact or assertion that proves the step is done. *"Do X"* is not enough; *"Do X; confirm `<file>` exists at `<path>`"* is. |
| **Execution** | Optional, conditional | Default is `Direct`. Other values: `Task agent` (subagent dispatch), `Teammate` (true-parallel teammate), `[human]` (user does it). Mark only when not Direct. |
| **Artifacts** | Conditional | When a later step needs data this step produces (PR number, file path, commit SHA), name the artifact here. |
| **Human checkpoint** | Conditional | For irreversible actions (merging, sending messages, committing), error judgment (merge conflicts), or output review. Pause and confirm with the user. |
| **Rules** | Conditional | Hard rules for the workflow. User corrections during the interview are especially load-bearing here. |

Steps with success criteria like *"the step is complete"* are tautological.  Push back.

A criterion must also **discriminate** — a clearly-wrong run must fail it.  *"Report generated"* passes when the report is empty; *"a test was added"* passes when the test asserts nothing.  A non-discriminating criterion is worse than none, because it manufactures false confidence.  Name the property that separates success from a hollow pass: *"report lists ≥ 1 finding per dimension, or states a clean pass per dimension"*, *"the added test fails when the fix is reverted."*

---

## Patterns to avoid

These are patterns that read as completed work but signal nothing to a cold-reading agent.  Avoid them in the first draft; if one slips in, the cold-walk catches it.  The point is **don't write these**, not "write them and audit afterward."

### Anti-self-assertions

*"I have read all the rules"*, *"always follow these guidelines"*, *"I will not skip steps"*.  Known failure mode: the assertion reads to the agent as completed work, so it skips the actual rule.  Don't write them; state the rule directly with its reasoning.

### Dated phrasing

*"As of 2026-05-26"*, *"in the current release"*, *"before the August migration"*.  Skills outlive their dates.  Name the condition that was true at the time (*"on CircuitPython 9.x"*, *"after the 2.1.119 schema change"*) — that survives the calendar.

### First-person plural

*"We run X"*, *"our convention"*.  The reading agent isn't a co-author.  Write imperative — *"Run X"*, *"The convention is X"*.

### Defensive hedging

*"Should usually work"*, *"may handle the common cases"*.  Either name the conditions explicitly or drop the hedge.  Hedging tells the reading agent *"I don't know when this fires"* — which is rarely the impression you want.

### Moralizing imperatives

*"Be careful when…"*, *"remember to always…"*, *"don't forget that…"*.  Empty scaffolding.  Write the rule.

### Voodoo constants

Magic numbers / paths in procedural snippets without a why.  *"Run with `--timeout 47`"* without an explanation of why 47 is the right number.  Annotate (*"`--timeout 47` — measured P95 on the slowest stage; bump if a new stage lands"*) or drop the constant.

### Time-sensitive promises

*"The new behavior is…"*.  The reader doesn't know which behavior is new without dates.

### AI-tic vocabulary

The standing ban list — words that signal generic AI prose, not concrete engineering:

```
canonical | idempotent | comprehensive | seamless | robust | cutting-edge |
best-in-class | leverage | intuitive | elegant | streamlined | battle-tested |
first-class | one-stop | out of the box | worth noting | dive into |
let's explore | effortless | painless | empowers | harness | unleash |
by construction | under the hood | got you covered | simply put | in essence |
magic | powerful
```

Plus `shape` / X-shaped compounds (this repo's specific rule).

Avoid these in your draft.  If one shows up during writing, replace it with the concrete verb or noun the sentence actually needs.

---

## Stance toward the reading agent

A SKILL.md is read by an agent mid-task.  Mechanical sweeps catch tic-level failures; stance-level failures look fine line-by-line and fail the cold-read test.

Common shapes that fail (defensive hedging and moralizing imperatives also live in *Patterns to avoid* above; the three below need stance-level — not mechanical — detection):

- **Apologetic scope notes.**  *"We know this skill doesn't cover X, but…"* — apologizing for bounds steals attention.  State scope plainly.
- **Step-by-step narration of self-evident agent actions.**  *"First, identify the file.  Then read it.  Then look for X."* over *"Read the file and check for X."* — the agent can sequence.
- **Over-cautious checkpointing.**  *"Pause and verify with the user before continuing"* on every step turns the skill into a polling loop.  Reserve checkpoints for genuinely user-owned decisions.

The fix: write to a capable practitioner.  State what to do and what the exit condition is.  If a check is load-bearing, name what's being checked and why.  Trust the agent to handle the routine; flag only the non-obvious.
