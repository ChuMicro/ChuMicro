---
name: audit-comments
description: Audit code comments and docstrings in a file, library, or tree for whether a cold reader learns what the thing does and why it exists. Unlike the trim-only comment passes inside /audit-library, this skill rewrites a degraded comment from a fresh read of the code rather than subtracting it further. Use when comments have gone illegible after repeated audits, after a feature pass, or before a release-prep pass.
---

# Comment audit

Audit the comments and docstrings of a target (`libraries/<name>/`, `workbench/<name>/`, a single `.py`, or a subtree) for one question: **if a reader knew nothing about this code and read only this comment, would they know what the thing does and why it exists?**  Output a prioritized punch-list, then execute the high-confidence batch with the user's go-ahead.

This skill reads code *only as much as it takes to write a correct comment*.  It does not reshape code, flag dead code, or restructure methods — those route to `/audit-library`.  One responsibility: the prose.

## Why this is its own skill

`/audit-library` §6 audits comments but only **subtracts** — its rule is *"don't golf, if the shape is clear leave it."* Run that enough and you get residue: a sentence that survived three subtractive passes, each removing a word, none ever asking *what should this say?*

For comments specifically, that posture is inverted here: **a comment that fails the cold-reader test is rewritten from a fresh read of the code, not trimmed.** Trimming a degraded comment makes it shorter and more illegible. The fix is new prose written by someone who just read the code.

`/audit-library` §6 *surfaces* comment candidates (essay-bloat ratio sweep, AI-tic grep) and defers the rewrite here. Deterministic drift (dated incidents, `Decision NNNN` in shipped trees, cross-site duplicates) is the lint's job (`CHU012`, `CHU006`, dedup rules in `plans/open-questions.md`). Semantic judgment — *is this comment narrating a change, labeling the code, or explaining the current why?* — is this skill's.

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

Read the comment *first*, then the code. If the comment didn't prepare you for what the code does, or you had to read the code to understand the comment, the comment failed.

Then apply structural + stance tests to the prose itself. **Dim 7 (structural):** read each sentence aloud — an abstraction in the subject slot propped up by a weak verb (*"its floor is the WFI-idle that `ipoll` gives"*) is a REWRITE even when technically correct, and is the most common reason a comment that "reads fine" still reads as sludge. **Dim 8 (stance):** defensive padding, anxious hedging, and step-by-step narration of self-evident code read as scaffolding the reader doesn't need.

Then classify:

* **KEEP** — states what the thing does and the non-obvious why; a cold reader is oriented before they read a line of code.  Leave it. Tighten wording only if a tic is present.
* **TRIM** — correct and oriented, carrying one removable tic or one redundant clause.  Subtractive fix is enough.
* **REWRITE** — degraded: illegible, buried, label-only, or so trimmed it no longer says what the thing is.  **Discard it.  Read the code.  Write a new comment from scratch.**  Do not salvage word-by-word.  *Testable criterion:* if your edit changes ≤1 clause and leaves surrounding paragraph structure intact, it is TRIM, not REWRITE — even if you used the word "rewrite" while drafting.  Tagging a minimal phrase-swap as REWRITE is the failure mode the trim-only audit history produced; name the work honestly.
* **DELETE** — pure label (`# increment counter`), pure history (`# replaces the old lfs mkfs`), or a downstream/provenance pointer with no current-why content.  Remove; add nothing.

The classification spans two passes.  **Pass 1 (subtractive cleanup)** produces DELETE and TRIM findings.  **Pass 2 (whole-comment evaluation against the post-Pass-1 state)** produces REWRITE findings.  KEEP survives both passes.  See Procedure for the sequencing and why the order matters.

## Audit dimensions

Run each over the target.  Capture findings as `file:line` + one-line description + dimension tag (see Output format).

### 1. Says-what-it-does, plainly, first

A docstring's first sentence orients the reader: *what this returns / does*, in plain words, before any why.

* **Definition-by-superlative.**  *"The one true path for getting this string"*, *"the single source for X"* as an opener — the banned `the (one|single|sole) <noun> (that|which|is)` tic (same family as *"the canonical X"*; see [`agent-style-guide.md` § "the one / single / sole X that…"](../../../docs/contributing/agent-style-guide.md#the-one--single--sole-x-that)).  Rewrite to the plain statement: *"Returns the product ID string."*  *Triage, not auto-flag* — legitimate invariant prose (*"the single owner of the staging path"*, ADR 0077's *"exactly one mechanism"*) is a KEEP.
* **Why with no what.**  A docstring that jumps straight to rationale/safety without ever saying what the function returns or does.  The reader gets *why it's careful* before *what it is*.  Rewrite: plain what-sentence first, then the why.
* **What buried under provenance.**  The real one-line description exists but sits under three paragraphs of where-this-came-from.  Lift the what to sentence one; cut or compress the rest per dim 3/4.
* **Abstract subject opening.**  *"The cross-runtime sleep adapter blocks long enough for ticks to move"* as the opener of a test docstring for `sleep_ms(5)` — the subject (*"the adapter"*) is an abstract noun standing in for the concrete callable.  Test: substitute the actual identifier for the subject; if the sentence reads more useful, the opener failed.  Rewrite by naming the concrete thing: *"`sleep_ms(5)` returns within 500 ms with non-negative elapsed ticks."*  Overlaps dim 7 (sentence-shape rule), owned here because the opener is the most load-bearing sentence — dim 7 catches the defect everywhere; dim 1 makes the opener case explicit so an auditor doesn't gloss it.
* **Title-fragment opener.**  *"Tick-driven non-blocking connect."* / *"Cross-runtime tick adapter."* / *"Non-blocking HTTP client."* — a noun phrase that names the topic but doesn't form a sentence stating what the thing *is* or *does*.  A cold reader doesn't learn whether `SocketConnector` *is* a connector, *manages* connecting, or *holds* connection state.  Rewrite as a statement: *"Advances a non-blocking TCP/TLS connect across multiple ticks, one phase per `tick(now_ms)` call."*  Title-fragments survive every Pass 1 sweep because no banned word is in them, and they survive dim 7 too because there's no abstract subject to flag — they have no subject at all.
* **Concept-name without identifier.**  *"Subclasses provide the runtime-specific advance methods (DNS resolve, async TCP connect, TLS handshake step)."* names the *phases* (the concepts) without naming the *override targets* (the actual methods).  A subclass author can't act on this without reading source.  When a docstring tells the reader that subclasses / consumers / callers will do something, name what they override / call / instantiate.  *"Subclasses override `_resolve_dns()`, `_start_tcp_connect()`, `_check_tcp_connect()`, `_step_tls_handshake()` with runtime-specific implementations"* beats the concept-only form.  Same family as the dim 6 verifiability check (named-symbol claims), inverted: dim 6 catches a wrong name; this catches the *missing* name.

### 2. Directional honesty — confined code must not name its callers

A low-level helper's comment that names its downstream callers is a leak: the helper is now coupled, in prose, to code it should not know about.

* **"Called from X / used by Y" in a helper docstring** — *"Called from each platform's `_setup_session(...)`"*.  The helper does not get to know who calls it.  Rewrite to the contract + an abstract usage hint: *"Installs the plugins shared by every HTTP client.  Use as the shared config for downstream clients."*
* **Upstream comment encoding a downstream invariant** — *"the caller must call close() after this"* is a real contract and stays; *"the deploy CLI passes this as --foo"* names a specific consumer and goes.  Test: would the comment still be true and useful if a *different* caller used it?  If naming the caller is the only content, delete the naming.

### 3. Provenance and reference-project noise

Comments that point outside the realm of *this* code are noise to the reader of this code.

* **Mirror / port pointers** — *"Mirrors `paho.mqtt.client.Client.connect()`"*, *"ported from a reference MQTT implementation"*, *"matches the reference impl"*.  The reader of this file cannot act on a sibling/upstream project name.  Delete the pointer; keep only the behavioral content (*"uses the OS trust store"*).  For shipped trees this is also `CHU006`'s deterministic subset (mono-repo refs) — but the broader provenance class (any external-repo / reference-impl name) is judgment, owned here.
* **Enumerated mirror lists** — a docstring whose bulk is *"- repo-A does it with X; - repo-B does it with Y"*.  The reader needs *what this code does*, not a comparative survey.  Rewrite to the irreducible technical why (the constraint that forced this approach), drop the survey.  Worked shape: a 22-line cert-parsing docstring enumerating two reference impls collapses to 6 lines stating the JVM/Swift constraint, the byte-reinterpret approach, and the one load-bearing safety clause.

### 4. Signal-to-noise

Every sentence must change what the reader knows or does next.  Sentences that don't, go.

* **`the`-density as a symptom (not a target).**  Stacked articles and sentence-initial `the` before brand names usually mark prose written by accretion.  Per-noun forward-reference test + brand-name + stacked-article shapes: [`agent-style-guide.md` § Definite-article tics](../../../docs/contributing/agent-style-guide.md#definite-article-tics).  Apply the forward-reference test to REWRITE drafts, not only originals — inherited `the`s the rewrite didn't earn compound across passes.  Reduce as a *symptom* of low signal.
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
* **Test docstring overclaim.**  *"`sleep_ms()` advances the clock"* on a test whose only asserts are `elapsed >= 0` and `elapsed < 500` (which allow zero); *"the parser handles malformed input correctly"* on a test that only checks one specific malformed case.  The test *name* and the test's asserts are different claims; the docstring describes what the asserts prove, not what the name aspires to.  Causal connectors (*"so"*, *"because"*, *"therefore"*) need the second clause to be a real consequence the asserts observe — independent checks join with *"and"* or a comma.  Read the assert block before classifying.

Pass 1 work — a wrong claim is DELETE (if the only content is the wrong claim), TRIM (replace the wrong value with the correct one), or DEFER to Pass 2 (when the rest of the comment depends on now-wrong scaffolding).  Verification is fast for named symbols (one grep), cheap for magnitudes (one arithmetic check), expensive for behavior (a read).  Default to verifying every named-symbol and magnitude claim a comment exposes; verify behavior when the comment's authority would surprise you to be wrong.

### 7. Sentence shape — concrete subject, real verb

A comment can pass dims 1 through 6 and still read as sludge, because the defect is structural, not in any word a regex or the other dimensions catch.  The shape that does it: an abstraction in the subject slot and a weak verb.  *"Its floor is the WFI-idle that `ipoll` gives"* names no actor and freezes an action (*"`ipoll` idles the CPU"*) into a coined noun.  Rewrite so something concrete acts: *"a connected board idles the CPU between events."*

Three faults travel together, listed in full with worked before/after in [`agent-style-guide.md` § Concrete subject, real verb](../../../docs/contributing/agent-style-guide.md#concrete-subject-real-verb-the-structural-rule): an abstract subject (*"the win is"*, *"the cost is"*), a nominalization carried by *is* / *gives* / *provides* / *performs*, and coined compound jargon.  The test is a read, not a grep.  Say the sentence the way you'd say it out loud to a colleague, and rewrite any you would not say that way.  No sweep in Pass 1 finds this.  It is Pass 2 judgment.

**Generic role-nouns are the easier-to-miss version of the abstract subject.** *"Constructor stores X"*, *"Subclasses provide Y"*, *"Callers must call Z"*, *"Implementations override W"* — the role-noun feels concrete (it refers to *some* real thing) but it's a category abstraction; a specific class / method / function would name the actor.  *"`__init__` stores the dial parameters (host, port, optional TLS context)"* beats *"Constructor stores the dial parameters"*.  *"Runtime-specific subclasses (`CPSocketConnector`, `MPSocketConnector`) override `_resolve_dns()` and friends"* beats *"Subclasses provide the runtime-specific advance methods"*.  Same defect as the WFI-idle case, less obvious shape — and the most common reason an auditor's "every sentence has a concrete subject" verdict is wrong.

This dimension binds hardest on REWRITE drafts (step 7).  A draft written fresh from the code still fails the audit if it comes out nominalized, because the rewrite has rebuilt the words and kept the defect.  Apply the read-aloud test to the *proposed* prose, not only the original.

### 8. Stance toward the reader

A comment is a conversation across time — past-author speaking to future-reader.  Dims 1-7 catch comments that *fail* mechanically; this dimension catches comments that *pass mechanically but read wrong*.  Ask: does this comment treat the reader as a thinking colleague, or as someone who needs every step spelled out?

Common shapes that fail:

* **Defensive padding** (*"just to be safe"*, *"this might"*, *"in case"*) — apologizing for the code instead of explaining it.  The hedge doesn't tell the reader what specifically to watch for.
* **Step-by-step narration of self-evident code** — *"first we get the value, then we increment it, then we return it"* over `return value + 1`.  The reader can read code; tell them what they can't see.
* **Anxious hedging** (*"I think this"*, *"should probably"*) — signals the writer is unsure.  If the writer's unsure, the comment should say what specifically is uncertain, not hedge generically.
* **Audit-pass posturing** — *"intentionally not closing this because [3 lines of justification]"* on a line where the close decision is obvious.  The comment exists to defend against a hypothetical reviewer, not to teach the reader.

The fix: rewrite as if explaining the code to a colleague at a whiteboard.  Trust them to think.  If the comment doesn't tell them something they couldn't read in the code, it shouldn't exist.

Like dim 7, this is Pass 2 judgment — no Pass 1 sweep catches it.  Apply to both originals and REWRITE drafts.

## Procedure

**Two passes, in order.**  Pass 1 makes the cleanup edits across every file in the target — the subtractive defects, DELETEs and TRIMs.  Pass 2 then runs a deeper evaluation on the post-Pass-1 state: it reads each surviving comment *as a whole* (sentence structure, what-then-why arc, paragraph shape) and asks whether a cold reader is oriented to what the thing does and why it exists.  REWRITE is the call for comments that don't.  Run Pass 1 to a commit *before* starting Pass 2: a tic stripped in Pass 1 often reveals that the surrounding prose, not the tic, was the actual defect, and reading the original Pass-1 state biases Pass 2 toward the tic and misses the residue.  This is why splitting the work pays — a single combined pass routinely tags a comment TRIM when Pass 2 on the trimmed state would have tagged it REWRITE.

The pass split also lets work parallelize: dispatch one sub-agent per file (or per subpackage) inside a pass, since per-file findings don't depend on each other.  The pass *boundary* is the synchronization point — Pass 1 collects, presents, and executes before Pass 2 begins.

**Method discipline — read fully, do not grep-shortcut.  Spare no tokens.**  This is not a pattern-match audit.  Grep can surface candidates inside Pass 1 (AI-tic regex, dated-history tokens, mirror pointers) but every candidate still gets a read to confirm it is the real case, not legitimate invariant prose (ADR 0077's *"exactly one mechanism"* and similar are KEEPs).  Pass 2 has no grep shortcut — the deliverable is cold-reader judgment, and judgment requires reading every comment.  If the target is too large for one continuous read, **split the target** (audit one subpackage at a time).  Do not switch to grep.  Token cost is not the success metric; finding the residue is.

**Inventory rule — one punch-list entry per grep hit, no implicit grouping.**  After running a sweep regex (em-dash, semicolon, arrow, AI-tic regex, `legacy`/`deprecated` tokens, magnitude/named-symbol claims), Pass 1 step 3 must produce one entry per hit, never N-k.  The *fix shape* may repeat ("all em-dashes → colons"); the *inventory* never collapses.  Worked failure: grouping ~30 em-dash hits into three pattern shapes and enumerating only one cluster missed ~15 sites in test-body docstrings and inline numbered comments.  Mechanical gate: capture each sweep's output, then ensure punch-list entry count equals hit count before moving on.

**Refresh the standing checks before Pass 1.**  Read [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex), [§ Phrase bans](../../../docs/contributing/agent-style-guide.md#phrase-bans), and [§ Definite-article tics](../../../docs/contributing/agent-style-guide.md#definite-article-tics) so the sweep operates against the current suspect list, not whatever patterns you happened to remember.  Add `→` and `⇒` to the grep list — these are flagged in the style guide's connective-tissue rule (em-dashes, semicolons, arrows), and they're easy to miss in a freeform read.  Hits are candidates, not verdicts: a flagged token that reads fine out loud (an em-dash earning its pacing, an arrow rendering a real flow) stays.

**Read paragraph-internal clauses individually, not just paragraphs as units.**  This rule binds in Pass 2 most acutely.  Pass 1's strips remove tic-shaped padding, leaving paragraphs that read "fine" while a mid-paragraph parenthetical (*"(bench-confirmed across both runtimes)"*), a buried "and the test will catch drift" clause, a single bulleted item in a 15-line list, or a historical aside inside otherwise-current prose still encodes a defect.  Paragraph-paced reads leave residue; clause-paced reads catch it.

### The auditor's bias problem

The auditor reads the code and the existing prose, then judges the prose, applies trims, and proposes rewrites — knowing what's there before knowing what should be there.  That makes the auditor a biased reader of both the post-trim state and any proposed replacement: the "this looks fine" verdict on your own work is unreliable.

The `audit-comments-verifier` subagent runs twice — once on the post-Pass-1 state (step 5a) and once on the post-Pass-2 state (step 7b).  Each pass closes its own bias gap:

* **Step 5a (post-Pass-1):** the verifier reads the trimmed state blind to the pre-trim prose.  Catches rule violations the auditor missed in the sweep (an AI-tic word not in the standing regex, a comment left incoherent after a trim that wasn't marked DEFER, cross-site redundancy that survived).  Findings flow into Pass 2 step 6 as additional REWRITE input.
* **Step 7b (post-Pass-2):** the verifier reads the rewritten state blind to the original prose.  Catches degraded rewrites (a draft that came out nominalized, a missing contract, a body paragraph that survived the persona).  Findings consolidate at step 7c.

Pass 2 step 7's "look away from the original, draft the new comment, then compare" is the auditor's own procedural discipline against bias; the verifier dispatches are the independent check.

When reporting to the user, prefer the verifier's findings over your own observations on contested calls.  Surface auditor / verifier disagreements visibly in the walk — let the user break the tie, don't substitute your bias for the verifier's blindness.

### Pass 1 — subtractive sweep

1. **Resolve the target.**  Confirm the argument; list the `.py` files in scope (`git ls-files <target> | grep '\.py$'`).
2. **Sweep the subtractive cases across every file.**  Dim 6 verifiability of named-symbol / magnitude / behavioral claims (grep + arithmetic-check; wrong claims are the most reader-misleading defect and the cheapest to catch), Dim 3 mirror/provenance pointers, Dim 4 AI-tic vocabulary + redundant `the`-density + cross-site redundancy, Dim 5 change narrative / dated incident / stale "until X lands" / legacy-label-without-timeline, Dim 2 caller-naming in helper docstrings, Dim 1 superlative-tic *strip* (just the opener swap — the full plain-what-sentence rewrite is Pass 2's if the strip leaves the comment incoherent).  Greps with a source-of-truth elsewhere are invoked by reference (AI-tic regex → [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex); essay-bloat ratio script → `/audit-library` field-reality), not transcribed.  **Capture each sweep's output to a scratch file** (`.scratch/audit-comments-<target>-<sweep>.txt`) so the inventory gate in step 3 has something to count against.
3. **Inventory gate — classify every hit, one punch-list entry per site.**  Re-check `wc -l` on each captured sweep file against the punch-list entry count for that sweep before moving on; if they differ, you skipped sites and the audit is incomplete.  No implicit grouping: "all em-dashes → colons" describes the *fix shape*, not a classification shortcut.  Classify each entry as one of:
   * **DELETE:** pure label / history / provenance / caller-naming with no current-why content.
   * **TRIM:** the strip leaves the surrounding comment correct and oriented.
   * **DEFER:** the strip would leave the comment incoherent — mark for Pass 2 to handle as REWRITE, do not attempt a partial fix here.
   * **KEEP:** the hit is legitimate prose (ADR 0077-style invariant; a `the` that earns its specificity; an em-dash inside `print()` / error-message strings, which are user-facing output and out of scope for this skill).  Record KEEP-with-reason in the punch-list so the next auditor doesn't re-surface it.
4. **Present the subtractive punch-list.**  Group by confidence.  HIGH: DELETEs and mechanical TRIMs (one tic, one redundant clause).  MEDIUM: TRIMs where which clause to cut is a judgment call (the home site in a 3-way redundancy, the load-bearing `the` in a stacked-article paragraph).
5. **Execute Pass 1.**  HIGH as one cohesive commit — DELETEs and mechanical TRIMs need no per-finding judgment.  Walk each MEDIUM finding via `AskUserQuestion`, one commit per applied finding ([Walking MEDIUM and LOW findings](#walking-medium-and-low-findings)).  Run `python scripts/run.py preflight --coverage-threshold 94` after each commit if `src/` comments in a shipped tree changed — a docstring edit can trip `CHU0NN` on the same line or shift a line a test pins.
5a. **Dispatch the `audit-comments-verifier` subagent on the post-Pass-1 `libraries/<name>/src/`.**  Wait until every Pass 1 commit (HIGH batch + MEDIUM walked items) has landed — the verifier reads the committed state, not a mid-walk intermediate.  See [The auditor's bias problem](#the-auditors-bias-problem) for why this dispatch exists.  Same persona, same task-prompt template as step 7b; one verifier per library, not per file.

    ```
    Agent(
        subagent_type="audit-comments-verifier",
        model="opus",
        description="<library> Pass 1 verifier",
        prompt="<task only — see step 7b template>",
        run_in_background=True,
    )
    ```

5b. **Carry verifier findings into Pass 2 step 6 as REWRITE input.**  Pass 1 ships as-is; do not open a Pass 1 supplement commit.  Map verifier tier onto Pass 2 confidence the same way step 7c does (CRITICAL → at-least-MEDIUM, IMPORTANT → at-least-MEDIUM, MINOR filtered by default, AMBIGUOUS → LOW).  A verifier-surfaced CRITICAL with a one-line mechanical fix lands as a Pass 2 HIGH REWRITE in step 8; everything else feeds Pass 2 step 6's cold-read evaluation alongside Pass 1's DEFERs.

### Pass 2 — reconstructive sweep

6. **Read the post-Pass-1 state cold, evaluating each comment as a whole.**  Pull a fresh read of each file in the target.  For each surviving comment/docstring: read the comment *first*, then enough code to judge whether it passes "The test every comment must pass."  This pass is not clause-grading — Pass 1 already did that.  This pass asks four things.  First, whether the comment's overall shape (sentence order, what-then-why arc, paragraph structure) orients a cold reader to what the thing does and why it exists.  A comment whose arc buries the what, leads with rationale before the contract, or sums to less than the code teaches the reader on its own fails and goes to REWRITE.  Second, whether each individual sentence passes the read-aloud structural test (dim 7): say it the way you'd say it out loud to a colleague, and a sentence built on an abstract subject and a weak verb (*"its floor is the WFI-idle that `ipoll` gives"*) is a REWRITE even when the arc is fine.  Do not assume the sentences read fine because no tic survived Pass 1, since the structural defect carries no banned word.  Generic role-nouns (*"Constructor stores"*, *"Subclasses provide"*) are this dimension's most-missed shape — they read concrete but are category abstractions; flag them.  Third, whether the comment passes the stance test (dim 8): does it treat the reader as a thinking colleague, or as someone who needs every step spelled out?  Defensive padding, anxious hedging, step-by-step narration of self-evident code, and audit-pass posturing all pass dims 1-7 but fail this one.  Fourth, **draft what the ideal comment would say from a fresh read of the code — what does it *do*, what does it *return*, what's its *contract* (done condition, error semantics), what does a cold reader *need* to act?  Compare your draft against the actual.  Items present in your draft but absent from the actual are findings — tag `missing`.**  This makes the missing-content question explicit; without it, the cold-reader test catches what's *wrong* with what's there but misses what's *not* there (the docstring that describes phases without naming override targets, that names a method without saying what it returns, that omits the done condition entirely).  A comment that passes all four stays KEEP.  Pass 1's DEFERs and step 5b's verifier findings both feed in here as REWRITE candidates.

   **Run a file-level cross-site sweep before per-comment classification.**  Read the module docstring, class docstrings, method docstrings, and attribute comments *together* — not one at a time.  The same fact stated in 2+ sites that didn't trip CHU027 (paraphrased, or sub-threshold at <12 tokens, or <3 in-package sites) names a *home* — usually the broadest scope where the fact is most discoverable — and the others collapse to a cross-reference or DELETE.  Per-comment review misses this because each site reads fine alone; the home-finding move happens only when the docs are read together.  Worked shape: a "Read via :func:`ast.parse` (no execution)" sentence repeated in a module docstring and three function docstrings collapses to the module docstring as the home; each function's repetition drops.
7. **Draft replacement text for every REWRITE — from the code alone, *before* re-reading the original prose.**  A REWRITE finding without proposed new prose is not actionable; the punch-list shows the actual replacement.  *Order is load-bearing:* read the code, look away from the original, draft the new comment, *then* compare against the original.  Drafting with the original in view biases you toward minimal edits and degraded prose perpetuates.  If you can't draft a coherent comment from the code alone, that itself is a finding — the comment was carrying knowledge the code doesn't make obvious (KEEP-check, or escalate to `/audit-library` if the code's the problem).  Apply the cold-reader test, the read-aloud structural test (dim 7), and the stance test (dim 8) to your *proposed* text, not only the original.  Minimal-edit drafts that strip a tic often leave the surrounding prose opaque or ambiguous; a fresh draft that comes out nominalized has rebuilt the words and kept the structural defect; a fresh draft that comes out defensive or scaffolding has rebuilt the words and kept the stance defect.  Say your replacement out loud as if explaining it to a colleague before you commit it.
7a. **Apply each proposed REWRITE to `libraries/<name>/src/` in place** (uncommitted).  The verifier dispatched at step 7b reads the post-apply state — it has no access to your draft otherwise.  Track each `(file:line, original_text, proposed_text)` tuple in your working memory so the per-finding walk at step 10 can revert a hunk if the user declines.  If the user later reverts the whole pass, `git restore libraries/<name>/src/` rolls every applied rewrite back.
7b. **Dispatch the `audit-comments-verifier` subagent** on `libraries/<name>/src/`.  See [The auditor's bias problem](#the-auditors-bias-problem) for why the verifier exists.  The harness loads `.claude/agents/audit-comments-verifier.md` as the subagent's system prompt; the director does NOT read or embed the persona file.

    ```
    Agent(
        subagent_type="audit-comments-verifier",
        model="opus",
        description="<library> Pass 2 verifier",
        prompt="<task only — see template below>",
        run_in_background=True,
    )
    ```

    Task prompt:

    ````
    Read these Python files and produce findings per the output format in your system prompt:

    <list of paths to the post-apply files in libraries/<name>/src/>

    Do not read any other files. Judge each file standalone as a cold reader.

    Report the findings.
    ````

    Wait for the verifier to complete before proceeding.  On a multi-file library, one verifier dispatch covers the whole tree — one verifier per library, not per file.  (Per-file parallel dispatch loses cross-file cohesion findings the auditor's step 6 cross-site sweep already covers; whole-tree dispatch is sufficient.)

7c. **Consolidate verifier findings with your draft analysis.**  Verifier tier maps onto auditor confidence:

    * **CRITICAL** (named rule break) → at least MEDIUM.  HIGH if the fix is one-line and unambiguous (drop the AI-tic word, drop the body paragraph); MEDIUM if it requires a judgment-call rewrite.
    * **IMPORTANT** (cold-reader failure) → at least MEDIUM.
    * **MINOR** (stylistic) → filter by default.  Surface only when the user asked for exhaustive review or total CRITICAL+IMPORTANT count is under 3.
    * **AMBIGUOUS** → LOW.  Verifier flagged because project context resolves it; only the user can.

    Verifier findings the auditor missed get appended to the punch-list, tagged `verifier-surfaced`.  Auditor findings the verifier cleared: keep, but downgrade one tier — the verifier is the cold-reader check, not a veto.  Tier disagreements: keep both, surface in step 9 and the per-finding walk at step 10.
8. **Score by confidence:**
   * **HIGH** — REWRITE where the new text is mechanical and unambiguous (one plain what-sentence replacing a buried/superlative one).
   * **MEDIUM** — REWRITE where the new prose makes a judgment call about which why is load-bearing (essay collapse, mirror-list compression).  Sign-off needed: the user owns which constraint is the one worth keeping.
   * **LOW / question** — KEEP-check: comments that read fine to you but you're unsure carry a why a maintainer needs.  Ask rather than cut.

   When the verifier (step 7b) tiered a finding differently from the auditor, carry both tiers into step 9 so the user sees the disagreement.  `_shared/walk-pattern.md` § "Verifier integration" covers how the walk presents this.
9. **Present the reconstructive punch-list.**  Group by confidence, show proposed replacement text inline for REWRITEs.
10. **Execute Pass 2.**  HIGH REWRITEs as one cohesive commit — these are mechanical by definition (step 8) and need no per-finding pause.  Walk each MEDIUM REWRITE and each LOW `keep?` via `AskUserQuestion`, one commit per applied finding ([Walking MEDIUM and LOW findings](#walking-medium-and-low-findings)).  Small reversible edits — if one rewrite reads worse on a second look, the rest stand.  Re-run preflight per Pass 1 step 5 if `src/` comments changed.
11. **Defer code-shape findings throughout.**  If reading the code to write a comment surfaces dead code / a lying name / a method that should split — *do not fix it here*.  File it as a `## Next` entry pointing at `/audit-library <name>` and move on.  Out-of-scope diffs riding along is the leading cause of revert traffic on audit work.

After Pass 2, invoke the `task-checkpoint` skill — it owns preflight, `plans/next-up.md` refresh, commit, and push.  Read the `git-commit` skill before committing for the heredoc mechanics.  Don't re-implement either here, and don't stop without invoking `task-checkpoint`.

## Walking MEDIUM and LOW findings

**MUST READ:** [`.github/skills/_shared/walk-pattern.md`](../_shared/walk-pattern.md) — the shared `AskUserQuestion` convention for surfacing MEDIUM and LOW findings across audit-* skills, including verifier-integration handling.  In audit-comments specifically: MEDIUM TRIMs (Pass 1) and MEDIUM REWRITEs + LOW `keep?` (Pass 2) walk; HIGH batches; DEFER findings (the `shape` tag) file as `## Next` pointers to `/audit-library`.

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
* `missing` — content a cold reader needs that the comment doesn't carry: the contract, the return value, the done condition, the error semantics, the named overrides.  Surfaced by Pass 2 step 6's fourth check (draft the ideal comment from code, compare to actual).  Show the addition inline.  MEDIUM by default since the call about what the reader needs is a judgment.  Distinct from `rewrite`: `missing` adds; `rewrite` replaces.
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
* **Don't surface MEDIUM or LOW findings as a free-text punch-list when walking is available.**  Per-finding `AskUserQuestion` turns each judgment into a click + the tool's "Other" free-text fallback.  Free-text mode is the fallback for very high finding counts (MEDIUM 15+) or when the user explicitly asks — never the default.
* **Don't expand scope mid-pass.**  A new stumble after the edit batch is a follow-up, not an extension of this pass.

## Done when

* Both Pass 1 (subtractive) and Pass 2 (whole-comment evaluation) ran across every file in the target, each producing its own punch-list and commit cycle.
* Every Pass 1 sweep's hit count matches its punch-list entry count (inventory gate — no implicit grouping, every site classified individually).
* Every HIGH finding has a commit or an explicit user skip.
* Every MEDIUM finding has a user answer — applied, deferred to `plans/next-up.md`, or dropped.
* Every `keep?` question has an answer; every `shape` finding is filed as a `## Next` entry pointing at `/audit-library`, not silently dropped.
* If `src/` comments in a shipped tree changed, `python scripts/run.py preflight --coverage-threshold 94` passes on the final state.
* Re-reading the changed comments cold (code unseen) orients the reader to what each thing does and why it exists, and each sentence reads the way you'd say it out loud to a colleague (concrete subject, real verb, dim 7), not as an abstract subject propped up by a weak verb.
