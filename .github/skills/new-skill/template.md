# SKILL.md Template

The reference scaffold `/new-skill` Step 3 uses.  Read the structure from the code blocks below; produce a new SKILL.md modeled on them.  Field-by-field rules for the frontmatter live in [`spec-loader-reader.md`](spec-loader-reader.md).  Body-structure rules live in [`spec-triggering-reader.md`](spec-triggering-reader.md).

## Table of contents

- [Frontmatter scaffold](#frontmatter-scaffold)
- [Body scaffold](#body-scaffold) — title · when-to-use · invocation · definition of done · process · output format · red flags · what to include / leave out · don'ts · done when
- [Companion agents — table + persona skeleton](#companion-agents--table--persona-skeleton)
- [Authoring notes](#authoring-notes)

---

## Frontmatter scaffold

```yaml
---
# All fields are optional; only `description` is recommended.
# The slash command name comes from this directory's name, NOT from `name:` below.

description: <Verb> <object> <when>. <One-sentence body of what the skill does.> Use when <triggering condition>. Examples: "<user message 1>", "<user message 2>", "<user message 3>".

# `description` + `when_to_use` combined are capped at 1,536 chars in the loader.
when_to_use: |
  Use when <triggering condition described in full>.
  Trigger phrases include "<phrase 1>", "<phrase 2>", "<phrase 3>".
  Do NOT use to <adjacent task owned by a sibling skill> — that workflow is <sibling skill>.

# Frontmatter fields to include only as needed. Delete unused ones from the
# committed SKILL.md.

# name: <display label in skill listings; defaults to directory name>
# argument-hint: "[<optional>] <required>"
# arguments: <space-separated names, OR a YAML list>
# allowed-tools: Read Glob Grep Bash(<prefix> *) AskUserQuestion
# disable-model-invocation: true       # user-only invocation, removes description from session-start context
# user-invocable: false                # Claude-only invocation, hides from / menu
# model: opus                          # per-skill model override: opus | sonnet | haiku | <full-id> | inherit
# effort: high                         # per-skill effort: low | medium | high | xhigh | max
# context: fork                        # runs in a subagent with no conversation history
# agent: Explore                       # subagent type for context: fork (Explore | Plan | general-purpose | <custom>)
# hooks: {...}                         # hooks scoped to THIS skill's lifecycle
# paths: "src/**/*.py"                 # auto-trigger only on matching paths
# shell: bash                          # bash (default) or powershell for bang-prefixed backticked-command blocks
---
```

---

## Body scaffold

````markdown
# <Skill Title>

<One paragraph: what this skill is, who calls it, what the deliverable is.
Name the handle the agent will use — "drive it via `<driver>` under tmux"
for a desktop tool, "produces a punch-list of <findings>" for an audit.
No narrative preamble — the agent reading this is mid-task.>

## When to use this skill

- <Concrete scenario 1 where this skill is the right answer>
- <Concrete scenario 2>
- <Concrete scenario 3>

**Don't use for:**

- <Adjacent task> — use [`<sibling-skill>`](../<sibling-skill>/SKILL.md).
- <Another adjacent task> — use a different approach.

## Invocation

| Form | Behavior |
|---|---|
| `/<slug>` | <default behavior> |
| `/<slug> <arg>` | <variant behavior> |
| `/<slug> --<flag>` | <flag-driven variant> |

<Delete this section if the skill has no arguments.>

## Definition of done

<For action / driver-backed skills. Otherwise replace with a list of
in-scope deliverables that prove the skill ran correctly.>

You are done when **all** of these are true:

1. <Verifiable criterion 1 — an observable artifact, file, or assertion>
2. <Verifiable criterion 2>
3. <Verifiable criterion 3>

## Process

### 1. <First step name>

<What to do. One paragraph at most. Include the exact command when the
agent needs to run something.>

```bash
<exact command the agent runs>
```

**Success criteria:** <one observable artifact or assertion that proves
this step is done. Not "step is complete" — a real check.>

**Execution:** Direct (delete this line if Direct).

**Artifacts:** <name and one-line description of any data this step
produces that later steps consume. Delete if none.>

**Rules:**
- <Hard rule specific to this step, with the reason it exists>

### 2. <Second step name>

<…>

**Success criteria:** <…>

**Human checkpoint:** <When and why to pause and confirm with the user.
Delete if not needed. Reserve for irreversible actions or output review.>

### 3. <Third step name>

<…>

**Success criteria:** <…>

## Output format

<For skills that produce structured output. Show the literal form — a
table, a JSON schema, a punch-list. Delete this section if the skill's
output is the produced file itself.>

```
<one row or one line of the output, showing the columns / fields>
```

## Red flags — stop and reconsider

Stop if:

- **<Failure mode 1>** — <why this means the skill is about to ship the
  wrong thing>
- **<Failure mode 2>**
- **<Failure mode 3>**

## What to include

- <Concrete inclusion 1 — what the agent should add to its work>
- <Concrete inclusion 2>

## What to leave out

- <Concrete exclusion 1 — what the agent should NOT add>
- <Concrete exclusion 2>

## Don'ts

- **Don't <action>.** <One-line reason>.
- **Don't <action>.** <One-line reason>.

## Done when

<Observable end-state, distinct from the last Process step. The agent
uses this to know the skill ran correctly.>

- <Observable check 1>
- <Observable check 2>
- <The user has been told <what they need to know>>
````

---

## Companion agents — table + persona skeleton

Delete this section when the skill is single-agent or pure prose.  Include when the skill dispatches custom-persona sub-agents.  List each with role + file location + dispatch site within the Process.

````markdown
## Companion agents

| Agent | Role | File | Dispatched from step | Blind to |
|---|---|---|---|---|
| `<agent-1>` | <writer / verifier / investigator / …> | `.claude/agents/<agent-1>.md` | Step `<N>` | <baseline / writer prompt / nothing> |
| `<agent-2>` | <…> | `.claude/agents/<agent-2>.md` | Step `<N+1>` | <…> |
````

Each agent file lives at the path above.  The companion subagent skeleton — use one per agent:

`.claude/agents/<agent-name>.md` (or `~/.claude/agents/<agent-name>.md` for cross-project personas):

````markdown
---
# Required
name: <agent-name>
description: <when Claude or the orchestrating skill should delegate to this subagent>

# Optional — include only what the subagent needs
# tools: Read Glob Grep                 # space-separated or YAML list; inherits all if omitted
# disallowedTools: Write Edit            # deny specific tools from the inherited/listed set
# model: opus                            # sonnet | opus | haiku | <full-id> | inherit (default)
# permissionMode: default                # default | acceptEdits | auto | dontAsk | bypassPermissions | plan
# maxTurns: 10                           # cap agentic turns
# skills: my-skill another-skill         # preload full skill content (not just description) at startup
# mcpServers: [slack, github]            # MCP servers available; ignored for plugin subagents
# hooks: {...}                           # lifecycle hooks scoped to this subagent; ignored for plugin subagents
# memory: project                        # user | project | local — persistent memory across sessions
# background: false                      # true to always run as a background task
# effort: high                           # low | medium | high | xhigh | max
# isolation: worktree                    # run in an isolated git worktree
# color: blue                            # UI color hint for the running subagent
---

You <role-verb> <object>.  <One-sentence framing of what you produce.>

## Hard limits

- **<Rule 1>** — <one-sentence why>
- **<Rule 2>**

## Scope

You judge the <prose / code / structure / …>, not the <other thing>.  Out of scope:

- <Concrete exclusion 1>
- <Concrete exclusion 2>

## What you do

For each <input> you're given:

1. <Concrete action 1>
2. <Concrete action 2>
3. <Concrete action 3>

## Output format

<Literal output layout — table, structured rows, etc. — sourced from a known scheme or invented and defined here. Don't borrow vocabulary from another skill's verifier.>

## Blindness contract

You have **not** seen <X>.  You have **not** seen <Y>.  The only context you have is <Z> and the rule set above.

<Why this blindness exists — usually because a director that orchestrated this saw X and is biased; you, blind to it, give the unbiased read.>
````

**Notes on the subagent skeleton:**

- `name` is required.  Lowercase + hyphens.  Must be unique across the agents tree — subdirectories don't affect identity.  The filename does not have to match the `name`, but conventionally they do.
- `description` is required.  Names *when* Claude or the orchestrating skill should delegate to this subagent.
- All other fields are optional.  Include only those the subagent actually needs.
- `tools` defaults to inheriting all tools available to the main conversation.  Restrict for verifiers (`Read` only — a verifier that can write breaks its blindness contract).
- `model` defaults to `inherit`.  Override only when the subagent's work differs from session default (judgment-heavy → `opus`, fast parallel → `haiku`).
- `skills` preloads the **full skill content** at startup, not just the description — heavier than session-level loading, useful when the subagent must follow specific procedure.
- Plugin subagents have `hooks`, `mcpServers`, and `permissionMode` ignored for security.
- The body is the system prompt.  Second-person voice (*"You judge…"*, *"You return…"*).  No procedure section borrowed from a SKILL.md.
- **Loading caveat to flag to the user**: a freshly-written persona file requires a Claude Code session restart to load.  Subagents created through `/agents` take effect immediately.
- The body carries its rules inline.  Attention/weights land harder on content in the persona's system prompt than on content one Read away — so the persona is self-contained even when those rules also live in a spec section, an ADR, or the orchestrating skill's body.  When the inline rules mirror a file on disk, open the persona body with a *Source of truth* pointer naming that file so future editors update both in lockstep.  (Per-invocation parameters that vary by dispatch — paths, input lists — stay in the dispatch prompt, not the persona body.)

---

## Authoring notes

A condensed checklist when filling the scaffold above.  Full rules live in `spec-loader-reader.md` (frontmatter) and `spec-triggering-reader.md` (body).

**Frontmatter:**

- `name` defaults to the directory name; set the field only when the display label should differ.
- `description` is what the loader scans on every session-start.  Carry verbs the user would actually type.  Test against three example user messages before locking it in.  ≤ 1024 chars (hard validation cap).
- `allowed-tools` should be the minimal set.  Use `Bash(<prefix> *)`, not bare `Bash`.
- `when_to_use` extends the description with trigger phrases and a *Do NOT use* clause when an adjacent skill exists.
- Set `context: fork` only when the skill is self-contained and runs to completion without mid-process user input.  Fork sub-agents cannot take live input.
- Set `disable-model-invocation: true` for skills with side effects (deploys, sends messages, commits), or for `/command`-only entry points.

**Body:**

- ≤ 500 lines and under ~5,000 tokens (≈3,800 words) — both budgets, since long lines game the line count.  Past either, factor reference files (one hop deep only); each link names what the file contains and when to read it.
- Procedure-first.  Bury narrative.
- Every Process step needs Success criteria.  The other annotations (Execution, Artifacts, Human checkpoint, Rules) are conditional.
- Done-when is distinct from the last Process step.  The last step is what you do; Done-when is the state you observe.
- AI-tic vocabulary, anti-self-assertions, dated phrasing, first-person plural, defensive hedging, moralizing imperatives — strip before shipping.

**Reference files** (optional, one hop deep only):

- `interview.md` — deep question bank for interview-style skills.
- `spec.md` (+ `spec-*.md` siblings) — rules / criteria the skill enforces; split by topic when a single file grows past the splitting threshold.
- `examples.md` — one or two worked walkthroughs.
- `scripts/` — bundled executable scripts for action skills; entry-point file names match the job (`driver.<ext>`, `smoke.sh`, `validate.py`).
