# Skill Spec — Author guidance and orchestration patterns

This is the rule reference `/new-skill` enforces.  When this file disagrees with an older skill on disk, this file wins — the older skill is regenerated through `/new-skill`, not edit-merged with this spec.

## Where the rules live

The detailed rules split into three sibling files by topic:

| File | Covers |
|---|---|
| [`spec-loader-reader.md`](spec-loader-reader.md) | Frontmatter contract, name + description + when_to_use rules, Concise is key |
| [`spec-triggering-reader.md`](spec-triggering-reader.md) | Body structure, per-step annotation discipline, patterns to avoid, stance |
| [`spec-sibling-author.md`](spec-sibling-author.md) | Reading rule, reference-file layout, MCP tool naming |

The validation lenses in `.github/skills/_shared/audit_wf.js` carry condensed versions of the loader and body rules; a material edit to those spec files means re-checking the matching lens prompt. Orchestration patterns split into a fourth file (topical):

| File | Covers |
|---|---|
| [`spec-orchestration.md`](spec-orchestration.md) | Sub-agent dispatch architectures (Patterns 1–4), persona contract, file locations, anti-pattern, hook-vs-skill |

The rest — degrees of freedom, authoring patterns, driver / harness, widget selection, three-readers framing — is general author guidance.  Lives in this file.  Table of contents below.

## Table of contents

- [Authoring principles](#authoring-principles) — degrees of freedom · iterative refinement · model testing
- [Authoring patterns](#authoring-patterns) — checklist · feedback loop · template · examples · conditional · solve-don't-punt · voodoo constants · plan-validate-execute · forward slashes · avoid offering too many options
- [Three readers, three failure modes](#three-readers-three-failure-modes)
- [Driver / harness pattern](#driver--harness-pattern) — when needed · driver shapes · driver rules · listing bundled scripts · designing scripts for agentic use · one-off commands vs bundled
- [Widget selection — AskUserQuestion vs plain text](#widget-selection--askuserquestion-vs-plain-text)
- Agent and orchestration patterns → see [`spec-orchestration.md`](spec-orchestration.md)
- [Mirror relationship with the validation lenses](#mirror-relationship-with-the-validation-lenses)

---

## Authoring principles

### Degrees of freedom — match specificity to task fragility

Choose the level of specificity to fit how fragile and variable the work is.  Three bands:

| Freedom | When to use | What it looks like |
|---|---|---|
| **High** — text instructions, multiple valid approaches | Heuristics guide; decisions depend on context | *"Analyze code structure, check for bugs, suggest improvements"* — no code, no exact sequence |
| **Medium** — pseudocode or scripts with parameters | Preferred pattern exists; some variation OK | A code template with parameters the user fills in |
| **Low** — specific scripts, few or no parameters | Operations are fragile; consistency is critical; exact sequence matters | *"Run exactly this script. Do not modify the command or add flags."* |

Analogy: imagine Claude as a robot on a path.

- **Narrow bridge with cliffs on both sides** → only one safe way forward.  Provide guardrails, exact instructions (low freedom).  Example: a database migration that must run in a specific order.
- **Open field with no hazards** → many paths lead to success.  Give direction, trust Claude to find the route (high freedom).  Example: a code review where context determines the best critique.

The skill author's job is to pick the right band per step.  Mixing bands within one procedure is fine; defaulting to low freedom everywhere produces brittle skills that fail when the world doesn't match the script.

### Iterative refinement — Claude A creates, Claude B uses

The most effective development loop runs across **two Claude instances**:

- **Claude A** sits with the skill author and helps draft / refine the SKILL.md.  Claude A knows the author's intent and the design context.
- **Claude B** is a fresh instance with the skill loaded — it uses the skill on real tasks without the author's context.

The loop:

1. Author works through a real task with Claude A (no skill yet).  Notices what context they repeat each time.
2. Author asks Claude A to draft a skill that captures the reusable pattern.
3. Claude A drafts the SKILL.md with proper frontmatter and body structure.
4. Author reviews for conciseness, asks Claude A to refine information architecture.
5. **Author tests with Claude B** on related tasks.  Observes whether Claude B finds the right information, applies rules correctly, succeeds.
6. **Observations from Claude B flow back to Claude A** for refinement: *"Claude B forgot to filter test accounts; is the rule prominent enough?"*
7. Repeat.

Why this works: Claude A understands the skill format and agent needs; the author provides domain expertise; Claude B reveals gaps through real usage.  Iterative refinement improves the skill based on **observed behavior**, not assumptions.

**Common observation cues from Claude B:**

- *Unexpected exploration paths* — Claude B reads files in an order the author didn't anticipate → structure isn't as legible as the author thought
- *Missed connections* — Claude B fails to follow a reference → the link needs to be more prominent
- *Overreliance on one section* — Claude B reads the same file repeatedly → that content probably belongs in the main SKILL.md
- *Ignored content* — Claude B never reads a bundled file → it's unnecessary or poorly signaled

The `description` and `name` are the single biggest determinants of whether Claude B picks the skill at all.  Iterate on those most aggressively.

### Test across models

A skill that works perfectly on Opus may underperform on Haiku.  Test across:

- **Haiku** — does the skill provide enough guidance for a smaller model?
- **Sonnet** — clear and efficient?
- **Opus** — not over-explaining?

If the skill will be used across model tiers, aim for instructions that work for the smallest model in the set; bigger models tolerate redundancy, smaller models often need it.

---

## Authoring patterns

### Checklist pattern (for complex workflows)

For procedures with more than three steps where order matters, give Claude a copyable checklist:

````
## <Workflow name>

Copy this checklist and tick items as you complete them:

```
Progress:
- [ ] Step 1: <action>
- [ ] Step 2: <action>
- [ ] Step 3: <action>
```

**Step 1: <action>**
<exact command or instruction>

**Step 2: <action>**
<exact command or instruction>

...
````

Claude pastes the checklist into its response and ticks items as it progresses.  Useful for multi-step workflows where skipping a step is a known failure mode (form-filling, migrations, multi-stage code generation).

### Feedback loop pattern (validator → fix → repeat)

For quality-critical work, name a validator the skill runs after each draft, then loop until clean:

```
1. Draft <output>.
2. Run <validator>.
3. If validation fails:
   - Read the error message
   - Fix the issue
   - Run <validator> again
4. Only proceed when validation passes.
```

The validator can be a script, a style guide, or another sub-agent.  The loop catches errors immediately rather than letting them propagate to later steps where the cause is harder to trace.

### Template pattern (strict or flexible)

Provide an output template.  Match strictness to the requirement:

**Strict template** — when output must conform to a contract (API response, data format):

````
## Report structure

ALWAYS use this exact template:

```markdown
# [Title]

## Executive summary
[One paragraph]

## Findings
- Finding 1
- Finding 2

## Recommendations
1. ...
```
````

**Flexible template** — when adaptation is useful:

````
## Report structure

Sensible default; adjust sections as the analysis warrants:

```markdown
# [Title]

## Executive summary
[Overview]

## Findings
[Adapt sections based on what you discover]
```
````

The strict form constrains; the flexible form anchors.  Don't mix the two voices in one template — pick a band and stick with it.

### Examples pattern (input → output pairs)

When output quality depends on matching a style, provide concrete pairs:

````
## Commit message format

**Example 1:**
Input: Added user authentication with JWT tokens
Output:
```
feat(auth): implement JWT-based authentication

Add login endpoint and token validation middleware
```

**Example 2:**
Input: Fixed bug where dates displayed incorrectly
Output:
```
fix(reports): correct date formatting in timezone conversion

Use UTC timestamps consistently across report generation
```

Follow this style: type(scope): brief description, then detailed body.
````

Examples teach style faster than descriptions of style.

### Conditional workflow pattern

For skills that branch by input type:

```
## <Workflow> entry

1. Determine the input type:

   **<Type A>?** → Follow "Workflow A" below
   **<Type B>?** → Follow "Workflow B" below

2. Workflow A:
   - Step ...
   - Step ...

3. Workflow B:
   - Step ...
   - Step ...
```

Forces Claude to pick a path explicitly rather than guess which branch applies.

### Solve, don't punt (for code-bearing skills)

Scripts bundled with a skill should handle errors, not raise them up to Claude:

**Good:**

```python
def process_file(path):
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        print(f"File {path} not found, creating default")
        with open(path, "w") as f:
            f.write("")
        return ""
    except PermissionError:
        print(f"Cannot access {path}, using default")
        return ""
```

**Bad — punts to Claude:**

```python
def process_file(path):
    return open(path).read()  # fails opaquely, Claude has to figure it out
```

### Bundled-script conduct — announce long work, guard the browser

Two rules for any script a skill ships, both learned from real runs:

- **A script about to make a multi-minute silent call announces itself first.**  A clean-room `claude -p`, a long subprocess, a network sweep — print one flushed line naming what is running and the rough duration (*"regenerating Foo.bar against the ledger (one clean-room claude -p, ~1-2 min)..."*) before the call.  Without it, a chained sequence of these scripts looks hung and the user interrupts healthy work.
- **A script that opens a browser honors a headless guard.**  Auto-open via `open` / `webbrowser` is the right default on a desktop, and wrong in CI, cron, and background sessions.  Gate it behind an env var (the regen-comments renderers use `REGEN_NO_OPEN=1`) and write the artifact regardless, printing its path.

### Voodoo constants — document or drop

Any magic number / path / threshold in a script needs a comment explaining the value.  Otherwise it's a "voodoo constant" — Claude can't reason about whether to change it.

**Good — self-documenting:**

```python
# HTTP requests typically complete within 30 seconds
# Longer timeout accounts for slow connections
REQUEST_TIMEOUT = 30

# Three retries balances reliability vs speed
# Most intermittent failures resolve by the second retry
MAX_RETRIES = 3
```

**Bad — magic numbers:**

```python
TIMEOUT = 47  # Why 47?
RETRIES = 5   # Why 5?
```

### Plan-validate-execute (for high-stakes operations)

For batch operations or destructive changes, have Claude write a structured plan first, validate the plan with a script, then execute.  Reversible, machine-checkable, debuggable.

```
1. Analyze input → write changes.json
2. Validate changes.json (script)
3. If validation fails: fix changes.json, re-validate
4. Execute the validated plan
5. Verify output
```

Catches "Claude misunderstood the input" before any state is mutated.

### Forward slashes only

Always use forward slashes in file paths, regardless of platform:

- Good: `scripts/helper.py`, `reference/guide.md`
- Avoid: `scripts\helper.py`, `reference\guide.md`

Unix-style paths work everywhere; Windows-style paths break on Unix.

### Avoid offering too many options

Give a default with an escape hatch.  Don't enumerate every possibility:

**Good:**

> Use pdfplumber for text extraction.  For scanned PDFs requiring OCR, use pdf2image with pytesseract instead.

**Bad:**

> You can use pypdf, or pdfplumber, or PyMuPDF, or pdf2image, or PyPDF2, or…

The bad version creates decision paralysis.  The good version picks one and names the one alternative that meaningfully differs.

---

## Three readers, three failure modes

A SKILL.md is read by three different agents at three different times.  Each surfaces a different class of gap.  The skill that ships well has been tested against all three.

| Reader | When they read | What they do | What they bail on |
|---|---|---|---|
| **Loader agent** | Every session start | Reads only the `description:` (and `when_to_use:`) line. Decides whether to surface this skill in the picker for a given user message. | Vague stems, jargon-heavy openers, descriptions missing *when*, descriptions over ~400 chars. |
| **Triggering agent** | When a match fires | Has matched. Opens the body cold, no prior conversation context. Walks top-to-bottom and executes. | No exit condition; *"as we discussed"* refs; arguments not documented; procedure that needs jumping around; narrative preamble before any step; Process step without Success criteria. |
| **Sibling-skill author** | Some time later | Adding a new skill next to this one. Checks whether the new task overlaps. | Two skills that would route the same user message; restates content from another skill or from a source-of-truth doc. |

### Source-first discipline

For each load-bearing piece — description, Process, Done-when — **draft the ideal version from a fresh read of "what does this skill do, when does it fire, who calls it" before re-reading the actual draft.**  Items present in your fresh draft but absent from the actual are findings.  These are gaps mechanical sweeps don't catch because nothing is *wrong* with what's there; what's wrong is what's *not* there.

---

## Driver / harness pattern

When the skill's job is to *run code* — a smoke test, a build, a probe, a deploy — write the harness too.

### When a driver is needed

- The success criterion is something only code can verify: "the app started," "a page rendered," "the API returned 200."
- The skill drives an interactive tool: a TUI, a REPL, a long-running server.
- The skill orchestrates multiple commands in sequence with state between them.

### Driver shapes by project type

| Skill type | Driver form | Lives in |
|---|---|---|
| Web app / browser-driven | `chromium-cli` inline heredoc in SKILL.md | `SKILL.md` (no separate file) |
| Web server / API | Background-launch + `curl`-based smoke script | `smoke.sh` next to SKILL.md |
| Desktop GUI (Electron) | Playwright `_electron` REPL under tmux | `driver.mjs` next to SKILL.md |
| TUI / interactive terminal | `tmux` wrapper (`send-keys` / `capture-pane`) | `driver.sh` next to SKILL.md |
| CLI tool | Representative-args smoke script | `smoke.sh` next to SKILL.md |
| Library / SDK | Import-and-call smoke script | `driver.<py|mjs>` next to SKILL.md |

### Driver rules

- Bundled scripts live in `<skill-dir>/scripts/`.  A single-entry skill names its entry point per its job (`driver.<ext>`, `smoke.sh`, `probe.py`); a multi-script skill keeps each as its own file in the same folder.
- When a bundled script grows enough that the project's real test suite or another tool wants it, move it to `scripts/` or `e2e/` at the project root and update the SKILL.md to point at the new path.  The skill stays put; the script finds a better home.
- The bundled scripts get committed alongside the SKILL.md — they are not scaffolding.
- Every code block in SKILL.md that invokes a bundled script is a command the author actually ran.  No inferring from the README.

### Listing bundled scripts in the SKILL.md

When a skill bundles more than one script, the SKILL.md body lists them so the agent knows they exist:

```markdown
## Available scripts

- **`scripts/validate.sh`** — validates configuration files
- **`scripts/process.py`** — processes input data
```

A single-entry-point skill can reference the script inline in the Process step that runs it; no separate Available-scripts section needed.

Reference scripts with **relative paths from the skill directory root** — the agent resolves these automatically.  No absolute paths.  Same convention for any other bundled content (reference files, fixtures).

### Designing scripts for agentic use

When an agent runs a bundled script, it reads stdout and stderr to decide what to do next.  A few choices make scripts dramatically easier to use:

- **No interactive prompts.**  Agents run in non-interactive shells — TTY prompts, password dialogs, confirmation menus hang indefinitely.  Accept input via flags, env vars, or stdin.  Document the requirement in `--help`.
- **Document with `--help`.**  `--help` output is the primary way the agent learns the script's interface.  Brief description + every flag + one or two examples.  Keep concise — the output enters the agent's context.
- **Helpful error messages.**  Name what went wrong, what was expected, what to try.  *"`Error: --format must be one of: json, csv, table. Received: \"xml\"`"* beats *"`Error: invalid input`."*
- **Structured output.**  Prefer JSON / CSV / TSV over free-form text.  Send data to stdout, diagnostics (progress, warnings) to stderr — lets the agent capture clean parseable output while still seeing what happened.
- **Idempotent operations.**  Agents retry on failure.  *"Create if not exists"* is safer than *"create and fail on duplicate."*
- **Reject ambiguous input.**  Use enums and closed sets where possible; refuse with a clear error rather than guessing.
- **`--dry-run` for destructive operations.**  Lets the agent preview what would happen before committing.
- **Meaningful exit codes.**  Distinct codes per failure type (not found, invalid args, auth failure).  Document them in `--help` so the agent knows what each code means.
- **Safe defaults.**  Destructive operations require an explicit `--confirm` / `--force` flag.
- **Predictable output size.**  Many agent harnesses truncate tool output past 10–30K characters.  Default to a summary; support `--offset` (or require an `--output <file>` for large data) so the agent can opt into more.

### One-off commands vs bundled scripts

When an existing tool already does the job and ships with version-pinned runners (`uvx`, `pipx run`, `npx`, `bunx`, `go run`), invoke it inline in the SKILL.md instead of bundling a wrapper.  Always pin the version.  Move to `scripts/` when the command grows complex enough that it is hard to get right on the first try.

For self-contained bundled scripts, prefer formats that declare their own dependencies inline — PEP 723 (`uv run script.py`) for Python, `npm:` specifiers for Deno, `bundler/inline` for Ruby — so the agent can invoke the script with a single command with no separate install step.

---

## Widget selection — AskUserQuestion vs plain text

Interactive skills gather artifacts from the user.  Each artifact has one correct widget; the wrong one frustrates the user or produces wrong output.

| Artifact the question gathers | Widget | Why |
|---|---|---|
| One path from a known set of choices (mode, scope, audience, yes/no) | `AskUserQuestion` single-pick | The widget renders K options + Other; the user picks one branch. |
| Subset (M items) of a finite K of predefined items (which tools, which dimensions, which features) | `AskUserQuestion` with `multiSelect: true` | The widget renders K checkboxes; the user picks M. Only works when K is finite and the options are themselves the answer (not illustrations of categories). |
| Free-text content the user types (list of trigger messages, multi-step procedure, paragraph spec, sentence brief) | Plain chat. Optionally preceded by a one-pick gateway `AskUserQuestion`: *"ready to type, or show examples first?"* | `AskUserQuestion` is single-pick by default; the options read as the universe of choices, not as illustrations. A user staring at four sample messages cannot intuit that they're supposed to type three different ones in Other. |

### The Q1a antipattern

A common mistake: a question asks for *"three trigger messages"* and lists three sample messages as `AskUserQuestion` options, intending the samples as illustration and the user's three as free-text in Other.

**The widget cannot carry this.**  Single-pick + Other = *"pick one of K or type one of your own,"* not *"type three of your own using these as inspiration."*  The user reads the labels as the universe of choices.

**The fix:**

```
1. (Optional) Fire a gateway AskUserQuestion:
   "Phase N gathers <N items>. Ready to type, or want to see examples first?"
   Options: "Ready" | "Show examples first"
2. If "Show examples first" → print examples as plain assistant text → re-fire gateway
3. If "Ready" → exit AskUserQuestion. Say "Type them now, one per line."
4. Accept plain chat input. Restate the captured artifact ("To confirm — the N items
   you gave are…"). Loop until the user confirms or revises.
```

The plain-text capture loop is what the multi-item artifact needs.  `AskUserQuestion` re-enters only for the confirmation single-pick at the end.

### When in doubt

If a question's answer would naturally be typed as 2+ lines of free text, it is NOT an `AskUserQuestion` question.  Branching, multi-select-from-finite, and yes/no are the three things the widget does well.  Everything else is plain text.

---

## Agent and orchestration patterns

Moved to [`spec-orchestration.md`](spec-orchestration.md) — covers file locations, the custom-subagent frontmatter contract, persona-body shape, when to write a custom persona vs use general-purpose, Patterns 1–4, the two-agents-pretending-to-be-a-director anti-pattern, and the hook-vs-skill routing question.

---

## Mirror relationship with the validation lenses

The `/new-skill` validation step runs the shared lens workflow (`.github/skills/_shared/audit_wf.js`), whose agent prompts carry condensed versions of the loader and body rules **inline** — a lens does not Read these spec files at dispatch time.  This is deliberate: an agent that re-reads a long spec per dispatch skims, fills gaps with training-data intuition, and behaves inconsistently across runs.  A material edit to `spec-loader-reader.md` or `spec-triggering-reader.md` means re-checking the matching lens prompt in that script.

The other sections of this `spec.md` root (Authoring principles, Authoring patterns, Three readers / three failure modes, Driver / harness pattern, Widget selection) plus the sibling [`spec-orchestration.md`](spec-orchestration.md) are authoring guidance for the skill writer — not enforced by a cold-walk persona — and live only there.
