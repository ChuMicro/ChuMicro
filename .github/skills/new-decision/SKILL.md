---
name: new-decision
description: How to create a new decision record in plans/decisions/. Use this skill when a structural, pattern, or tooling tradeoff needs to be recorded.
---

# New Decision

Decision records capture *why* the workspace has its current shape. Create one when a tradeoff is made that future agents or contributors would otherwise have to rediscover.

## When to create a decision

- A structural change affects how libraries, tests, or tooling work.
- A pattern is established that all libraries should follow.
- An approach was evaluated and rejected (prevents re-discovery).
- A tool or dependency choice was made with meaningful alternatives.

**Don't create a decision for:** bug fixes, routine features, or changes that don't affect other libraries or the workspace contract.

## Procedure

### 1. Check for conflicts with existing decisions

Before drafting the new ADR's body, grep `plans/decisions/` for any ADR that touches the same primitive — the same cross-library contract, the same shared enum, the same callback signature, the same protocol semantic, the same dimension of an already-decided tradeoff. If one exists, **read it before locking the new design**, and either:

- Make the new decision *consistent* with the existing contract (the common case), and cite the existing ADR in `Related:`; or
- Acknowledge the conflict and choose between (a) amending the existing ADR in place, (b) marking the existing one `superseded`, or (c) narrowing the new decision's scope so the conflict disappears.

A conflict you don't notice during planning becomes a conflict your design encodes. The fix lands much later, costs more, and often involves a partial reversal of the new decision — exactly what writing the ADR was supposed to prevent. See [field-reality.md](field-reality.md) for the incident that motivated this step.

Quick conflict-search recipe — adapt to the primitive you're deciding:

```bash
# By name of the primitive (callback, enum, kwarg, exception class):
grep -rl "<primitive-name>" plans/decisions/

# By recent ADRs touching the same library or seam:
ls -t plans/decisions/ | head -20

# Cross-library contracts (anything specifying behavior across two+ libraries):
grep -l "cross-library\|cross-lib\|shared contract" plans/decisions/
```

### 2. Determine the next number

```bash
ls plans/decisions/ | grep -E '^[0-9]' | tail -1
```

Take the last number and add 1. Pad to 4 digits.  Dead-record
filename markers (Decision 0076) go *after* the `NNNN-` prefix, so
this recipe stays correct even when superseded / inert ADRs have been
renamed — the highest number still sorts last.

### 3. Create the file

Filename: `plans/decisions/NNNN-<slug>.md`

The slug should be 2-4 words, lowercase, hyphenated. Examples:
- `0022-settings-storage-format.md`
- `0023-nvm-backend-api.md`

### 4. Write the content

Use this template:

```markdown
# Decision NNNN: <Title>

Status: `accepted`
Date: `YYYY-MM-DD`
Related: <!-- Decision numbers, open questions, or "none" -->

## Context

<!-- 2-4 sentences. What problem or question triggered this decision?
     What constraints exist? Reference other decisions if relevant. -->

## Decision

<!-- What was decided. Be concrete — name the pattern, the API, the tool.
     Include code snippets if they clarify the contract.
     Use subsections if the decision has multiple parts. -->

## Consequences

<!-- What follows from this decision. What must change? What becomes easier
     or harder? What new constraints exist? -->
```

### Status values

| Status | Meaning |
|---|---|
| `proposed` | Written up for review — not yet committed to |
| `accepted` | Active and enforced |
| `superseded` | Replaced by a newer decision (link to it) |
| `deferred` | Evaluated but not yet decided |

These four are the entire enum.  No `in-progress`, no `partial`, no `shipped`, no `revised` — see [`plans/decisions/README.md`](../../../plans/decisions/README.md) for why.  An ADR whose body has been edited to reflect a changed reality is still `accepted`; edits don't bump it to a fifth state.

### 5. Cross-reference

If the decision affects rules in `AGENTS.md`, update the relevant section there. Common touchpoints:

- **Quick reference / hard rules** — new constraints agents must follow
- **Common pitfalls** — new mistakes to warn about
- **Testing strategy** — changes to test patterns
- **Memory & performance** — new embedded code patterns

If the new decision extends, narrows, or partially supersedes an existing one, **edit the affected paragraphs of the older ADR in place** so a cold reader gets the current rule, and cross-link the new decision inline (e.g. `... — see [Decision NNNN](NNNN-slug.md)`).  Do not add a `> **Note:** See also Decision NNNN ...` blockquote at the head of the older ADR — that pattern is forbidden by the README.  If the change is too large to absorb without distorting the original reasoning, mark the old ADR `superseded` instead and write a fresh one.

When you mark an older ADR `superseded` — or it goes inert (a one-time / bootstrap decision whose every consequence has shipped) — apply the dead-record filename marker from [Decision 0076](../../../plans/decisions/0076-archive-dead-decisions-in-filename.md): rename `NNNN-<slug>.md` to `NNNN-SUPERSEDED-BY-MMMM-<slug>.md` (replaced) or `NNNN-INERT-<slug>.md` (inert, `Status:` stays `accepted` + add an `Archived: inert — <why>` field), then `grep -rn` the old basename and fix the one or two inbound filename links.  Use `git mv` so history follows.  CHU019 fails the build if status, marker, and field disagree.

### 6. Edit the body in place

This rule from [`plans/decisions/README.md`](../../../plans/decisions/README.md) is load-bearing — the difference between an ADR that helps future contributors and one that misleads them.  When a decision changes, rewrite the affected paragraphs of the existing ADR so a reader landing cold gets accurate information.  Specifically:

- **No dated revision banners** (no `Revised: YYYY-MM-DD — ...`).  Edit the prose; let `git log` carry history.
- **No `## Amendments` / `## Update (YYYY-MM-DD)` / `## Progress notes` sections.**  Status updates belong in commit messages or `plans/workstreams/<name>.md`.
- **No "this decision has been revised twice" preambles.**  If you find yourself writing one, stop and edit the body.
- **The `Date:` field is the original decision date.**  Never parenthesize it (`Date: 2026-04-21 (revised 2026-05-02)`).
- **No "Amended by Decision NNNN" blockquotes** — as covered in step 5, use inline cross-links instead.

The README is the source of truth for these rules; mirror its language when in doubt.

### 7. Verify

- [ ] File exists at `plans/decisions/NNNN-<slug>.md`
- [ ] Number is sequential (no gaps, no duplicates)
- [ ] Has all three sections: Context, Decision, Consequences
- [ ] Status, date, and Related field are present
- [ ] `AGENTS.md` updated if the decision adds hard rules or pitfalls
- [ ] Referenced from related decisions if applicable
- [ ] If the decision resolves an open question, update `plans/open-questions.md`
- [ ] If the decision encodes a requested constraint, the rule states the invariant — not the mechanism that prompted it

### 8. Close out

Follow the [`task-checkpoint`](../task-checkpoint/SKILL.md) skill — preflight, refresh `plans/next-up.md`, then commit + push via the [`git-commit`](../git-commit/SKILL.md) skill.  The ADR is a unit of work; it earns its `## Done (recent)` entry like any other.

## Style notes

- Keep it brief. A decision record is 20-60 lines, not a design document.
- Write in present tense ("Libraries must..." not "Libraries should...").
- Include code snippets only when they clarify a contract or API.
- Name the alternatives that were considered and why they were rejected — this is the most valuable part for future readers.
- **State the principle, not the mechanism.** When the decision encodes a constraint someone asked for, the rule sentence must name the invariant, not the implementation that motivated it ("no CLI may materialize a workspace", not "no pip-installed scaffolder"). A `Rejected:` bullet that sets aside the stricter thing actually requested, for convenience, is the narrowing happening in real time — challenge it before the ADR lands. Source of truth + the worked cautionary case (Decision 0038's `init`): [`plans/decisions/README.md`](../../../plans/decisions/README.md).
