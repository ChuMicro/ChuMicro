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

### 1. Determine the next number

```bash
ls plans/decisions/ | grep -E '^[0-9]' | tail -1
```

Take the last number and add 1. Pad to 4 digits.

### 2. Create the file

Filename: `plans/decisions/NNNN-<slug>.md`

The slug should be 2-4 words, lowercase, hyphenated. Examples:
- `0022-settings-storage-format.md`
- `0023-nvm-backend-api.md`

### 3. Write the content

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
| `revised` | Updated in-place (note the revision date) |
| `deferred` | Evaluated but not yet decided |

### 4. Cross-reference

If the decision affects rules in `AGENTS.md`, update the relevant section there. Common touchpoints:

- **Quick reference / hard rules** — new constraints agents must follow
- **Common pitfalls** — new mistakes to warn about
- **Testing strategy** — changes to test patterns
- **Memory & performance** — new embedded code patterns

If the decision affects an existing decision, add a note to the old one:

```markdown
> **Note:** See also [Decision NNNN](NNNN-slug.md) which extends/revises this.
```

### 5. Verify

- [ ] File exists at `plans/decisions/NNNN-<slug>.md`
- [ ] Number is sequential (no gaps, no duplicates)
- [ ] Has all three sections: Context, Decision, Consequences
- [ ] Status, date, and Related field are present
- [ ] `AGENTS.md` updated if the decision adds hard rules or pitfalls
- [ ] Referenced from related decisions if applicable
- [ ] If the decision resolves an open question, update `plans/open-questions.md`

## Style notes

- Keep it brief. A decision record is 20-60 lines, not a design document.
- Write in present tense ("Libraries must..." not "Libraries should...").
- Include code snippets only when they clarify a contract or API.
- Name the alternatives that were considered and why they were rejected — this is the most valuable part for future readers.
