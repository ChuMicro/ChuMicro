# Worked Example — Interview to SKILL.md

A synthetic walkthrough of `/new-skill` from a vague user ask through the eleven interview phases to the final files on disk.  The example is constructed to show pushback in action, not lifted from a real session.

## Table of contents

- [The user opens with](#the-user-opens-with) — the vague ask
- Interview phases:
  - [Phase 0 — Pre-flight](#phase-0--pre-flight) (artifact-type routing, job-type sort)
  - [Phase 1 — Trigger discovery](#phase-1--trigger-discovery) (three example messages)
  - [Phase 2 — Scope boundary](#phase-2--scope-boundary) (in / out / adjacent)
  - [Phase 3 — Audience and context](#phase-3--audience-and-context) (inline vs fork)
  - [Phase 4 — Frontmatter draft](#phase-4--frontmatter-draft) (description + name)
  - [Phase 5 — Sibling-overlap check](#phase-5--sibling-overlap-check)
  - [Phase 6 — Procedure form](#phase-6--procedure-form) (driver vs prose)
  - [Phase 7 — Steps + per-step annotations](#phase-7--steps--per-step-annotations)
  - [Phase 8 — Arguments and tools](#phase-8--arguments-and-tools)
  - [Phase 9 — Citations and incident trail](#phase-9--citations-and-incident-trail)
  - [Phase 10 — Cold-walk against three readers](#phase-10--cold-walk-against-three-readers)
  - [Phase 11 — Show, confirm, write](#phase-11--show-confirm-write)
- Produced files:
  - [Final SKILL.md — YAML Audit](#yaml-audit) (the file that lands on disk)
- [What this example illustrates](#what-this-example-illustrates) (interview lessons recap)

---

## The user opens with

> "I want a skill that helps me deal with all my YAML files."

`/new-skill` (no args, no `--spec`) fires.

---

## Phase 0 — Pre-flight

`AskUserQuestion` Q0a fires:

> **What's the rough job this skill should do?**
> - Audit / scan / lint something
> - Generate / create something
> - Run / drive / verify something
> - Reference / cookbook

User picks: **Audit / scan / lint something.**

Mode: interview.  Slug candidate: none.  Job type: audit.

---

## Phase 1 — Trigger discovery

`AskUserQuestion` Q1a:

> **Give me three example user messages that should fire this skill.**

User types into "Other": *"check my YAML"*.

**Pushback.**  *"That's one example.  I need three.  Give me two more — phrasings a user would actually type."*

User adds: *"lint the YAML in this repo"* and *"is my docker-compose valid?"*.

`AskUserQuestion` Q1b restates:

> **To confirm — the skill should fire on (1) "check my YAML", (2) "lint the YAML in this repo", (3) "is my docker-compose valid?". Is anything missing?**
> - Yes — that covers it
> - Add a fourth example
> - Drop one — that's actually a different skill

User picks: *Drop one — "is my docker-compose valid?" is actually a different skill.*

**Pushback.**  *"That second one names a specific tool — docker-compose validation has its own validator and probably wants its own skill.  Dropping it tightens the scope.  Confirming the trigger set is (1) and (2)?"*

User: *Yes.*

**Exit artifact.**  Trigger messages: `["check my YAML", "lint the YAML in this repo"]`.

---

## Phase 2 — Scope boundary

`AskUserQuestion` Q2a:

> **Name two things this skill should NOT do.**

User: *"Not sure yet."*

**Pushback.**  *"Then it's probably too broad.  Looking at the trigger messages — both are about YAML quality.  Should the skill also: (a) edit YAML files, (b) generate YAML from a schema, (c) compare two YAML files, (d) deploy YAML configs?  Each of those is a different skill.  Pick what's OUT."*

User: *All of those are out.  Just audit / lint.*

**Q2b — adjacent task:**

User: *"There might be a future YAML-fixer skill but it doesn't exist yet."*

**Exit artifact.**  In-scope: audit / lint YAML files in the repo.  Out: editing, generating, comparing, deploying.  Adjacent: a future YAML-fixer.

---

## Phase 3 — Audience and context

Q3a — caller: **User types `/yaml-audit` directly.**

Q3b — context: **Inline (default) — the user wants to see findings as they surface and pick which to fix.**

Q3c — conversation dependence: **Fresh.**

**Exit artifact.**  Caller: user-invoked slash command.  Context: inline.  Fresh.

---

## Phase 4 — Frontmatter draft

Q4a — slug:

> **I suggest `yaml-audit` as the slug.  It'll invoke as `/yaml-audit`.**

User accepts.

Q4b — description draft:

> Read this description aloud:
>
> ```
> description: Audit YAML files in the repository for syntax errors, schema violations, and common smells (trailing whitespace, inconsistent indentation, duplicate keys). Produces a punch-list of findings ranked by severity. Use when the user wants to check, lint, or validate YAML across the repo. Examples: "check my YAML", "lint the YAML in this repo", "is my CI config valid YAML?".
> ```

Trigger test:

- *"check my YAML"* → matches *check* + *YAML*.  ✓
- *"lint the YAML in this repo"* → matches *lint* + *YAML* + *repo*.  ✓

User: *"Looks good but it's a bit long."*

**Pushback.**  *"The triggering portion is ~340 chars — under the ~400 budget.  The examples push it higher but the loader matches against examples, so they earn their place.  Want to trim, or leave as-is?"*

User: *Leave as-is.*

**Exit artifact.**  Description locked.

---

## Phase 5 — Sibling-overlap check

The pre-flight from the SKILL.md procedure surfaced these descriptions in the same tree (names abstracted for this illustration):

- `<sibling-A>`: *"Audit a user-facing markdown doc for cold-reader readability…"*
- `<sibling-B>`: *"Code-quality audit on a single library…"*
- `<sibling-C>`: *"Audit one SKILL.md…"*

**Stem-word search isn't enough.**  Two skills sharing the word *audit* (hypothetically) is not real overlap — the loader matches against the full description line, not stem words.  Read each sibling's full description and ask: *"Would the trigger messages from Phase 1 plausibly route to this sibling instead of the new skill?"*

Walking the three trigger messages against each hypothetical sibling description:

- *"check my YAML"* vs `<sibling-A>` *("Audit a user-facing markdown doc for cold-reader readability…")*: the sibling description names *markdown doc* explicitly — no match.  ✓
- *"check my YAML"* vs `<sibling-B>` *("Code-quality audit on a single library…")*: the sibling names *library* — no match.  ✓
- *"lint the YAML in this repo"* vs each sibling: same logic; no match.  ✓

No real overlap surfaces.  Skip the disambiguation pass.

If the trigger messages *had* matched a sibling description, the disambiguation question would have been:

> **Trigger message #N would also match `<sibling>`.  Disambiguate?**
> - Tighten the new description to exclude `<sibling>`'s scope
> - Extend `<sibling>` to also handle this case — don't build a new skill
> - Build both with a *Do NOT use* clause in each

**Exit artifact.**  No overlap with siblings; new description stands.

---

## Phase 6 — Procedure form

Q6a:

> **What does the skill *do* in one sentence?**

User: *"Reads YAML files and produces a punch-list."*

Q6b — existing tool:

> **Is there an existing CLI / script that already does this?**

User: *"`yamllint` exists.  We'd use it."*

**Exit artifact.**  Pure prose + `yamllint` driver.  Wraps an existing CLI.

---

## Phase 7 — Steps + per-step annotations

`AskUserQuestion` Q7a:

> **Walk me through one representative invocation end-to-end.**

User: *"Find all the YAML files.  Run yamllint on them.  Sort findings.  Show me the punch-list.  Fix the high-confidence ones with my OK."*

Draft procedure:

1. Find YAML files (`find . -name '*.yaml' -o -name '*.yml'`)
2. Run `yamllint` against each
3. Parse and group findings by severity
4. Show punch-list to user
5. Apply fixes for high-confidence findings after user OK

Per-step probes:

**Step 1 — Success criteria:**

User: *"There's a list of files."*

**Pushback.**  *"How many?  None is a valid output too — the user has no YAML.  Be specific."*

User: *"A list of file paths, possibly empty.  If empty, the skill says so and exits."*

**Step 1 final:** Success criteria: *"`find` returns a list of YAML file paths (possibly empty). If empty, the skill prints `No YAML files found.` and exits."*

**Step 2 — Success criteria:** *"`yamllint` exits with a parseable output for each file."*

**Step 3 — Success criteria:** *"Findings grouped by yamllint's native severity levels (whatever yamllint reports — the skill doesn't invent its own taxonomy)."*

**Step 4 — Success criteria + Human checkpoint:** *"Punch-list printed in chat with `<path>:<line>: <severity> <message>` rows; the skill pauses for the user to pick which findings to fix."*

**Step 5 — Success criteria + Human checkpoint:** *"Each user-selected fix applied as an `Edit` operation; user confirmed via `AskUserQuestion` before any write."*

Q7c — Done-when:

User: *"The skill is done when the punch-list is shown and fixes are applied."*

**Pushback.**  *"That's just step 5.  Done-when describes the state, not the action.  What's the observable end-state?  E.g. 'punch-list rendered, all chosen fixes applied, repo re-`yamllint`-clean for the fixed files'."*

User: *Yes, that's the state.*

**Exit artifact.**  Five-step procedure with annotations + observable Done-when.

---

## Phase 8 — Arguments and tools

Q8a — arguments:

User: *"Maybe a `--path` to scope to a subdirectory."*

`argument-hint: "[--path <dir>]"`

Q8b — tools:

```yaml
allowed-tools:
  - Read
  - Edit
  - Glob
  - Bash(find *)
  - Bash(yamllint *)
  - AskUserQuestion
```

Q8c — invocation policy: *"It edits files.  Make it user-only — `disable-model-invocation: true`."*

**Exit artifact.**  Final frontmatter ready.

---

## Phase 9 — Citations and incident trail

Extracted absolutes from the draft:

- *"Always print the punch-list before applying fixes."*

> **Rule: *"Always print the punch-list before applying fixes."* What's the source?**
> - ADR / decision file
> - Incident
> - Three prior observations
> - No source — soften to a guideline
> - Drop the rule

User: *"It's just good practice — show before fixing."*

**Pushback.**  *"That's the Human checkpoint pattern, which the per-step annotation already encodes.  We don't need to also state it as an absolute rule — the step annotation covers it.  Drop the standalone rule?"*

User: *Yes, drop.*

**Exit artifact.**  Rule removed; the Human checkpoint annotation on Step 4 carries the same intent without an extra absolute.

---

## Phase 10 — Cold-walk against three readers

**Loader agent.**  Reads the `description:` line.  No vague stem, names *what* + *when*, includes verbs the trigger messages use.  ✓

**Triggering agent.**  Opens the body cold.

- Process steps numbered.  ✓
- Each step has Success criteria.  ✓
- Done-when present.  ✓
- Arguments documented (`--path`).  ✓
- `yamllint` is named in `Bash` allowed-tools.  ✓

One gap: the body doesn't say what `yamllint` config to use.  Default behavior?  Project-local?

`AskUserQuestion`:

> **Cold-walk finding: the body doesn't say how to choose the `yamllint` config (default vs project-local `.yamllint`).  Address?**
> - Add a step that checks for `.yamllint` first, falls back to defaults
> - Document as a known gap; agent uses defaults
> - I'll write a Rule on Step 2 covering it

User: *Add a step.*

Draft Step 1.5: *"Look for `.yamllint` in the repo root.  If present, pass `-c .yamllint` to `yamllint`.  Otherwise use defaults."*

**Sibling-skill author.**  No overlap that wasn't already addressed in Phase 5.

**Exit artifact.**  One gap surfaced, one new step added.

---

## Phase 11 — Show, confirm, write

The proposed `.github/skills/yaml-audit/SKILL.md`:

```yaml
---
name: yaml-audit
description: Audit YAML files in the repository for syntax errors, schema violations, and common smells (trailing whitespace, inconsistent indentation, duplicate keys). Produces a punch-list of findings ranked by severity. Use when the user wants to check, lint, or validate YAML across the repo. Examples: "check my YAML", "lint the YAML in this repo", "is my CI config valid YAML?".
allowed-tools:
  - Read
  - Edit
  - Glob
  - Bash(find *)
  - Bash(yamllint *)
  - AskUserQuestion
when_to_use: |
  Use when the user wants to check, lint, or validate YAML files in this repository.
  Trigger phrases include "check my YAML", "lint YAML", "validate YAML", "yaml audit".
  Do NOT use to audit markdown docs or non-YAML configuration — name the adjacent skill responsible for those if one exists in this tree.
argument-hint: "[--path <dir>]"
arguments:
  - --path
disable-model-invocation: true
---

# YAML Audit

Audit YAML files in the repository for syntax errors, schema violations, and style smells.  Produces a punch-list grouped by severity (HIGH / MEDIUM / LOW), then offers to apply HIGH-confidence fixes with user sign-off per finding.

## Definition of done

You are done when **all** of these are true:

1. Every YAML file under the audit scope was passed through `yamllint`.
2. The punch-list was printed in chat.
3. For each fix offered to the user, the user either confirmed via `AskUserQuestion` and the fix was applied, or the user declined and the file is unchanged.
4. The repo is `yamllint`-clean for the files where fixes were accepted.

## Process

### 1. Find YAML files

```bash
find ${PATH_ARG:-.} -name '*.yaml' -o -name '*.yml'
```

**Success criteria:** `find` returns a list of YAML file paths (possibly empty).  If empty, print `No YAML files found.` and exit.

### 2. Pick the yamllint config

Check for `.yamllint` in the repo root.

**Success criteria:** `YAMLLINT_CONFIG_FLAG` is set to `-c .yamllint` if the file exists, otherwise empty.

### 3. Run yamllint

```bash
yamllint $YAMLLINT_CONFIG_FLAG <files>
```

**Success criteria:** `yamllint` exits with parseable output for each file.

### 4. Parse and group findings

**Success criteria:** Findings grouped into HIGH (syntax errors), MEDIUM (schema violations), LOW (style smells), each row in `<path>:<line>: <severity> <message>` form.

### 5. Show punch-list and ask user

**Success criteria:** Punch-list printed in chat; `AskUserQuestion` fired offering to fix HIGH-confidence findings.

**Human checkpoint:** the user picks which findings to fix.

### 6. Apply fixes

For each finding the user accepted, apply the fix via `Edit`.

**Success criteria:** Each chosen fix applied; the touched files re-run cleanly through `yamllint` for the rule that was flagged.

**Human checkpoint:** confirm before each write — irreversible without `git`.

## Output format

```
HIGH    <path>:<line>: <message>
MEDIUM  <path>:<line>: <message>
LOW     <path>:<line>: <message>
```

## Don'ts

- **Don't apply fixes without the user's per-finding sign-off.**  YAML edits are easy to get wrong; one round-trip per write is cheap insurance.
- **Don't widen the scope beyond YAML files.**  JSON / TOML / INI are out — they have their own validators.

## Done when

- The punch-list was rendered.
- Every chosen HIGH-confidence fix is applied.
- The user has seen the final state.
```

Summary header in chat:

```
New skill: .github/skills/yaml-audit/

Slug:         yaml-audit
Description:  Audit YAML files in the repository for syntax errors,
              schema violations, and common smells…
Trigger test: "check my YAML"           ✓
              "lint the YAML in this repo" ✓
              "is my CI config valid YAML?" ✓

Files to write:
  SKILL.md      (94 lines)

Cold-walk findings fixed in this draft: 1
AI-tic hits stripped in this draft: 0
Sibling-overlap candidates considered: 3

Save?
```

`AskUserQuestion` confirms.  Files land at `.github/skills/yaml-audit/SKILL.md`.

Closing line:

```
Skill written: .github/skills/yaml-audit/SKILL.md
Invoke as: /yaml-audit [--path <dir>]
Edit the SKILL.md directly to refine — re-run /new-skill to author a sibling.
```

---

## What this example illustrates

- **Pushback works.**  The user opened with *"all my YAML files"* — too broad.  Phase 1 surfaced two real triggers and a third that was a different skill.  Phase 2 nailed down explicit exclusions.
- **Sibling-overlap is description-line matching, not stem-word matching.**  Several hypothetical siblings used the word *audit*; reading their full descriptions showed each named a different target.  No real overlap surfaced — the stem alone would have produced false positives.
- **The cold-walk catches what the mechanical sweep misses.**  No mechanical check would have flagged "the body doesn't say which yamllint config to use" — only a cold reader simulating the trigger does.
- **Absolutes earn their place.**  *"Always print before fixing"* sounded reasonable but the per-step Human checkpoint already covered it.  The rule was dropped, not added.
- **One step gets added during cold-walk.**  Procedures grow during the audit; that's the audit doing its job.
