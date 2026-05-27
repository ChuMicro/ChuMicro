# Spec — Sibling-author scope

Reading-rule, reference-file-layout, and MCP-tool-naming rules the sibling-author cold-walk persona judges against.  When this file changes, [`.claude/agents/new-skill-sibling-author.md`](../../.claude/agents/new-skill-sibling-author.md) changes in lockstep.

For frontmatter rules see [`spec-loader-reader.md`](spec-loader-reader.md).  For body-structure rules see [`spec-triggering-reader.md`](spec-triggering-reader.md).  For general authoring guidance see [`spec.md`](spec.md).

## Table of contents

- [The reading rule](#the-reading-rule--non-negotiable)
- [Reference-file layout](#reference-file-layout)
- [MCP tool references — fully-qualified](#mcp-tool-references--fully-qualified)

---

## The reading rule — non-negotiable

When writing a new skill, you (the agent driving `/new-skill`) **MUST NOT** Read any existing SKILL.md, persona, or reference file from another skill in this tree.  The only files you may consult while writing are:

- This file and the other `spec-*.md` files in this directory
- The new-skill SKILL.md
- [`interview.md`](interview.md), [`template.md`](template.md), [`examples.md`](examples.md) inside the new-skill directory
- The user's answers during the interview

**Narrow exception:** the sibling-overlap check (Process step 1b in the new-skill SKILL.md) reads ONLY the `description:` line of each sibling — never the body, never the persona files, never the reference files.  Description-line scan is for trigger-routing comparison; nothing else.

Existing skills may carry drift that the new skill is meant to escape.  Reading any part of them imports that drift.  Even patterns labeled *"abstract"* in another skill's body carry the framing of that skill's job.  When the new skill's job is different, those framings are wrong — and the agent that read them won't notice they're wrong.

---

## Reference-file layout

When a SKILL.md needs to factor content out:

- Reference files live **inside the skill directory** (`<skill-dir>/<file>.md`).
- One hop deep only — no `<skill-dir>/refs/details.md`.  The triggering agent has a context budget and follows one link, not two.
- Files > 100 lines need a table of contents at the top.
- Cross-link with relative paths — `[interview.md](interview.md)`, not full repo paths.
- A reference file that has grown past 500 lines is itself a candidate for further splitting.

Common reference files:

| File | Purpose |
|---|---|
| `interview.md` | Deep question bank, pushback patterns, phase-by-phase guides — for interview-style skills. |
| `spec.md` (+ `spec-*.md`) | Rules / criteria the skill enforces — for skills whose job is to evaluate other artifacts against a standard. Split by persona-mirror boundary when a single spec file grows past the splitting threshold. |
| `template.md` | Starter skeleton the skill emits — for generation skills. |
| `examples.md` | One or two worked walkthroughs end-to-end. |
| `field-reality.md` | Incidents that motivated the skill's existence — for skills whose rules need an incident trail. |
| `scripts/` | Bundled executable scripts for action skills.  Entry-point file names match the job (`driver.<ext>`, `smoke.sh`, `validate.py`). |

---

## MCP tool references — fully-qualified

If the skill uses MCP tools, always write the fully-qualified name:

```
Use the BigQuery:bigquery_schema tool to retrieve table schemas.
Use the GitHub:create_issue tool to create issues.
```

Format: `ServerName:tool_name`.  Without the server prefix, Claude may fail to locate the tool when multiple MCP servers are configured.
