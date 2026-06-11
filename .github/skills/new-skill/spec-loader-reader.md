# Spec — Loader-reader scope

Frontmatter rules the loader-reader cold-walk persona judges against.  When this file changes, [`.claude/agents/new-skill-loader-reader.md`](../../.claude/agents/new-skill-loader-reader.md) changes in lockstep.

For body-structure, per-step, patterns-to-avoid, and stance rules see [`spec-triggering-reader.md`](spec-triggering-reader.md).  For sibling-overlap and reference-file rules see [`spec-sibling-author.md`](spec-sibling-author.md).  For general authoring guidance (degrees of freedom, authoring patterns, driver / harness, widget selection, orchestration) see [`spec.md`](spec.md).

## Table of contents

- [Frontmatter contract](#frontmatter-contract)
  - [Where the command name comes from](#where-the-command-name-comes-from)
  - [`name`](#name)
  - [`description`](#description) — incl. [calibrating against near-miss queries](#calibrating-against-near-miss-queries)
  - [`when_to_use`](#when_to_use-optional)
  - [`argument-hint`](#argument-hint-optional)
  - [`arguments`](#arguments-optional)
  - [`allowed-tools`](#allowed-tools-optional)
  - [`disable-model-invocation`](#disable-model-invocation-optional)
  - [`user-invocable`](#user-invocable-optional)
  - [`model`](#model-optional)
  - [`effort`](#effort-optional)
  - [`context`](#context-optional)
  - [`agent`](#agent-optional)
  - [`hooks`](#hooks-optional)
  - [`paths`](#paths-optional)
  - [`shell`](#shell-optional)
  - [String substitutions](#string-substitutions)
  - [Dynamic context injection](#dynamic-context-injection--bangcommand)
  - [Plugin-namespaced skills](#plugin-namespaced-skills)
  - [Skill precedence when names collide](#skill-precedence-when-names-collide)
  - [Where skills live](#where-skills-live)
- [Concise is key](#concise-is-key)

---

## Frontmatter contract

Every SKILL.md opens with a YAML block between `---` fences.  **All fields are optional.**  Only `description` is recommended so Claude knows when to use the skill.

```yaml
---
name: my-skill                            # optional — defaults to directory name
description: <what + when, ending with    # recommended
  Examples: "...", "...", "...">
when_to_use: <extended trigger guidance>  # optional — appended to description
argument-hint: "[<optional>] <required>"  # optional
arguments: slug --spec                    # optional — space-separated or YAML list
allowed-tools: Read Grep                  # optional — space-separated or YAML list
disable-model-invocation: true            # optional — user-only invocation
user-invocable: false                     # optional — Claude-only invocation
model: opus                               # optional — per-skill model override
effort: high                              # optional — per-skill effort override
context: fork                             # optional — runs in a subagent
agent: <agent-name>                       # optional — paired with context: fork
hooks: {...}                              # optional — skill-scoped hooks
paths: "src/**/*.py"                      # optional — auto-trigger only on matching paths
shell: bash                               # optional — bash (default) or powershell
---
```

### Where the command name comes from

The slash command is **not** the `name` field.  It comes from the skill's location:

| Location | Command name source |
|---|---|
| `~/.claude/skills/<dir>/SKILL.md` or `.claude/skills/<dir>/SKILL.md` | Directory name |
| `.claude/commands/<file>.md` (legacy custom commands) | File name without extension |
| `<plugin>/skills/<dir>/SKILL.md` | `/<plugin>:<dir>` |
| `<plugin>/SKILL.md` at plugin root | Frontmatter `name`, falling back to plugin directory name |

The frontmatter `name` field is a **display label** shown in skill listings.  The plugin-root case is the one place where `name` sets the command name.

### `name`

- **Optional.**  Defaults to the directory name.
- **Maximum 64 characters.**
- Lowercase letters, numbers, and hyphens only.  No XML tags.
- **Cannot be reserved words:** `anthropic`, `claude`.
- Used as the display label in skill listings.
- For plugin-root `SKILL.md`, also sets the namespaced command (falls back to plugin directory name).

**Naming convention.**  Anthropic recommends **gerund form** (verb + -ing) for skill names — describes the activity clearly:

- Recommended: `processing-pdfs`, `analyzing-spreadsheets`, `managing-databases`, `writing-documentation`
- Acceptable alternatives: noun phrases (`pdf-processing`), action-oriented (`process-pdfs`)
- Avoid: vague names (`helper`, `utils`, `tools`), overly generic (`documents`, `data`), inconsistent patterns within one skill library

### `description`

- **Recommended.**  Without it, the loader matches against the first paragraph of markdown content.
- The single most load-bearing field for routing.  The loader matches user messages against this line.
- **Hard maximum: 1024 characters** (validation rule — skills with longer descriptions fail to load).  No XML tags.  Non-empty.
- **Listing truncation: 1536 characters** combined with `when_to_use` (also configurable via the `maxSkillDescriptionChars` setting).  The hard 1024 cap is per-field; the 1536 cap is on the combined text shown in skill listings.  Put the key use case first — truncation drops from the end.
- Names **what the skill does** AND **when to invoke it**.
- **Always third person.**  *"The description is injected into the system prompt, and inconsistent point-of-view can cause discovery problems."*
  - Good: *"Processes Excel files and generates reports."*
  - Avoid: *"I can help you process Excel files."*
  - Avoid: *"You can use this to process Excel files."*
- Verbs the user would actually type — *audit*, *generate*, *run*, *deploy*, *screenshot*.  Avoid abstract stand-ins (*handle*, *manage*, *work with*).
- **Focus on user intent, not implementation.**  The agent matches against what the user asked for, not how the skill works internally.  *"Cleans messy CSV data"* beats *"Wraps pandas read_csv with parameter inference."*
- **Imperative `Use when…` coda is compatible with third-person opening.**  The full structure: `<Third-person verb> <object>. <Differentiator.> Use when <trigger>. Examples: "<m1>", "<m2>", "<m3>".`  The opening states what; the coda states when.
- **Be pushy about adjacent phrasings.**  List the contexts where the skill applies, including cases where the user does not name the domain directly.  Pattern: *"…even if they don't explicitly mention 'CSV' or 'analysis.'"*  Under-pushy descriptions miss real triggers; over-broad descriptions misfire on near-misses (calibrate against both — see below).
- Anti-stems that fail the loader test:
  - *"Tools for…"* / *"Helps with…"* / *"Utilities for…"*
- Include trigger-phrase examples for routing:
  > Examples: "audit this skill", "review my SKILL.md", "regenerate /foo".
- Include a *Do NOT use to <X>* clause when an adjacent skill exists and the boundary is non-obvious — the precision counterweight to the pushy patterns above.
- **Specialized-knowledge caveat.**  Agents tend to consult skills only for tasks that require knowledge or capabilities beyond what they can handle alone.  A simple one-step request (*"read this PDF"*) may not trigger a PDF skill even if the description matches perfectly — that's the agent judging the task does not need specialized handling, not a description failure.  Optimize the description against tasks that genuinely need the skill's knowledge.
- The loader has a session-start budget that scales at ~1% of the model context window (configurable via `skillListingBudgetFraction`).  When overflowing, descriptions for least-invoked skills get dropped first.  Long descriptions cost every session; tight descriptions cost less.

#### Calibrating against near-miss queries

When judging a description, do not test only against the messages it should fire on.  Also draft a **near-miss** query — one that shares the skill's keywords or concepts but actually needs something different.  Worked examples for a CSV-analysis skill:

| Query | Should fire | Why |
|---|---|---|
| *"my boss wants a chart from this data file"* | Yes | Domain not named; the description must be pushy enough to route |
| *"I need to update the formulas in my Excel budget spreadsheet"* | No | Shares "spreadsheet" / "data"; needs Excel editing, not CSV analysis |
| *"can you write a python script that reads a csv and uploads each row to our postgres database"* | No | Mentions CSV; the task is ETL, not analysis |

A description that fires on the first message but stays silent on the latter two is calibrated.  A description that fires on all three is too pushy.  A description that fires on none is too narrow.

**Query realism.**  Calibration queries — positive and near-miss — should read the way users actually type: a concrete file path or symbol name, some backstory, casual phrasing, the occasional lowercase or typo.  Abstract requests (*"format this data"*, *"extract text from PDF"*) measure nothing, because no real message looks like that.  Obviously-irrelevant negatives test nothing either — every near-miss should be a query a naive keyword match would route wrong.

**Persisted evals.**  The interview's Phase 1 queries (three positives + three-to-five near-misses with `expected_route`) persist as `trigger-evals.json` next to the SKILL.md, in the regen-comments schema (`skill_name`, `evals: [{query, should_trigger, expected_route?}]`).  `.github/skills/_shared/run_trigger_evals.py` probes them against the live skill registry; re-run after any `description` / `when_to_use` edit or when a sibling's scope moves closer.

### `when_to_use` (optional)

- Extended trigger guidance appended to `description` in the skill listing.  Combined with `description`, counts toward the 1536-char listing truncation.
- Use for trigger phrases that wouldn't fit in `description`, or for *Do NOT use* clauses that need their own paragraph.
- Loader scans `description` + `when_to_use` as a single text blob for routing.
- Same third-person voice rule as `description`.

### `argument-hint` (optional)

- Hint shown during autocomplete to indicate expected arguments.
- Examples: `[issue-number]`, `[filename] [format]`, `<file-path>`.
- Square brackets mark optional; bare angle brackets mark required.

### `arguments` (optional)

- Named positional arguments for `$<name>` substitution in the skill content.
- Accepts a space-separated string (`arguments: issue branch`) or a YAML list.
- Names map to positions in order: with `arguments: [issue, branch]`, `$issue` expands to the first argument and `$branch` to the second.

### `allowed-tools` (optional)

- Tools Claude can use without per-call approval while the skill is active.
- Accepts a space-separated string (`allowed-tools: Read Grep`) or a YAML list.
- For Bash, use prefix-scoped entries: `Bash(git add *) Bash(git commit *)`.  Never bare `Bash` in a project-committed skill (broad approval).
- MCP tools: `mcp__<server>__<tool>` or `mcp__<server>__*`.
- `AskUserQuestion` is its own entry — list it for any interactive skill.
- Does NOT restrict what's callable.  It only suppresses approval prompts for the listed tools.  Deny rules in `/permissions` still apply.

### `disable-model-invocation` (optional)

- `true` — only the user can invoke the skill (`/<command>` only).  Claude cannot auto-load it.
- **Also removes the description from session-start context** — saves the description-budget cost for skills the user invokes deliberately.
- Use for workflows with side effects (deploys, commits, sends messages) or pure `/<command>`-style entry points.
- Default: `false`.

### `user-invocable` (optional)

- `false` — hides the skill from the `/` menu.  Claude can still invoke it; the user can't.
- Use for background-knowledge skills that aren't actionable as a command (e.g. *"legacy-system-context"*).
- Default: `true`.
- The visibility/invocation matrix:

| Frontmatter | User can invoke | Claude can invoke | Description in session-start context |
|---|---|---|---|
| (default) | Yes | Yes | Yes |
| `disable-model-invocation: true` | Yes | No | No |
| `user-invocable: false` | No | Yes | Yes |

### `model` (optional)

- Per-skill model override for the rest of the current turn.  Resumes the session model on next prompt.
- Accepts `opus`, `sonnet`, `haiku`, a full model ID (`claude-opus-4-7`), or `inherit`.
- Useful for skills whose work warrants a different model than the session default (judgment-heavy → opus, fast lookup → haiku).

### `effort` (optional)

- Per-skill effort override.  Options: `low`, `medium`, `high`, `xhigh`, `max`.
- Overrides the session effort level while the skill is active.
- Default: inherits from session.

### `context` (optional)

- `fork` — runs in a forked subagent with its own context.  The SKILL.md content becomes the prompt that drives the subagent.  Subagent does NOT have conversation history.
- Pairs with `agent:` to pick the subagent type (built-in `Explore`, `Plan`, `general-purpose`, or any custom subagent from `.claude/agents/`).
- Default: inline (in the main conversation).
- **Warning**: `context: fork` only makes sense for skills with **explicit task instructions**.  If the skill body is reference material (*"use these API conventions"*) without a task, the subagent receives the guidelines but no actionable prompt and returns nothing useful.

### `agent` (optional)

- Names the subagent type used when `context: fork` is set.
- Built-in options: `Explore` (read-only research), `Plan` (planning), `general-purpose` (capable but generic).
- Or any custom subagent slug from `.claude/agents/<name>.md`.
- Defaults to `general-purpose` if omitted with `context: fork`.

### `hooks` (optional)

- Hooks scoped to **this skill's lifecycle** — distinct from session-level hooks in `settings.json`.
- Use when a deterministic step should fire whenever this skill runs (e.g. a post-skill notification).

### `paths` (optional)

- Glob patterns that limit when Claude auto-loads the skill — only when working with files matching the patterns.
- Accepts comma-separated string or YAML list.
- Same format as path-specific rules in CLAUDE.md.

### `shell` (optional)

- `bash` (default) or `powershell` for `!`<command>`` blocks (see *Dynamic context injection* below).
- Setting `powershell` runs inline shell commands via PowerShell on Windows.  Requires `CLAUDE_CODE_USE_POWERSHELL_TOOL=1`.

### String substitutions

Skill content supports these substitutions, which expand before Claude sees the content:

| Variable | Meaning |
|---|---|
| `$ARGUMENTS` | All arguments passed when invoking the skill.  If `$ARGUMENTS` is not present in the body, arguments are appended as `ARGUMENTS: <value>`. |
| `$ARGUMENTS[N]` | Specific argument by 0-based index. |
| `$N` | Shorthand for `$ARGUMENTS[N]`. |
| `$<name>` | Named argument declared in the `arguments:` frontmatter list. |
| `${CLAUDE_SESSION_ID}` | Current session ID — for logging, session-specific files. |
| `${CLAUDE_EFFORT}` | Current effort level — to adapt skill instructions to the active setting. |
| `${CLAUDE_SKILL_DIR}` | **Directory containing the skill's SKILL.md.**  Use this to reference bundled scripts (e.g. `${CLAUDE_SKILL_DIR}/scripts/visualize.py`) so they resolve correctly across personal/project/plugin layouts. |

Indexed arguments use shell-style quoting — wrap multi-word values in quotes to pass them as a single argument.

### Dynamic context injection — `!`command``

The **bang-backtick** syntax (a bang character followed by a backticked shell command) runs the command **before the skill content is sent to Claude**.  The command output replaces the placeholder.  This is the **supported feature** for injecting fresh state into a skill prompt.

A skill that wants the current git diff inlined into its body would place a bang-prefixed backticked command on its own line, between the section headers, and the preprocessor substitutes the diff output at load time.  (The literal syntax is not shown here because the example would itself fire the preprocessor when this spec file is loaded — see the rules below for why.)

Rules:
- The inline form fires only when the bang character appears at the start of a line or immediately after whitespace.  When the bang follows a non-whitespace character (e.g. `KEY=<bang><backtick>cmd<backtick>`), the placeholder is left as literal text.
- For multi-line commands, use a fenced block whose opener is ` ``` ` followed immediately by a bang character — that fence fires too.
- Substitution runs **once** over the original file.  Command output is inserted as plain text and is not re-scanned for further placeholders.
- Disable via the `disableSkillShellExecution: true` setting (project- or managed-level kill switch).
- Bundled and managed skills are not affected by the kill switch.

**Authoring caveat for this spec file and similar reference docs.**  Because the preprocessor scans raw text — including inside fenced code blocks and inline code spans — any literal `<bang><backtick>command<backtick>` pattern in a reference doc that ships as part of a skill directory WILL fire when the skill is invoked.  To document the syntax safely, describe it in prose (as above) rather than writing the literal trigger.

### Plugin-namespaced skills

Plugin skills carry a namespaced command:

- `<plugin>/skills/<skill>/SKILL.md` → `/<plugin>:<skill>`
- `<plugin>/SKILL.md` (plugin-root) with `name: <slug>` → `/<plugin>:<slug>`, falling back to the plugin directory name if `name` is omitted.

Plugin skills cannot conflict with other levels because the namespace is unique.  Plugin subagents have additional restrictions: `hooks`, `mcpServers`, and `permissionMode` are ignored when loaded from a plugin.

### Skill precedence when names collide

When skills share a name across levels:

```
managed settings > personal > project
```

Plugin skills use the namespace, so they cannot collide with the above.  Files in `.claude/commands/` still work for backward compatibility; if a skill and a command share the same name, the skill wins.

### Where skills live

| Location | Path | Available to |
|---|---|---|
| Personal | `~/.claude/skills/<name>/SKILL.md` | All your projects |
| Project | `.claude/skills/<name>/SKILL.md` | This project only |
| Plugin | `<plugin>/skills/<name>/SKILL.md` | Where plugin is enabled |
| Managed | Managed settings directory | Organization-wide |

Project skills load from the starting directory **and every parent up to the repo root**, plus nested `.claude/skills/` directories under files you're editing (monorepo support).

Skills from `--add-dir` / `/add-dir` are loaded automatically (exception to the rule that those flags grant file access only).  Skills from the `permissions.additionalDirectories` setting are NOT loaded.

---

## Concise is key

Every token in a loaded skill rides the rest of the session.  Don't explain what Claude already knows.  Challenge each piece of content:

- *"Does Claude really need this explanation?"*
- *"Can I assume Claude knows this?"*
- *"Does this paragraph justify its token cost?"*

Worked example — both versions teach the same thing.  The verbose version is three times as long for no information gain:

**Concise** (~50 tokens):

````
## Extract PDF text

Use pdfplumber for text extraction:

```python
import pdfplumber

with pdfplumber.open("file.pdf") as pdf:
    text = pdf.pages[0].extract_text()
```
````

**Verbose** (~150 tokens — bad):

```
## Extract PDF text

PDF (Portable Document Format) files are a common file format that
contains text, images, and other content. To extract text from a PDF,
you'll need to use a library. There are many libraries available for
PDF processing, but pdfplumber is recommended because it's easy to use
and handles most cases well. First, you'll need to install it using
pip. Then you can use the code below...
```

The concise version assumes Claude knows what PDFs are and how libraries work.  Default assumption: Claude is already very smart.
