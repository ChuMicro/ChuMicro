---
name: audit-comments
description: Audit code comments and docstrings in a file, library, or tree for whether a cold reader learns what the thing does and why it exists. Unlike the trim-only comment passes inside /audit-library, this skill rewrites a degraded comment from a fresh read of the code rather than subtracting it further. Use when comments have gone illegible after repeated audits, after a feature pass, or before a release-prep pass.
---

# Comment audit

Audit the comments and docstrings of a target (`libraries/<name>/`, `workbench/<name>/`, a single `.py`, or a subtree) for one question: **if a reader knew nothing about this code and read only this comment, would they know what the thing does and why it exists?**  Output a prioritized punch-list, then execute the high-confidence batch with the user's go-ahead.

This skill reads code *only as much as it takes to write a correct comment*.  It does not reshape code, flag dead code, or restructure methods — those route to `/audit-library`.  One responsibility: the prose.

## Why this is its own skill

`/audit-library` §6 audits comments too, but its governing rule is *"don't golf, if the shape is clear leave it"* — it only ever **subtracts** (cut a tic, delete an unparseable sentence, drop narration).  Run that move enough times and you get the residue this skill exists to fix: `the single chokepoint that evicts a board settings.toml` — a sentence that survived three subtractive passes, each removing a word, none ever asking *what should this say?*

For comments specifically, that posture is inverted here: **a comment that fails the cold-reader test is rewritten from a fresh read of the code, not trimmed.**  Trimming a degraded comment makes it shorter and more illegible.  The fix is new prose written by someone who just read what the code actually does.

`/audit-library` §6 still *surfaces* comment candidates (its essay-bloat ratio sweep, its AI-tic grep) — it detects, then defers the rewrite here.  The deterministic drift (dated incidents, `Decision NNNN` in shipped trees, cross-site duplicate blocks) is the lint's job (`CHU012`, `CHU006`, and the dedup / date-token rules tracked in `plans/open-questions.md` → "Mechanize the comments…").  The semantic call — *is this comment narrating a change, labeling the code, or explaining the current why?* — is explicitly assigned to human judgment there, not lint.  This skill is that judgment's home.

## Scope

`# comments` and `"""docstrings"""` in:

* `libraries/<name>/src/` and `support/test_harness/src/` — code that ships to a device; flash-costed, cross-runtime, read cold by library users.
* `workbench/<name>/src/`, `scripts/` — host code; read cold by contributors.
* Test bodies — comments and docstrings in `tests/` / `functional_tests/`.

Out of scope: user-facing markdown (`README.md`, `docs/guide.md`) → `/audit-docs`.  SKILL.md / ADR / `plans/` prose → `/audit-skill`, ADR review.  Code shape, dead code, method length, duplication of *logic* → `/audit-library`.

**Arguments.**

* `/audit-comments <library>` — every `.py` under that package (e.g. `/audit-comments wifi`, `/audit-comments deploy`).
* `/audit-comments <path>` — one file or a subtree (e.g. `/audit-comments libraries/mqtt/src/chumicro_mqtt/_wire.py`).
* No argument → ask which target.  Whole-repo in one pass is an `/audit-workspace`-scale concern — surface that and ask whether to scope down; the repo-wide roll-out is tracked in `plans/next-up.md`, run per-library.

## The test every comment must pass

Read the comment *first*, then the code.  If the comment didn't prepare you for what the code does — or you had to read the code to understand the comment — the comment failed.  Then classify:

* **KEEP** — states what the thing does and the non-obvious why; a cold reader is oriented before they read a line of code.  Leave it. Tighten wording only if a tic is present.
* **TRIM** — correct and oriented, carrying one removable tic or one redundant clause.  Subtractive fix is enough.
* **REWRITE** — degraded: illegible, buried, label-only, or so trimmed it no longer says what the thing is.  **Discard it.  Read the code.  Write a new comment from scratch.**  This is the default action for the residue described above — do not try to salvage word-by-word.  *Testable criterion:* if your proposed edit changes ≤1 clause and leaves the surrounding paragraph structure intact, it is TRIM, not REWRITE — even if you used the word "rewrite" while drafting.  REWRITE requires the surrounding prose to be reconsidered from the code alone; the result is usually a multi-sentence restructure, often shorter than the original.  Tagging a minimal phrase-swap as REWRITE is the failure mode the trim-only audit history produced — name the work honestly.
* **DELETE** — pure label (`# increment counter`), pure history (`# replaces the old lfs mkfs`), or a downstream/provenance pointer with no current-why content.  Remove; add nothing.

## Audit dimensions

Run each over the target.  Capture findings as `file:line` + one-line description + dimension tag (see Output format).

### 1. Says-what-it-does, plainly, first

A docstring's first sentence orients the reader: *what this returns / does*, in plain words, before any why.

* **Definition-by-superlative.**  *"The one true path for getting this string"*, *"the single source for X"* as an opener — the banned `the (one|single|sole) <noun> (that|which|is)` tic (same family as *"the canonical X"*; see [`agent-style-guide.md` § "the one / single / sole X that…"](../../../docs/contributing/agent-style-guide.md#the-one--single--sole-x-that)).  Rewrite to the plain statement: *"Returns the product ID string."*  *Triage, not auto-flag* — legitimate invariant prose (*"the single owner of the staging path"*, ADR 0077's *"exactly one mechanism"*) is a KEEP.
* **Why with no what.**  A docstring that jumps straight to rationale/safety without ever saying what the function returns or does.  The reader gets *why it's careful* before *what it is*.  Rewrite: plain what-sentence first, then the why.
* **What buried under provenance.**  The real one-line description exists but sits under three paragraphs of where-this-came-from.  Lift the what to sentence one; cut or compress the rest per dim 3/4.

### 2. Directional honesty — confined code must not name its callers

A low-level helper's comment that names its downstream callers is a leak: the helper is now coupled, in prose, to code it should not know about.

* **"Called from X / used by Y" in a helper docstring** — *"Called from each platform's `actual fun platformHttpClient(...)`"*.  The helper does not get to know who calls it.  Rewrite to the contract + an abstract usage hint: *"Installs the Ktor plugins shared by every platform client. Use as the shared config for downstream platform clients."*
* **Upstream comment encoding a downstream invariant** — *"the caller must call close() after this"* is a real contract and stays; *"the deploy CLI passes this as --foo"* names a specific consumer and goes.  Test: would the comment still be true and useful if a *different* caller used it?  If naming the caller is the only content, delete the naming.

### 3. Provenance and reference-project noise

Comments that point outside the realm of *this* code are noise to the reader of this code.

* **Mirror / port pointers** — *"Mirrors `PlatformOkHttpClient.cloudClient()`"*, *"ported from the upstream client repo"*, *"matches the reference impl"*.  The reader of this file cannot act on a sibling/upstream project name.  Delete the pointer; keep only the behavioral content (*"uses the OS trust store"*).  For shipped trees this is also `CHU006`'s deterministic subset (mono-repo refs) — but the broader provenance class (any external-repo / reference-impl name) is judgment, owned here.
* **Enumerated mirror lists** — a docstring whose bulk is *"- repo-A does it with X; - repo-B does it with Y"*.  The reader needs *what this code does*, not a comparative survey.  Rewrite to the irreducible technical why (the constraint that forced this approach), drop the survey.  Worked shape: a 22-line cert-parsing docstring enumerating two reference impls collapses to 6 lines stating the JVM/Swift constraint, the byte-reinterpret approach, and the one load-bearing safety clause.

### 4. Signal-to-noise

Every sentence must change what the reader knows or does next.  Sentences that don't, go.

* **`the`-density as a symptom (not a target).**  Stacked definite articles and sentence-initial `the` before brand names usually mark prose written by accretion, not by a writer.  Source of truth: [`agent-style-guide.md` § Definite-article tics](../../../docs/contributing/agent-style-guide.md#definite-article-tics) for the brand-name and stacked-article shapes, and [§ The `the X` forward-reference test](../../../docs/contributing/agent-style-guide.md#the-the-x-forward-reference-test) for the per-noun three-way test on REWRITE drafts.  Apply the forward-reference test to the draft, not only to the original: inherited `the`s the rewrite did not earn compound across passes the same way the superlative tic does.  Reduce as a *symptom* of low signal.
* **AI-tic vocabulary in comments/docstrings.**  Run the standing regex from [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex) over `src/` comments, not just markdown.  Same handling per [§ Phrase bans](../../../docs/contributing/agent-style-guide.md#phrase-bans) (drop / replace / case-by-case).  Do not carry a private copy of the list here.  The agent style guide is the source of truth and `/audit-skill` dim 6 flags drift.
* **Essay wrapping a one-liner.**  A 5-line body under a 25-line docstring whose extra 24 lines narrate the body line-by-line.  `/audit-library` §6's ratio sweep is the *detector* (cite its script; don't re-implement it); the *action* — rewrite to the irreducible what + why — is this skill's.  **Calibrate before cutting:** `typing.Protocol` method bodies (the docstring *is* the contract), `@abstractmethod` stubs, and destructive- or many-parameter public-API `Args:` blocks legitimately run long.  The ratio triggers a read, not a cut.
* **Cross-site redundancy within the file / package.**  When the same fact is stated in 2+ comment sites — module docstring + the attribute docstring next to the field + the return-block sentence about that field, or callee descriptions echoed in caller docstrings — one site is the home and the others collapse.  Read the file's comments *together*, not in isolation, to see this; per-comment review will miss it because each one reads fine alone.  CHU027 catches the lexical class mechanically (≥3 in-package or ≥2 cross-package, ≥12 normalized tokens) per [Decision 0079](../../../plans/decisions/0079-prose-drift-mechanization.md); the auditor still catches sub-threshold cases (2 sites in one package, or paraphrased sites that don't hash-match).  Consolidation finding: name the home site in the punch-list, mark the others DELETE or TRIM-to-cross-reference.

### 5. History and change-narration

The comment documents the *why of the code as it is now* — never how it got here.

* **Change narrative** — *"replaces the old lfs mkfs, which destroyed the keep set"*, *"now that clean-slate defaults"*, *"used to also send Ctrl-C"*.  The reader does not need the diff; `git log` and the ADR carry it.  Rewrite to the present-tense why (*"preserves the keep set: a full mkfs would drop boot.py"*), or DELETE if the only content was the history.
* **Dated incident / bench log** — *"2026-05-09 ESP32-S2 bake"*, *"empirically the slowest we've observed"*, *"(bench-confirmed across both runtimes)"*.  The dated subset is `CHU012`'s; the dateless verb-anchored subset (*"X now that Y landed"*) plus the parenthetical bench-confirmation shape (*"(bench-confirmed …)"*, *"(measured on the Pi Pico W)"*) is judgment, owned here.  These survive audits because they *look* like rigorous technical justification, but they add nothing the reader can act on — DELETE.  Per-change rationale and bench numbers belong in the commit message.
* **Stale "until X lands"** — *"the legacy additive shape, retained only until clean-slate defaults"* when clean-slate already defaulted.  Both history *and* a false claim.  Rewrite to current reality or DELETE.
* **"legacy" / "deprecated" as a label with no deprecation timeline** — *"``False`` is the legacy additive scope"* / *"legacy additive deploys pass ``False``"* when `--no-wipe` is an actively-supported alternate mode the CLI documents.  Same family as the dateless-history tics above: the label implies obsolescence the codebase hasn't actually scheduled.  Rewrite to what it is plainly — *"the additive scope"*, *"the `--no-wipe` opt-out"* — and let `git log` carry whatever historical context once made the word fit.  Audit move: grep `legacy` + `deprecated` across `src/` comments; check each against whether a deprecation timeline exists.

## Procedure

**Method discipline — read fully, do not grep-shortcut.  Spare no tokens.**  This is not a pattern-match audit.  The reflex to scan a large library by `grep`ing for known AI-tics or banned phrases is the failure mode that misses the findings that matter: cross-site redundancy (the same fact stated across three comment sites — module docstring, attribute docstring next to the field, return-block sentence about that field), half-fixes (one stale clause removed, another stale clause in the same paragraph kept), comments whose load-bearing instruction is *implicit* in a word the auditor is about to strip, and the cold-reader judgments the skill exists to apply.  Read every comment in the target; if the target is too large for one continuous read, **split the target** (audit one subpackage at a time) — do not switch to grep.  Token cost is not the success metric; finding the residue is.  Grep is for verifying a specific claim after the read, not for replacing it.

**Read paragraph-internal clauses individually, not just paragraphs as units.**  A docstring's overall correctness shields its subordinate clauses from scrutiny — the worst surviving defects after a prior comment-audit pass are mid-paragraph parentheticals (*"(bench-confirmed across both runtimes)"*), closing "and the test will catch drift" clauses, a single bulleted item nested in a 15-line target list, and historical asides buried inside otherwise-current explanations.  The surrounding prose reads fine and the eye skips the bad clause, so a paragraph-level read misses what a clause-level read catches.  Worked case: the deploy follow-up audit caught six defects of this shape after a prior `/audit-comments deploy` pass missed them — every one was a clause nested inside an otherwise load-bearing paragraph.  This is the failure mode that requires the second pass; if your read is paragraph-paced you are leaving residue.

1. **Resolve the target.**  Confirm the argument; list the `.py` files in scope (`git ls-files <target> | grep '\.py$'`).
2. **Read comments-first, per file.**  For each file: read each comment/docstring *before* its code, then read enough code to judge whether the comment is correct and oriented.  Classify KEEP / TRIM / REWRITE / DELETE per "The test every comment must pass."
3. **Run the dimension sweeps** (dims 1–5).  Greps that have a source-of-truth elsewhere (AI-tic regex → [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex); essay-bloat ratio script → `/audit-library` field-reality) are *invoked by reference* — run them, don't transcribe them into this skill.
4. **Draft replacement text for every REWRITE finding — from the code alone, *before* re-reading the original prose.**  A REWRITE finding without proposed new prose is not actionable — write the new comment as part of the punch-list so the user reviews the actual replacement, not a promise.  *Order is load-bearing:* read the code, look away from the original, draft the new comment, *then* compare against the original.  If you draft with the original in view, the wording biases you toward minimal edits and degraded prose perpetuates.  If you can't draft a coherent comment from the code alone, that itself is a finding (the comment was carrying knowledge the code doesn't make obvious — KEEP-check, or escalate to `/audit-library` if the code's the problem).  Apply the cold-reader test to your *proposed* text, not only the original — minimal-edit drafts that strip a tic often leave the surrounding prose opaque or ambiguous and the audit ships a different defect than the one it found.
5. **Score by confidence:**
   * **HIGH** — DELETE (pure label / history / provenance pointer), and REWRITE where the new text is mechanical and unambiguous (one plain what-sentence replacing a buried/superlative one).
   * **MEDIUM** — REWRITE where the new prose makes a judgment call about which why is load-bearing (essay collapse, mirror-list compression).  Sign-off needed: the user owns which constraint is the one worth keeping.
   * **LOW / question** — KEEP-check: comments that read fine to you but you're unsure carry a why a maintainer needs.  Ask rather than cut.
6. **Present the punch-list.**  Group by confidence, show proposed replacement text inline for REWRITEs.
7. **Execute HIGH as one cohesive commit.**  Run the package's tests + any sibling package that imports it (a docstring edit can't break behavior, but a multi-line string edit can fault a syntax error or shift a line a test pins).  `python scripts/run.py preflight --coverage-threshold 94` if `src/` comments in a shipped tree changed (a docstring edit can trip `CHU0NN` on the same line).
8. **Execute MEDIUM as separate commits, one per finding** — small reversible edits; if one rewrite reads worse on a second look, the rest stand.
9. **Defer code-shape findings.**  If reading the code to write a comment surfaces dead code / a lying name / a method that should split — *do not fix it here*.  File it as a `## Next` entry pointing at `/audit-library <name>` and move on.  Out-of-scope diffs riding along is the leading cause of revert traffic on audit work.

End-of-work (preflight, `plans/next-up.md` update, commit, push) is `task-checkpoint`'s job — defer to it.  Commit message mechanics are `git-commit`'s — read it before committing.  Do not re-implement either here.

## Output format

```
Comment audit: <target>
=======================

HIGH-CONFIDENCE (safe to fix):

  delete    src/<file>.py:NN — pure label / history / provenance pointer
  rewrite   src/<file>.py:NN — buried what; superlative opener
              old: "The one true path for getting this string from this area."
              new: "Returns the product ID string."
  ...

MEDIUM-CONFIDENCE (sign-off needed):

  rewrite   src/<file>.py:NN — 22-line mirror-list docstring; proposed
              collapse to the JVM/Swift constraint + 1 safety clause:
              <full proposed text>
  ...

LOW-CONFIDENCE (questions for the user):

  keep?     src/<file>.py:NN — reads fine; unsure the "<X>" clause is a
                                why a cold maintainer needs. Keep or cut?

DEFER (route elsewhere — not fixed here):

  shape     src/<file>.py:NN — lying name surfaced while reading; route
                                to /audit-library <name>
```

Tag taxonomy:

* `delete` — pure label, history, or provenance pointer; remove, add nothing (dims 3, 5).
* `rewrite` — degraded comment rebuilt from a fresh code read; new text shown (dims 1, 2, 4).
* `trim` — correct + oriented, one removable tic/clause; subtractive fix (dim 4).
* `keep?` — reads fine, unsure it carries a needed why; ask before touching.
* `shape` — code-quality finding surfaced incidentally; route to `/audit-library`, do not fix here.

## What NOT to do

* **Don't subtract a degraded comment further.**  The reflex this skill exists to break.  A comment that fails the cold-reader test gets *new prose*, not a shorter version of the broken prose.
* **Don't golf good prose.**  Sometimes the clear comment is the longer one.  `/audit-docs` framing applies: *"you don't have to be so compact, these one-liners don't say much."*  Signal-to-noise is the target, not byte count.
* **Don't strip every `the`.**  Specific singular nouns keep the article; only the redundant/accretion ones go (dim 4).
* **Don't gut a load-bearing docstring because a ratio flagged it.**  Protocol contracts, destructive-API `Args:` warnings (a wrong flash offset bricks a board), clean multi-param public docs earn their length.  Cutting them is the bloat fault inverted.
* **Don't reshape code.**  If the code needs work to make the comment honest, the *code* finding is `/audit-library`'s.  File it, don't fix it.
* **Don't auto-commit.**  Comment edits ship as flash bytes on every board and are read cold by users — surface the punch-list with proposed text first; execute HIGH only after explicit go-ahead.
* **Don't transcribe sibling source-of-truth lists.**  The AI-tic regex and per-word handling live in [`agent-style-guide.md`](../../../docs/contributing/agent-style-guide.md).  The essay-bloat ratio script lives in `/audit-library` field-reality.  The dated-history lint subset lives in `CHU012`/`CHU006`.  All three are owned elsewhere.  Invoke by reference.  A private copy here is drift, flagged by `/audit-skill` dim 6.
* **Don't expand scope mid-pass.**  A new stumble after the edit batch is a follow-up, not an extension of this pass.

## Done when

* Every HIGH finding has a commit or an explicit user skip.
* Every MEDIUM finding has a user answer — applied, deferred to `plans/next-up.md`, or dropped.
* Every `keep?` question has an answer; every `shape` finding is filed as a `## Next` entry pointing at `/audit-library`, not silently dropped.
* If `src/` comments in a shipped tree changed, `python scripts/run.py preflight --coverage-threshold 94` passes on the final state.
* Re-reading the changed comments cold (code unseen) orients the reader to what each thing does and why it exists.
