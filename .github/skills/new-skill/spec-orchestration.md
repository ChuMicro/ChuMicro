# Spec — Agent and orchestration patterns

When a skill does its work through sub-agents.  Three architectures dominate, plus one anti-pattern to recognize.  This file names where to put what and when each pattern earns its complexity.

Not mirrored to a cold-walk persona — this is authoring guidance for skill writers.  Frontmatter, body, and references rules live in [`spec-loader-reader.md`](spec-loader-reader.md), [`spec-triggering-reader.md`](spec-triggering-reader.md), and [`spec-sibling-author.md`](spec-sibling-author.md).  General author guidance and reusable patterns live in [`spec.md`](spec.md).

## Table of contents

- [File locations](#file-locations) — where the skill and the personas live
- [Custom subagent frontmatter contract](#custom-subagent-frontmatter-contract)
- [Persona body — what to write](#persona-body--what-to-write)
- [Plugin subagent restrictions](#plugin-subagent-restrictions)
- [When to write a custom persona vs use general-purpose](#when-to-write-a-custom-persona-vs-use-general-purpose)
- [Pattern 1 — Single fork](#pattern-1--single-fork)
- [Pattern 2 — Director (sequential blindness, for generation workflows)](#pattern-2--director-sequential-blindness-for-generation-workflows)
- [Pattern 3 — Parallel dispatch](#pattern-3--parallel-dispatch) — 3a batch · 3b second-opinion
- [Pattern 4 — Skill-of-skills](#pattern-4--skill-of-skills)
- [Anti-pattern — Two agents pretending to be a director pattern](#anti-pattern--two-agents-pretending-to-be-a-director-pattern)
- [Hook vs skill — the routing question](#hook-vs-skill--the-routing-question)

---

## File locations

| File | Where | Purpose |
|---|---|---|
| Skill (the director / orchestrator) | `.claude/skills/<slug>/SKILL.md` or `~/.claude/skills/<slug>/SKILL.md` | The procedure the user invokes |
| Custom subagent persona | `.claude/agents/<agent-name>.md` or `~/.claude/agents/<agent-name>.md` | Loaded by the harness as the subagent's system prompt when the skill dispatches with `subagent_type: <agent-name>` |

Subagent directories are scanned **recursively**, so you can organize personas into subfolders (e.g. `agents/review/`, `agents/research/`).  Subfolders do NOT affect identity — only the `name` frontmatter field does.  Keep `name` values unique across the whole tree; conflicts are resolved silently.

**Loading caveat:** subagents are loaded at session start.  If you add or edit a persona file directly on disk, the user must restart the session to load it.  Subagents created through the `/agents` interface take effect immediately.

## Custom subagent frontmatter contract

Both `name` and `description` are **required**.  All other fields are optional.

```yaml
---
name: <agent-name>                  # required — lowercase + hyphens; unique across the tree
description: <when Claude delegates  # required — one or two sentences
  to this subagent>
tools: Read, Glob, Grep             # optional — inherits all if omitted
disallowedTools: Write Edit          # optional — denies from inherited/listed set
model: opus                          # optional — sonnet | opus | haiku | <full-id> | inherit (default)
permissionMode: default              # optional — default | acceptEdits | auto | dontAsk | bypassPermissions | plan
maxTurns: 10                         # optional — caps agentic turns
skills: my-skill another-skill       # optional — preloads full skill content (not just description) at startup
mcpServers: [slack, github]          # optional — references configured MCP servers, or inline definitions
hooks: {...}                         # optional — lifecycle hooks scoped to THIS subagent
memory: project                      # optional — user | project | local — persistent memory across sessions
background: false                    # optional — true to always run as background task
effort: high                         # optional — low | medium | high | xhigh | max
isolation: worktree                  # optional — run in an isolated git worktree
color: blue                          # optional — UI color hint for the running subagent
---

You are a <role>.  When invoked, <what you do>.
<Rest of the system prompt — markdown body.>
```

The body becomes the subagent's **system prompt**.  Subagents receive only this system prompt plus basic environment details (working directory) — not the full Claude Code system prompt.  Built-in `Explore` and `Plan` agents skip CLAUDE.md and parent git status; every other subagent loads both.

## Persona body — what to write

The body is whatever the subagent needs to do its job.  Common structure:

```
You <role-verb> <object>.  <One-sentence framing of what you produce.>

## Hard limits

- <Rule 1>
- <Rule 2>

## What you do

1. <Concrete action>
2. <Concrete action>

## Output format

<Literal output layout — table, structured rows, etc.>
```

Second-person voice (*"You judge…"*, *"You return…"*).  No procedure section borrowed from a SKILL.md — the persona is loaded once at startup, then the subagent works inside its own context with the body as its standing instructions.

## Plugin subagent restrictions

For security, plugin subagents do NOT support `hooks`, `mcpServers`, or `permissionMode` — those fields are ignored when loaded from a plugin.  If a plugin subagent needs them, copy the file to `.claude/agents/` or add explicit rules to `permissions.allow` in `settings.json`.

## When to write a custom persona vs use general-purpose

| Use general-purpose (`subagent_type: general-purpose`) when… | Write a custom persona when… |
|---|---|
| The task is one-shot research, a focused search, or a single judgment call | The agent has a *voice* the orchestrating skill depends on |
| The agent's output format is *"a paragraph or a report"* | The agent's output format is structured (per-finding rows, per-target sections, severity levels — name what the skill needs; don't borrow vocabulary from other skills) |
| The agent will be invoked once, ever, from this one skill | The agent is invoked repeatedly across runs, possibly in parallel |
| The skill's own briefing is enough context | Hard rules need to live in the agent's system prompt (so they survive across invocations and across orchestrating skills) |

Custom personas pay off when the agent's behavior must be **stable across invocations** and **not re-derived from prose every time**.  Don't write a custom persona for a one-shot task.

## Pattern 1 — Single fork

One agent dispatched, runs to completion, reports back.  Useful for investigations the inline assistant can't do without context-poisoning, or for generation passes where the inline body shouldn't carry the result-building.

Architecture:
- Skill body decides inputs + briefs the agent
- `Agent` tool fires with `run_in_background: true` if the skill has parallel work to do, otherwise foreground
- Skill body awaits, then surfaces the agent's report to the user

Custom persona only if the agent will be reused across multiple skills.

## Pattern 2 — Director (sequential blindness, for generation workflows)

**This pattern fits when the workflow PRODUCES something** — drafts code, writes prose, regenerates files.  Two or more agents run in sequence: the first produces output, the second reviews that output blind to the inputs the first saw.  The director (skill body) orchestrates but does not judge — its bias from reading inputs disqualifies it as a reviewer of the agents' outputs.

**This is not the audit pattern.**  When the workflow READS an artifact and compares against a spec (audit, lint, review), the right pattern is parallel second-opinion (Pattern 3 below) — there's no "trim" or "rewrite" stage in an audit; both agents do the same job independently.

Architecture (generation):
- Agent A (first stage) sees a designated set of inputs, produces output
- Director applies / processes the output, runs mechanical checks as the skill requires
- Agent B (second stage) sees ONLY what the skill's design says it should see — typically the post-processing state, not Agent A's inputs and not Agent A's task prompt
- Agent B returns findings in whatever output form the skill defines (the form is the skill author's call — don't borrow a vocabulary from another skill unless the skill's job is the same)

**Blindness is engineered**, not assumed.  Each agent's task prompt names ONLY the inputs that agent should see.  Cross-contamination happens through three channels:
- The task prompt names a path the agent shouldn't look at
- The persona file mentions inputs it shouldn't see (the persona file is loaded as system prompt for every invocation; anything in it is permanent context)
- The director provides "context" in the task prompt that leaks the answer (e.g. an example identifier or a paraphrase of the input)

**Director-bias warning, required in the skill body when a director pattern is used:**

> The director (the assistant invoking this skill) saw the inputs and is therefore biased.  When reporting findings, the second-stage agent's report outranks the director's observations.  Don't substitute the director's bias for the second-stage agent's blindness.

**Re-dispatch rule:** when mechanical checks fail, the director does NOT fix the agent's output inline — director edits inject editorial bias and the downstream verifier can't tell whose words it's reading.  Re-dispatch the first-stage agent with the failing items named, then re-apply, then re-run mechanical checks.  Cap re-dispatches at 1–2; beyond that, surface to the user as a stuck case.

## Pattern 3 — Parallel dispatch

N independent agents fire concurrently.  Two distinct shapes share the same dispatch mechanism but have different semantics:

**3a. Parallel batch** — each agent works on its own input slice (different target, same persona).  Useful for processing multiple targets with the same job.

**3b. Parallel second-opinion** — each agent reads the SAME input independently, each judges against the SAME spec, each is blind to the others' output.  Director consolidates: agreement on a finding raises confidence; divergence surfaces as ambiguity for the user.  This is the right pattern for **audit** workflows — there is no "first stage produces, second stage reviews"; both agents do the same audit independently.  **3b is also the right pattern for any self-audit step in a generation skill**: when the skill body author is biased after reading the inputs and drafting the output, the cold-walk happens via sub-agents that read the final draft independently against the spec.  See `SKILL.md` Step 5 for the worked example — three sub-agents, one per reader role, fired in one parallel message, results consolidated into a tiered findings table.

Architecture (both shapes):
- Director batches N `Agent` tool calls **into a single message** (the harness runs them concurrently from one message; sequential messages serialize them)
- For 3a: each call gets a different `description` and `prompt` (per-target)
- For 3b: each call gets the SAME `prompt` (same input, same spec); the persona file does the judging work; the director compares the N reports for agreement vs divergence
- Director awaits all; aggregates per-target (3a) or compares for second-opinion (3b)

Combine with Pattern 2: a director can run a parallel first-stage batch, then a parallel second-stage batch, with engineered blindness preserved between stages.  But don't conflate the two shapes — Pattern 2 has stages; Pattern 3b doesn't.

## Pattern 4 — Skill-of-skills

A skill that invokes other skills via the `Skill` tool.  Example: an orchestrator skill `/<parent>` invokes sub-passes `/<sub-A>`, `/<sub-B>`, `/<sub-C>` sequentially or in parallel.  Architecture is identical to the director pattern except the dispatched units are skills, not sub-agents.

Caveats:
- A skill being invoked by another skill must be safe to invoke from a non-user trigger (i.e. not gated with `disable-model-invocation: true`)
- The orchestrator skill's body lists each sub-skill it invokes; cite via `[/<sub-skill>](../<sub-skill>/SKILL.md)`
- The user's confirmation gates the orchestrator's actions; each sub-skill's own gates still fire

## Anti-pattern — Two agents pretending to be a director pattern

A skill that dispatches two agents but doesn't engineer blindness between them is just one agent's job split in half.  Recognize the failure:
- Both agents see the same inputs → not a director pattern
- The second agent's task prompt includes the first agent's output AND the original inputs → not blind
- The director claims "I'll use two for second-opinion" without naming what the second is blind to → cargo-culted pattern

The fix: either engineer the blindness (the second agent's task prompt names ONLY the working tree's final state, never the inputs the first agent saw), or collapse to single-agent.

## Hook vs skill — the routing question

A skill is invoked by the user (typed slash command) or the main agent (description match).  A hook fires deterministically on a tool event (`PreToolUse`, `PostToolUse`, `Stop`).  When the trigger is *"every time the user edits a file, do X"* — that's a hook, not a skill.  Route to `/update-config` to author the hook entry in `settings.json`.

Hybrid skills exist: a skill that invokes itself from a hook (e.g. a `PostToolUse` hook that fires `claude --skill <slug>`).  Author the skill normally; the hook entry is separate, in `settings.json`.
