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

Read the comment *first*, then the code.  If the comment didn't prepare you for what the code does — or you had to read the code to understand the comment — the comment failed.

Then apply a second test, to the comment's own sentences: read each one the way you'd say it out loud to a colleague.  A sentence whose subject is an abstraction (*"its floor is…"*, *"the win is…"*) propped up by a weak verb, or that freezes an action into a coined noun (*"the WFI-idle that `ipoll` gives"*), is a REWRITE even when the comment is technically correct and well-oriented.  Dim 7 covers this structural defect, and it is the most common reason a comment that "reads fine" still reads as sludge.  Then classify:

* **KEEP** — states what the thing does and the non-obvious why; a cold reader is oriented before they read a line of code.  Leave it. Tighten wording only if a tic is present.
* **TRIM** — correct and oriented, carrying one removable tic or one redundant clause.  Subtractive fix is enough.
* **REWRITE** — degraded: illegible, buried, label-only, or so trimmed it no longer says what the thing is.  **Discard it.  Read the code.  Write a new comment from scratch.**  This is the default action for the residue described above — do not try to salvage word-by-word.  *Testable criterion:* if your proposed edit changes ≤1 clause and leaves the surrounding paragraph structure intact, it is TRIM, not REWRITE — even if you used the word "rewrite" while drafting.  REWRITE requires the surrounding prose to be reconsidered from the code alone; the result is usually a multi-sentence restructure, often shorter than the original.  Tagging a minimal phrase-swap as REWRITE is the failure mode the trim-only audit history produced — name the work honestly.
* **DELETE** — pure label (`# increment counter`), pure history (`# replaces the old lfs mkfs`), or a downstream/provenance pointer with no current-why content.  Remove; add nothing.

The classification spans two passes.  **Pass 1 (subtractive cleanup)** produces DELETE and TRIM findings.  **Pass 2 (whole-comment evaluation against the post-Pass-1 state)** produces REWRITE findings.  KEEP survives both passes.  See Procedure for the sequencing and why the order matters.

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

### 6. Verifiability of concrete claims

A comment that names a symbol, file path, magnitude, date, or specific behavior is making a claim the code must back up.  Stale claims fail the cold-reader test most acutely — they actively mislead.  The reader trusts the comment and acts on a name that doesn't resolve or a number that's wrong.

* **Named-symbol claims.**  *"Mirrors `chumicro_deploy.sources.PackageSource`"* when `PackageSource` doesn't exist anywhere in the package; *":meth:`Deployer.deploy_diff`"* when the method has been renamed.  Correct when written, drifted as the code moved, and now routes the reader to nothing.  Grep before classifying: if the symbol resolves, the comment's structure is the issue (dim 2 / dim 3); if it doesn't, the named claim itself is the defect and goes.
* **Magnitude claims.**  *"For a typical chumicro deploy (~200 KB staging) this lands at the floor (90 s); for a 1 MB deploy it grows to 180 s; for a 5 MB deploy to 660 s"* — versus the actual constants `BASE=120, PER_MB=600, MIN=240` which yield 240 s / 720 s / 3120 s.  Arithmetic-check every magnitude the comment exposes against the constants it claims to derive from.
* **Behavioral claims.**  *"Returns ``True`` when X, ``False`` otherwise"* against a function that actually raises on the False case.  *"No-op on Linux"* against a function that runs the cleanup unconditionally.  Read the body before classifying.

Pass 1 work — a wrong claim is DELETE (if the only content is the wrong claim), TRIM (replace the wrong value with the correct one), or DEFER to Pass 2 (when the rest of the comment depends on now-wrong scaffolding).  Verification is fast for named symbols (one grep), cheap for magnitudes (one arithmetic check), expensive for behavior (a read).  Default to verifying every named-symbol and magnitude claim a comment exposes; verify behavior when the comment's authority would surprise you to be wrong.

### 7. Sentence shape — concrete subject, real verb

A comment can pass dims 1 through 6 and still read as sludge, because the defect is structural, not in any word a regex or the other dimensions catch.  The shape that does it: an abstraction in the subject slot and a weak verb.  *"Its floor is the WFI-idle that `ipoll` gives"* names no actor and freezes an action (*"`ipoll` idles the CPU"*) into a coined noun.  Rewrite so something concrete acts: *"a connected board idles the CPU between events."*

Three faults travel together, listed in full with worked before/after in [`agent-style-guide.md` § Concrete subject, real verb](../../../docs/contributing/agent-style-guide.md#concrete-subject-real-verb-the-structural-rule): an abstract subject (*"the win is"*, *"the cost is"*), a nominalization carried by *is* / *gives* / *provides* / *performs*, and coined compound jargon.  The test is a read, not a grep.  Say the sentence the way you'd say it out loud to a colleague, and rewrite any you would not say that way.  No sweep in Pass 1 finds this.  It is Pass 2 judgment.

This dimension binds hardest on REWRITE drafts (step 7).  A draft written fresh from the code still fails the audit if it comes out nominalized, because the rewrite has rebuilt the words and kept the defect.  Apply the read-aloud test to the *proposed* prose, not only the original.

## Procedure

**Two passes, in order.**  Pass 1 makes the cleanup edits across every file in the target — the subtractive defects, DELETEs and TRIMs.  Pass 2 then runs a deeper evaluation on the post-Pass-1 state: it reads each surviving comment *as a whole* (sentence structure, what-then-why arc, paragraph shape) and asks whether a cold reader is oriented to what the thing does and why it exists.  REWRITE is the call for comments that don't.  Run Pass 1 to a commit *before* starting Pass 2: a tic stripped in Pass 1 often reveals that the surrounding prose, not the tic, was the actual defect, and reading the original Pass-1 state biases Pass 2 toward the tic and misses the residue.  This is why splitting the work pays — a single combined pass routinely tags a comment TRIM when Pass 2 on the trimmed state would have tagged it REWRITE.

The pass split also lets work parallelize: dispatch one sub-agent per file (or per subpackage) inside a pass, since per-file findings don't depend on each other.  The pass *boundary* is the synchronization point — Pass 1 collects, presents, and executes before Pass 2 begins.

**Method discipline — read fully, do not grep-shortcut.  Spare no tokens.**  This is not a pattern-match audit.  Grep can surface candidates inside Pass 1 (AI-tic regex, dated-history tokens, mirror pointers) but every candidate still gets a read to confirm it is the real case, not legitimate invariant prose (ADR 0077's *"exactly one mechanism"* and similar are KEEPs).  Pass 2 has no grep shortcut — the deliverable is cold-reader judgment, and judgment requires reading every comment.  If the target is too large for one continuous read, **split the target** (audit one subpackage at a time).  Do not switch to grep.  Token cost is not the success metric; finding the residue is.

**Inventory rule — one punch-list entry per grep hit, no implicit grouping.**  After running a sweep regex (em-dash, semicolon, arrow, AI-tic regex, `legacy`/`deprecated` tokens, magnitude/named-symbol claims), the classification step in Pass 1 step 3 must produce one punch-list entry per hit, never N-k.  The *fix shape* is allowed to repeat across entries ("all em-dashes → colons"); the *inventory* never collapses.  Worked failure: a `/audit-comments runner` Pass 1 in 2026-05 grouped ~30 em-dash hits into three pattern shapes (title, definition, parenthetical) and only enumerated the title cluster before classifying — a parallel agent ran the same regex, walked every site, and surfaced ~15 misses inside test-body docstrings, setup-list bullets, raise-message strings, and inline numbered comments that the prose-shape read had skipped.  The mechanical gate prevents this: capture each sweep's output, then ensure punch-list entry count equals hit count before moving on.

**Refresh the standing checks before Pass 1.**  Read [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex), [§ Phrase bans](../../../docs/contributing/agent-style-guide.md#phrase-bans), and [§ Definite-article tics](../../../docs/contributing/agent-style-guide.md#definite-article-tics) so the sweep operates against the current suspect list, not whatever patterns you happened to remember.  Add `→` and `⇒` to the grep list — these are flagged in the style guide's connective-tissue rule (em-dashes, semicolons, arrows), and they're easy to miss in a freeform read.  Hits are candidates, not verdicts: a flagged token that reads fine out loud (an em-dash earning its pacing, an arrow rendering a real flow) stays.

**Read paragraph-internal clauses individually, not just paragraphs as units.**  This rule binds in Pass 2 most acutely.  Pass 1's strips remove tic-shaped padding, which leaves paragraphs that read "fine" overall while a mid-paragraph parenthetical (*"(bench-confirmed across both runtimes)"*), a buried "and the test will catch drift" clause, a single bulleted item in a 15-line list, or a historical aside inside an otherwise-current explanation still encodes a defect.  Worked case: the deploy follow-up audit caught six such defects after a prior `/audit-comments deploy` pass — every one was a clause nested inside an otherwise load-bearing paragraph.  Paragraph-paced reads leave residue; clause-paced reads catch it.

### Pass 1 — subtractive sweep

1. **Resolve the target.**  Confirm the argument; list the `.py` files in scope (`git ls-files <target> | grep '\.py$'`).
2. **Sweep the subtractive cases across every file.**  Dim 6 verifiability of named-symbol / magnitude / behavioral claims (grep + arithmetic-check; wrong claims are the most reader-misleading defect and the cheapest to catch), Dim 3 mirror/provenance pointers, Dim 4 AI-tic vocabulary + redundant `the`-density + cross-site redundancy, Dim 5 change narrative / dated incident / stale "until X lands" / legacy-label-without-timeline, Dim 2 caller-naming in helper docstrings, Dim 1 superlative-tic *strip* (just the opener swap — the full plain-what-sentence rewrite is Pass 2's if the strip leaves the comment incoherent).  Greps with a source-of-truth elsewhere are invoked by reference (AI-tic regex → [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex); essay-bloat ratio script → `/audit-library` field-reality), not transcribed.  **Capture each sweep's output to a scratch file** (`.scratch/audit-comments-<target>-<sweep>.txt`) so the inventory gate in step 3 has something to count against.
3. **Inventory gate — classify every hit, one punch-list entry per site.**  Re-check `wc -l` on each captured sweep file against the punch-list entry count for that sweep before moving on; if they differ, you skipped sites and the audit is incomplete.  No implicit grouping: "all em-dashes → colons" describes the *fix shape*, not a classification shortcut.  Classify each entry as one of:
   * **DELETE:** pure label / history / provenance / caller-naming with no current-why content.
   * **TRIM:** the strip leaves the surrounding comment correct and oriented.
   * **DEFER:** the strip would leave the comment incoherent — mark for Pass 2 to handle as REWRITE, do not attempt a partial fix here.
   * **KEEP:** the hit is legitimate prose (ADR 0077-style invariant; a `the` that earns its specificity; an em-dash inside `print()` / error-message strings, which are user-facing output and out of scope for this skill).  Record KEEP-with-reason in the punch-list so the next auditor doesn't re-surface it.
4. **Present the subtractive punch-list.**  Group by confidence.  HIGH: DELETEs and mechanical TRIMs (one tic, one redundant clause).  MEDIUM: TRIMs where which clause to cut is a judgment call (the home site in a 3-way redundancy, the load-bearing `the` in a stacked-article paragraph).
5. **Execute Pass 1.**  HIGH as one cohesive commit; MEDIUM as separate commits.  Run `python scripts/run.py preflight --coverage-threshold 94` if `src/` comments in a shipped tree changed (a docstring edit can trip `CHU0NN` on the same line or shift a line a test pins).

### Pass 2 — reconstructive sweep

6. **Read the post-Pass-1 state cold, evaluating each comment as a whole.**  Pull a fresh read of each file in the target.  For each surviving comment/docstring: read the comment *first*, then enough code to judge whether it passes "The test every comment must pass."  This pass is not clause-grading — Pass 1 already did that.  This pass asks two things.  First, whether the comment's overall shape (sentence order, what-then-why arc, paragraph structure) orients a cold reader to what the thing does and why it exists.  A comment whose arc buries the what, leads with rationale before the contract, or sums to less than the code teaches the reader on its own fails and goes to REWRITE.  Second, whether each individual sentence passes the read-aloud structural test (dim 7): say it the way you'd say it out loud to a colleague, and a sentence built on an abstract subject and a weak verb (*"its floor is the WFI-idle that `ipoll` gives"*) is a REWRITE even when the arc is fine.  Do not assume the sentences read fine because no tic survived Pass 1, since the structural defect carries no banned word.  A comment that passes both stays KEEP.  Pass 1's DEFERs feed in here as REWRITE candidates.

   **Run a file-level cross-site sweep before per-comment classification.**  Read the module docstring, class docstrings, method docstrings, and attribute comments *together* — not one at a time.  The same fact stated in 2+ sites that didn't trip CHU027 (paraphrased, or sub-threshold at <12 tokens, or <3 in-package sites) names a *home* — usually the broadest scope where the fact is most discoverable — and the others collapse to a cross-reference or DELETE.  Per-comment review misses this because each site reads fine alone; the home-finding move happens only when the docs are read together.  Worked shape: a "Read via :func:`ast.parse` (no execution)" sentence repeated in a module docstring and three function docstrings collapses to the module docstring as the home; each function's repetition drops.
7. **Draft replacement text for every REWRITE — from the code alone, *before* re-reading the original prose.**  A REWRITE finding without proposed new prose is not actionable; the punch-list shows the actual replacement.  *Order is load-bearing:* read the code, look away from the original, draft the new comment, *then* compare against the original.  Drafting with the original in view biases you toward minimal edits and degraded prose perpetuates.  If you can't draft a coherent comment from the code alone, that itself is a finding — the comment was carrying knowledge the code doesn't make obvious (KEEP-check, or escalate to `/audit-library` if the code's the problem).  Apply the cold-reader test *and* the read-aloud structural test (dim 7) to your *proposed* text, not only the original.  Minimal-edit drafts that strip a tic often leave the surrounding prose opaque or ambiguous, and a fresh draft that comes out nominalized (an abstract subject, a coined noun, a weak verb) has rebuilt the words and kept the defect.  Say your replacement out loud as if explaining it to a colleague before you commit it.
8. **Score by confidence:**
   * **HIGH** — REWRITE where the new text is mechanical and unambiguous (one plain what-sentence replacing a buried/superlative one).
   * **MEDIUM** — REWRITE where the new prose makes a judgment call about which why is load-bearing (essay collapse, mirror-list compression).  Sign-off needed: the user owns which constraint is the one worth keeping.
   * **LOW / question** — KEEP-check: comments that read fine to you but you're unsure carry a why a maintainer needs.  Ask rather than cut.
9. **Present the reconstructive punch-list.**  Group by confidence, show proposed replacement text inline for REWRITEs.
10. **Execute Pass 2.**  HIGH as one cohesive commit; MEDIUM as separate commits, one per finding (small reversible edits; if one rewrite reads worse on a second look, the rest stand).  Re-run preflight per Pass 1 step 5 if `src/` comments changed.
11. **Defer code-shape findings throughout.**  If reading the code to write a comment surfaces dead code / a lying name / a method that should split — *do not fix it here*.  File it as a `## Next` entry pointing at `/audit-library <name>` and move on.  Out-of-scope diffs riding along is the leading cause of revert traffic on audit work.

After Pass 2, invoke the `task-checkpoint` skill — it owns preflight, `plans/next-up.md` refresh, commit, and push.  Read the `git-commit` skill before committing for the heredoc mechanics.  Don't re-implement either here, and don't stop without invoking `task-checkpoint`.

## Output format

Each pass produces its own punch-list using the shape below.  Pass 1's distribution is dominated by `delete` and `trim`; Pass 2's by `rewrite` and `keep?`.  Label the punch-list header so the user knows which pass they are reviewing (`Comment audit (Pass 1 — subtractive): <target>`, `Comment audit (Pass 2 — rewrites): <target>`).

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

## Anti-patterns

* **Don't subtract a degraded comment further.**  The reflex this skill exists to break.  A comment that fails the cold-reader test gets *new prose*, not a shorter version of the broken prose.
* **Don't golf good prose.**  Sometimes the clear comment is the longer one.  `/audit-docs` framing applies: *"you don't have to be so compact, these one-liners don't say much."*  Signal-to-noise is the target, not byte count.
* **Don't strip every `the`.**  Specific singular nouns keep the article; only the redundant/accretion ones go (dim 4).
* **Don't strip every em-dash.**  Em-dashes that earn their place (pacing a parenthetical so a comma would mis-pace, connecting two real ideas where a sentence break would be choppy) stay.  Only the ones papering over missing connective tissue go.  Same posture for semicolons and arrows.  Read each aloud before flagging.
* **Don't gut a load-bearing docstring because a ratio flagged it.**  Protocol contracts, destructive-API `Args:` warnings (a wrong flash offset bricks a board), clean multi-param public docs earn their length.  Cutting them is the bloat fault inverted.
* **Don't reshape code.**  If the code needs work to make the comment honest, the *code* finding is `/audit-library`'s.  File it, don't fix it.
* **Don't auto-commit.**  Comment edits ship as flash bytes on every board and are read cold by users — surface the punch-list with proposed text first; execute HIGH only after explicit go-ahead.
* **Don't transcribe sibling source-of-truth lists.**  The AI-tic regex and per-word handling live in [`agent-style-guide.md`](../../../docs/contributing/agent-style-guide.md).  The essay-bloat ratio script lives in `/audit-library` field-reality.  The dated-history lint subset lives in `CHU012`/`CHU006`.  All three are owned elsewhere.  Invoke by reference.  A private copy here is drift, flagged by `/audit-skill` dim 6.
* **Don't expand scope mid-pass.**  A new stumble after the edit batch is a follow-up, not an extension of this pass.

## Done when

* Both Pass 1 (subtractive) and Pass 2 (whole-comment evaluation) ran across every file in the target, each producing its own punch-list and commit cycle.
* Every Pass 1 sweep's hit count matches its punch-list entry count (inventory gate — no implicit grouping, every site classified individually).
* Every HIGH finding has a commit or an explicit user skip.
* Every MEDIUM finding has a user answer — applied, deferred to `plans/next-up.md`, or dropped.
* Every `keep?` question has an answer; every `shape` finding is filed as a `## Next` entry pointing at `/audit-library`, not silently dropped.
* If `src/` comments in a shipped tree changed, `python scripts/run.py preflight --coverage-threshold 94` passes on the final state.
* Re-reading the changed comments cold (code unseen) orients the reader to what each thing does and why it exists, and each sentence reads the way you'd say it out loud to a colleague (concrete subject, real verb, dim 7), not as an abstract subject propped up by a weak verb.
