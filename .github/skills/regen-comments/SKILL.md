---
name: regen-comments
description: Regenerate code comments and docstrings from a clean slate. Strips comments/docstrings, dispatches the commenter-casual-friendly writer agent on the baseline (no code context leaked), reapplies output, runs preflight, then dispatches the commenter-verifier agent (blind to the baseline) to flag potential misses tiered by severity. Surfaces a structured checklist for human review; never auto-commits. Use when a library's comments have drifted past the point where /audit-comments can salvage them, when a library was written hastily and needs a real doc pass, or when validating the persona itself against a new library.
---

# Regenerate Comments

Strip-and-regenerate pass on a target's docstrings and comments. Unlike `/audit-comments` (which judges and rewrites existing prose), this skill discards everything and rewrites from a fresh read of code.

Three roles cooperate:

1. **Stripper** (`scripts/strip_comments.py`): removes docstrings and non-lint comments, inserts `pass` into bodies that would become empty, verifies the baseline parses.
2. **Writer agent** (`commenter-casual-friendly`): writes new docstrings + comments from the baseline. Sees only stripped code; never sees the original prose or technical rationale.
3. **Verifier agent** (`commenter-verifier`): reviews the writer's output as a cold reader, blind to the baseline. Flags rule violations and cold-reader failures by tier. Surfaces ambiguous cases for human-only judgment.

You (the assistant invoking this skill) are the **director**. You orchestrate but do not judge — your bias from reading the baseline means you can't fairly review the writer's output as a cold reader. That's why the verifier exists.

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

The strip step modifies source files in place (uncommitted in `main`). Confirm with the user before stripping. Show the file list:

```
About to regenerate comments for libraries/<name>/src/:
  - chumicro_<name>/__init__.py
  - chumicro_<name>/core.py
  - chumicro_<name>/...
This will strip docstrings and comments from these files in place, then dispatch the writer agent. Continue?
```

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

### 3. Dispatch the writer agent(s)

For each tree (or library, in multi-library mode), dispatch one writer agent in parallel. Use the `Agent` tool with native subagent dispatch:

```
Agent(
    subagent_type="commenter-casual-friendly",
    model="opus",
    description="<tree-or-library> writer",
    prompt="<task only — see template below>",
    run_in_background=True,
)
```

The harness loads `.claude/agents/commenter-casual-friendly.md` as the subagent's system prompt automatically. The director does NOT read or embed the persona file — that would duplicate the rules, waste tokens, and let the embedded copy drift from the canonical .md.

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

**Critical: what the task prompt must NOT contain.** These caused real damage during persona development:

- Technical rationale for why the code is the way it is (eager-import explanations, constant-value justifications, etc.) — the writer treats anything in the prompt as comment-worthy and puts it back into the source
- Identifier examples from the target code (`_last_beat_ms`, `period_ms`, etc.) — leaks the answer
- "Why" hints about constants, design choices, side-effects
- Cross-file context the writer would otherwise have to derive

If the writer can't figure out the why from a fresh code read, the correct outcome is no comment for that line.

Wait for all writer agents to complete before proceeding.

### 4. Apply the writer's output to source

```bash
cp -r .scratch/regen-comments/<name>/<tree>/output/* libraries/<name>/<tree>/.../
```

(Adjust path for the tree.)

### 5. Mechanical verification — and writer re-dispatch on lint failure

Run lint first (cheapest check):

```bash
.venv/bin/python scripts/run.py lint 2>&1 | tail -30
```

The most common error is **E501 (line too long > 100 chars)** — the persona doesn't enforce line length; ruff does.

**Do not trim offending lines yourself.** The director is biased (you've seen the baseline) and trimming involves word-choice judgment that belongs to the writer. Instead, re-dispatch the writer with the failing lines:

```
Agent(
    subagent_type="commenter-casual-friendly",
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

Apply the writer's response — only to the specific lines named. Re-run lint. If E501s persist, dispatch ONE more re-roll with the still-failing lines; if a second re-roll still fails, surface to the user as a stuck case rather than looping further or trimming inline.

This keeps word choice in the writer's hands and means the verifier (next step) reads what the writer actually produced, not director edits.

**If tests fail (not just lint)** the writer likely changed code despite the rule. Diff against the baseline to confirm:

```bash
diff -u .scratch/regen-comments/<name>/<tree>/baseline/<file>.py libraries/<name>/<tree>/.../<file>.py | grep -v '^[+-]\s*"\|^[+-]\s*#\|^[+-]\s*$' | head -30
```

That filter shows lines changed outside docstrings and comments. If anything appears, surface to the user and stop — the writer broke the byte-identity rule.

Then full preflight (after lint is clean):

```bash
.venv/bin/python scripts/run.py preflight --coverage-threshold 94 2>&1 | tail -15
```

### 6. Dispatch the verifier agent(s)

For each tree (or library), dispatch one verifier agent in parallel. The verifier sees the **final state** (regenerated commented files), NOT the baseline.

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

The verifier is blind to the baseline by construction — its task prompt never references `.scratch/regen-comments/`, and its system prompt (the persona file) never sees the baseline either.

Wait for all verifier agents to complete before proceeding.

### 7. Consolidate and surface findings

Collect all verifier findings. For each file, show the **Cold-reader summary** + tiered findings.

**Filter by default**:
- Always surface CRITICAL findings
- Always surface IMPORTANT findings
- Always surface AMBIGUOUS findings (those explicitly need human judgment)
- MINOR findings: surface only if the user asked for exhaustive review, OR if there are fewer than 3 findings overall (then MINOR fills the gap usefully)

**Format for the user**:

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

How to proceed:
  1. Open the diff in your editor (`git diff libraries/<name>/`) or review here.
  2. Walk the CRITICAL findings first — those are clear rule breaks.
  3. Walk the IMPORTANT findings — these are cold-reader failures.
  4. AMBIGUOUS findings need your judgment — they're the kind of thing only you can call.
  5. When satisfied, run /git-commit. (This skill does NOT auto-commit.)

Want me to:
  (a) Walk findings one at a time with you (interactive review)?
  (b) Wait for you to review in your IDE and come back with edits?
```

Default to asking. Walking one-at-a-time is the right mode when there are >5 CRITICAL/IMPORTANT findings or when the user is unfamiliar with the codebase.

### 8. Bump VERSION

If `src/` was touched and the library is past `0.0.0`, bump the patch level:

```bash
echo "<new-patch-version>" > libraries/<name>/VERSION
```

Confirm with `python scripts/run.py check-version`.

### 9. Hand off

Do NOT commit. Surface a one-line ready-to-commit summary; user runs `/git-commit` when satisfied.

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

## Methodology lessons (don't break these)

Learned the hard way during persona development:

1. **Never include technical rationale in the writer's prompt.** Any "why" you put in becomes a comment in the output, even when the right next state is no comment.
2. **Never include identifier examples from the target code.** Listing `_last_beat_ms` or `period_ms` as examples leaks the answer for that library.
3. **Strip means strip.** Comments AND docstrings AND empty-body fixup. The stripper handles this; don't add manual edits.
4. **The baseline must parse.** Always verify with `ast.parse` after stripping. A parse failure is a stripper bug.
5. **Test passing isn't proof the writer left code alone.** Diff against the baseline to confirm byte-identity outside docstrings.
6. **Lint after apply, but route fixes back to the writer.** E501 is the most common slip; the persona doesn't enforce line length. Re-dispatch the writer with the offending lines — don't trim them yourself. Director trims inject editorial bias and the verifier won't know which words were the writer's vs the director's.
7. **Verifier is blind, director is biased.** Don't read the verifier's output through your bias — its tier and category are the signal.
8. **Filter MINOR by default.** A user drowning in stylistic nitpicks misses CRITICAL findings. Surface MINOR only when explicitly asked.
9. **AMBIGUOUS findings exist for a reason.** The verifier flags them because they require project-specific judgment. Don't try to resolve them yourself — surface to the user.

## Files this skill leaves around

- `.scratch/regen-comments/<library>/<tree>/baseline/` — stripped versions (kept for re-runs / diffs)
- `.scratch/regen-comments/<library>/<tree>/output/` — writer agent output
- Source files at `libraries/<name>/...` — final state, uncommitted

`.scratch/` is gitignored. Clean up after a successful commit if you want; otherwise these are useful for debugging or re-runs.

## Future extensions

These came up during the experiment but aren't built yet:

- **Verifier-of-verifiers (consolidation agent)**: When running multi-library regen, a third agent that ingests all verifier reports, dedups across libraries, ranks by severity, and produces a single batched checklist. Useful when total finding count exceeds ~30.
- **Persona-per-tree**: The current design uses `commenter-casual-friendly` for all trees. Tests and examples might benefit from a tighter persona focused on test-docstring conventions ("describes what's asserted, not what the code does"). Worth experimenting with if test-docstring quality drifts.
- **Run integration**: Add `python scripts/run.py regen-comments <library>` as a wrapper that calls this skill non-interactively for CI / batch use. Current skill is interactive (asks before stripping, asks how to walk findings).
