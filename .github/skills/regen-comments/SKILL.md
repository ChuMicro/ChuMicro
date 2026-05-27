---
name: regen-comments
description: Regenerate code comments and docstrings from scratch. Strips existing prose, drafts new docstrings via a writer agent blind to the original, grades the result via a verifier agent blind to the baseline, and prints a tiered checklist for human review; never auto-commits. Use when comments have degraded past what /audit-comments can salvage, when a library was written hastily and needs a real doc pass, or when validating the writer persona against a new library. Examples: "/regen-comments chumicro_kvstore", "regenerate comments for chumicro_mqtt from scratch", "validate the commenter persona against a new library"
---

# Regenerate Comments

Strip-and-regenerate pass on a target's docstrings and comments. Unlike `/audit-comments` (which judges and rewrites existing prose), this skill discards everything and rewrites from a fresh read of code.

Three roles cooperate:

1. **Stripper** (`scripts/strip_comments.py`): removes docstrings and non-lint comments, inserts `pass` into bodies that would become empty, verifies the baseline parses.
2. **Writer agent** (one of `commenter-casual-friendly` for `src/`, `commenter-tests` for `tests/` + `functional_tests/`, `commenter-examples` for `examples/`): writes new docstrings + comments from the baseline. Sees only stripped code; never sees the original prose or technical rationale.
3. **Verifier agent** (`commenter-verifier`): reviews the writer's output as a cold reader, blind to the baseline. Flags rule violations and cold-reader failures by tier. Surfaces ambiguous cases for human-only judgment.

You (the assistant invoking this skill) are the **director**. You orchestrate and never auto-commit. See `## The director's bias problem` for why the verifier exists.

## When to reach for this

- Comments are degraded past salvageable — `/audit-comments` would mark everything REWRITE
- A library was written hastily and needs a real doc pass
- You want to validate the persona itself against a new library or tree
- You want a clean comment baseline before a release

## Out of scope

- Markdown / README / docs-site prose → `/audit-docs`
- ADR / SKILL / `plans/` prose → `/audit-skill`
- Trimming comments that are mostly fine → `/audit-comments`
- Code review of logic / shape → `/audit-library`

## Arguments

| Form | Behavior |
|------|----------|
| `/regen-comments <library>` | Regen `libraries/<name>/src/` only (default tree) |
| `/regen-comments <library> --tree all` | Parallel runs on `src/`, `tests/`, `functional_tests/`, `examples/` (4 writer agents, 4 verifier agents) |
| `/regen-comments <library> --tree tests` | One tree only |
| `/regen-comments <lib1> <lib2> ...` | Parallel runs across multiple libraries |
| `/regen-comments <path-to-file.py>` | Single file. See "Per-file caveat" below. |
| `/regen-comments <path-to-dir>` | Arbitrary directory tree |
| No argument | Ask which target |

### Per-file caveat

An agent looking at one file doesn't see what its sibling files do. This is fine for most Python files (they're self-contained for docstring purposes), but **avoid per-file mode** when:
- The file defines an abstract base class implemented in sibling files
- The file is a protocol / contract referenced by other files
- The file is an `__init__.py` whose re-exports depend on understanding the package shape

For these, prefer `/regen-comments <library>` so the writer sees the whole package.

## Procedure

### 1. Confirm scope and ask before starting

If `/regen-comments` was invoked with no target, fire `AskUserQuestion` populated by `ls libraries/` first to capture which library to regen.

The strip step modifies source files in place (uncommitted in `main`). Print the file list, then fire `AskUserQuestion`:

```
About to regenerate comments for libraries/<name>/src/:
  - chumicro_<name>/__init__.py
  - chumicro_<name>/core.py
  - chumicro_<name>/...
```

> "This will strip docstrings and comments from those files in place, then dispatch the writer agent. Proceed?" `header: Strip + regen`
> Options:
> - "Proceed — strip and dispatch"
> - "Narrow the scope first" — re-fire after the user names a smaller target
> - "Cancel"

**Success criteria:** when no target was provided, a target was captured via AskUserQuestion; user picked one of the confirmation options; scope captured before any file is touched.

### 2. Strip the baseline

For each target tree, strip to `.scratch/regen-comments/<library>/<tree>/baseline/`:

```bash
python scripts/run.py strip-comments libraries/<name>/src/chumicro_<name> .scratch/regen-comments/<name>/src/baseline --quiet
```

The stripper:
- Removes module / class / function docstrings
- Removes `#` comments except lint-exception ones (`# noqa`, `# type: ignore`, `# pylint: disable`, `# pragma: no cover`, `# mypy:`, `# ruff:`)
- Inserts `pass` into class/function bodies that would otherwise become empty
- Preserves whitespace (tabs vs spaces per file)
- Validates the output parses with `ast.parse`

If the stripper reports a parse failure, **stop**. That's a bug in the stripper; surface to the user with the file path and the original error.

Then overwrite the source files with the stripped versions so the user can see the clean state:

```bash
cp -r .scratch/regen-comments/<name>/src/baseline/* libraries/<name>/src/chumicro_<name>/
```

(In multi-tree runs, do the same for each tree's baseline.)

**Success criteria:** baseline at `.scratch/regen-comments/<name>/<tree>/baseline/` exists and parses with `ast.parse`; source files overwritten with the stripped versions.

### 3. Dispatch the writer agent(s)

For each tree (or library, in multi-library mode), dispatch one writer agent in parallel. Batch all writer-agent dispatches into one assistant message — the harness runs concurrent calls from a single message; sequential messages serialize them. The Multi-library section restates this; the contract is the same in `--tree all` mode.

**Pick the writer persona per tree** — three personas cover different file conventions:

| Tree | Writer persona | Why this persona |
|------|----------------|------------------|
| `src/` | `commenter-casual-friendly` | Production-code docstrings: one-sentence summaries, Args/Returns/Raises only when earned, no body paragraphs |
| `tests/`, `functional_tests/` | `commenter-tests` | Test docstrings: one-line claim of what's asserted in domain terms, no Args/Returns/Raises ever, causal connectors require real causation |
| `examples/` | `commenter-examples` | Pedagogical: module docstrings carry a short body (use case + how to run + `Example output::` block); inline comments explain why a caller would make a choice |

Use the `Agent` tool with the matching `subagent_type`:

```
Agent(
    subagent_type="<commenter-casual-friendly | commenter-tests | commenter-examples>",
    model="opus",
    description="<tree-or-library> writer",
    prompt="<task only — see template below>",
    run_in_background=True,
)
```

The harness loads the matching `.claude/agents/<persona>.md` as the subagent's system prompt automatically. The director does NOT read or embed any persona file — that would duplicate the rules, waste tokens, and let the embedded copy drift from the source .md.

**Task prompt — minimal, paths only:**

````
Read these stripped Python source files:
<list of input paths under .scratch/regen-comments/<name>/<tree>/baseline/>

Write commented versions to:
<list of output paths under .scratch/regen-comments/<name>/<tree>/output/>

Rules:
- Code body byte-identical to baseline.
- Only add docstrings, module docstrings, and short above-line comments.
- Don't change code, don't add or remove imports, don't add type hints.
- Preserve all lint-exception comments.

Report only the list of files you wrote.
````

**The task prompt must not contain:**

- Technical rationale for why the code is the way it is (eager-import explanations, constant-value justifications) — the writer treats anything in the prompt as comment-worthy and puts it back into the source
- Identifier examples from the target code (`_last_beat_ms`, `period_ms`) — leaks the answer
- "Why" hints about constants, design choices, side-effects
- Cross-file context the writer would otherwise have to derive

If the writer can't figure out the why from a fresh code read, the correct outcome is no comment for that line.

Wait for all writer agents to complete before proceeding.

**Success criteria:** writer agents dispatched in one Agent batch per tree (or library); all returned with file lists; no rationale-leak words in the task prompts.

### 4. Apply the writer's output to source

```bash
cp -r .scratch/regen-comments/<name>/<tree>/output/* libraries/<name>/<tree>/.../
```

(Adjust path for the tree.)

**Success criteria:** writer output copied to source paths under `libraries/<name>/<tree>/...`.

### 5. Mechanical verification — and writer re-dispatch on lint failure

**5a. Byte-identity gate.** Confirm the writer didn't change code:

```bash
diff -u .scratch/regen-comments/<name>/<tree>/baseline/<file>.py libraries/<name>/<tree>/.../<file>.py | grep -v '^[+-]\s*"\|^[+-]\s*#\|^[+-]\s*$' | head -30
```

That filter shows lines changed outside docstrings and comments. If anything appears, surface to the user and stop — the writer broke the byte-identity rule. Don't proceed to lint until byte-identity is clean; spending tokens on E501 re-rolls against already-broken output wastes them.

**5b. Lint and writer re-dispatch on E501.** Run lint:

```bash
.venv/bin/python scripts/run.py lint 2>&1 | tail -30
```

The most common error is **E501 (line too long > 100 chars)** — none of the writer personas enforce line length; ruff does.

Don't trim offending lines yourself. You've seen the baseline, so trimming injects word-choice judgment that belongs to the writer. Re-dispatch the writer with the failing lines — use the same persona that produced the file (per the Step 3 per-tree table):

```
Agent(
    subagent_type="<same persona that wrote this tree>",
    model="opus",
    description="<tree> lint re-dispatch",
    prompt="<re-dispatch task — see template below>",
    run_in_background=True,
)
```

**Re-dispatch task prompt:**

````
The following docstrings in <path> exceed 100 characters and ruff is rejecting them with E501.
Shorten each to fit, preserving its meaning. Don't change code. Don't add or remove sections.
Replace only the listed lines.

File: <abs path>

Line <N> (currently <chars> chars):
<exact current text>

Line <N> (currently <chars> chars):
<exact current text>

...

Report the updated docstrings (one per failing line). Don't restate unchanged content.
````

Apply the writer's response — only to the specific lines named. Re-run lint. If E501s persist, dispatch one more re-roll with the still-failing lines. If a second re-roll still fails, surface to the user as a stuck case.

This keeps word choice in the writer's hands and means the verifier (next step) reads what the writer actually produced, not director edits.

**5c. Full preflight.** Once lint is clean:

```bash
.venv/bin/python scripts/run.py preflight --coverage-threshold 94 2>&1 | tail -15
```

**Success criteria:** byte-identity diff PASS; lint PASS or stuck-case surfaced; preflight PASS.

### 6. Dispatch the verifier agent(s)

For each tree (or library), dispatch one verifier agent in parallel. Batch all verifier-agent dispatches into one assistant message — same single-message contract as Step 3. The verifier sees the **final state** (regenerated commented files), NOT the baseline.

```
Agent(
    subagent_type="commenter-verifier",
    model="opus",
    description="<tree-or-library> verifier",
    prompt="<task only — see template below>",
    run_in_background=True,
)
```

The harness loads `.claude/agents/commenter-verifier.md` as the subagent's system prompt. Director does not read or embed the persona.

**Task prompt:**

````
Read these regenerated Python files and produce findings per the output format in your system prompt:

<list of paths to the final commented files (in libraries/<name>/<tree>/...)>

Do not read any other files. Judge each file standalone as a cold reader.

Report the findings.
````

The verifier is blind to the baseline — its task prompt never references `.scratch/regen-comments/`, and its system prompt (the persona file) never sees the baseline either.

Wait for all verifier agents to complete before proceeding.

**Success criteria:** verifier agents dispatched in one Agent batch; all returned with findings reports.

### 6b. Lost-facts diff — director-side

The verifier is structurally blind to the stripped baseline; its task prompt names only the final commented files. It can flag what's wrong in the new prose; it cannot flag what was *lost* — a rationale line, a constraint note, a "why this constant" comment — that the writer did not reproduce.

The director is the one role that saw the baseline (during Step 2's strip), so the director runs the lost-facts pass.

For each file, diff the preserved baseline against the final commented file:

```bash
diff -u .scratch/regen-comments/<name>/<tree>/baseline/<file>.py libraries/<name>/<tree>/.../<file>.py | head -200
```

Scan the original's docstrings and comments for any *fact* — not wording — that the regenerated version did not reproduce. Typical losses:

- Why a constant has its specific value
- A side-effect callers need to know about
- A constraint enforced silently elsewhere
- A workaround tied to a specific bug or quirk

Append losses to the Step 7 findings list as `LOST-FACT` rows under the file they came from. Tier IMPORTANT by default; CRITICAL when the lost fact would prevent a caller from using the API correctly.

`LOST-FACT` rows surface in the same Step 7 walk-mode as verifier findings; the per-finding actions apply identically. A re-dispatch of the writer on a `LOST-FACT` row carries the fact (one sentence, no original prose verbatim, no leaked identifiers), not the original comment.

**Success criteria:** every file in the regen set diffed; `LOST-FACT` rows merged into Step 7's findings list (or "no lost facts" recorded).

### 7. Consolidate and surface findings

Collect all verifier findings (plus any LOST-FACT rows from Step 6b). Render **Cold-reader summary** + tiered findings per file.

**Filter by default:**
- Always surface CRITICAL findings
- Always surface IMPORTANT findings
- Always surface AMBIGUOUS findings (those explicitly need human judgment)
- MINOR findings: surface only when the user asked for exhaustive review, or when fewer than ~3 findings overall (sparse reports lose nothing by including MINORs)

Print the report (format below), then fire one `AskUserQuestion`:

> "Findings ready. Pick a review mode." `header: Review mode`
> Options:
> - "Walk findings inline" — per-finding `AskUserQuestion` rounds (described below); right mode when more than ~5 CRITICAL/IMPORTANT findings are open (above that, scroll-through review loses items) or the user is unfamiliar with the codebase
> - "Wait for IDE review" — exit; user reads the printed report in their editor and returns with edits
> - "Print only — no walk needed" — report stays in chat; no further action

For "Walk findings inline", group findings into rounds of up to 5 (one file's findings per round when feasible). Per round, fire one `AskUserQuestion` with `multiSelect: true`:

> "Round N of M — pick findings to address. Unpicked carry to the next round." `header: Round N`
> Options:
> - One row per finding: `TIER · file:line · one-line diagnostic`

For each picked finding, fire a per-finding follow-up:

> "Finding <file:line> — how to handle?" `header: <ref>`
> Options:
> - "Keep — accept the writer's text" — entry marked resolved; no Edit
> - "Edit inline — collect revised wording, then Edit" — free-form follow-up for the wording
> - "Re-dispatch the writer on this line" — paths + diagnostic only, no rationale or identifier examples (mirrors Step 5's E501 re-dispatch contract)
> - "Skip — address later" — entry recorded as unresolved in the final report

Apply user revisions via `Edit`. Re-dispatch the writer per Step 5's template.

**Report format:**

```
regen-comments complete for libraries/<name>/src/.

Mechanical checks: PASS / FAIL
- lint: PASS (3 E501 auto-trimmed during step 5)
- preflight: PASS

Verifier findings:

FILE: libraries/<name>/src/chumicro_<name>/core.py
   Cold-reader summary: <one-line summary>
   CRITICAL (2):
     L24 [shape] "blob-shaped persistence target" — `shape` banned everywhere; "blob-shaped" is the X-shaped compound form. Drop the suffix.
     L156 [body-paragraph] "Returns True when X. On a hit, the cache..." — second sentence is body; fold into the summary or drop.
   IMPORTANT (1):
     L78 [cold-reader-fail] `KVStore` class docstring says "manages persistence" — name what KVStore *does* for a caller.
   AMBIGUOUS (1):
     L203 [paraphrase] "the corrupt indicator" — could be paraphrase of `self._corrupt: bool` OR could be standard storage vocabulary. Verify whether "indicator" is in code identifiers or should be `_corrupt`.

FILE: libraries/<name>/src/chumicro_<name>/_backends/memory.py
   Cold-reader summary: clean read; module purpose clear, all methods named accurately.
   CRITICAL: (none)
   IMPORTANT: (none)
   AMBIGUOUS: (none)
```

Tier and category labels in the example output come from the verifier persona's `## Output format` section in `.claude/agents/commenter-verifier.md`; when that enum changes, the example here may lag.

For reports exceeding ~30 findings (above that, scroll-through review loses items), write the report to `.scratch/regen-comments/<name>/report.md` and send via `SendUserFile` with `status: proactive` instead of inline scroll.

The walk closes with one final print:

> "Walk complete — N resolved, M skipped. Run /git-commit when ready. (This skill does NOT auto-commit.)"

**Success criteria:** report printed; user picked a review mode; in walk mode, every picked finding either has an Edit applied / wording collected / re-dispatch fired / skip recorded.

### 8. Bump VERSION

If `src/` was touched and the library is past `0.0.0`, bump the patch level:

```bash
echo "<new-patch-version>" > libraries/<name>/VERSION
```

Confirm with `python scripts/run.py check-version`.

**Success criteria:** VERSION file updated; `python scripts/run.py check-version` confirms the level.

### 9. Hand off

Do NOT commit. Print a one-line ready-to-commit summary; user runs `/git-commit` when satisfied.

**Success criteria:** ready-to-commit summary printed; no commit made.

## Multi-library parallel runs

For `/regen-comments <lib1> <lib2> <lib3>`:

- Strip all targets first (sequential, fast — pure local I/O)
- Dispatch ALL writer agents in parallel — one Agent call per (library, tree) pair, all in one message
- Wait for writer agents to complete
- Apply outputs sequentially (avoids races on shared files like VERSION)
- Run lint + preflight ONCE across all changes
- Dispatch ALL verifier agents in parallel
- Consolidate findings across libraries, sorted by tier within each file

For 3 libraries × `--tree all` = 12 writer + 12 verifier agents in flight. The Agent tool harness handles this; just batch the dispatches into single messages.

## The director's bias problem

You — the assistant invoking this skill — have read the source code (during the strip step, you saw the original docstrings before stripping). That makes you a biased reader of the writer's output: you know what *should* be there because you saw what *was* there. Your "this looks fine" is unreliable.

**That is exactly why the verifier exists.** The verifier sees only the final state. Its findings are the unbiased read.

When reporting to the user, prefer the verifier's findings over your own observations. If you noticed something the verifier missed, you can mention it as a single follow-up note — but lead with the verifier's report. Don't substitute your bias for its blindness.

Step 6b puts the saw-the-baseline read to work in a structured diff. The bias becomes a declared input to a specific step rather than a hidden contaminant the prose warns about.

## Done when

Observable post-state of a completed regen-comments run:

- Mechanical checks (lint + preflight) printed PASS, or any FAIL recorded as a known concern.
- Verifier-findings report sits in chat with per-file tier breakdown.
- `LOST-FACT` rows from Step 6b merged into the findings list (or "no lost facts" recorded).
- Every picked finding in the Step 7 walk has an Edit applied, revised wording collected, a writer re-dispatch fired, or "skip" recorded.
- VERSION bumped when `src/` was touched and the library is past `0.0.0`.
- Source files at `libraries/<name>/...` are in their final regenerated state, uncommitted; user runs `/git-commit` to land the diff.

## Files this skill leaves around

- `.scratch/regen-comments/<library>/<tree>/baseline/` — stripped versions (kept for re-runs / diffs)
- `.scratch/regen-comments/<library>/<tree>/output/` — writer agent output
- Source files at `libraries/<name>/...` — final state, uncommitted

`.scratch/` is gitignored. Clean up after a successful commit if you want; otherwise these are useful for debugging or re-runs.
