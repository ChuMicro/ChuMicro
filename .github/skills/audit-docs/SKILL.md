---
name: audit-docs
description: Audit a user-facing markdown doc (README, INSTALL, library guides) for cold-reader readability, AI-tic phrases, jargon and implementation-detail leaks, unverified claims, section ordering, and visual / link consistency.  Produces a punch-list, executes safe cleanups with sign-off.  Use when a README has accumulated drift, after a feature pass, or before a release-prep pass.
---

# Docs audit

Audit one human-curated markdown doc (`README.md`, `libraries/<name>/docs/guide.md`, `INSTALL.md`, or a similar shape) for the things that make a doc unreadable to a cold reader.  Output a prioritized punch-list.  After the user gives the go-ahead, execute the high-confidence batch.  Surface medium-confidence and low-confidence items as questions so the user can answer them instead of guessing.

> **About this skill's own prose.**  This SKILL.md lives in `.github/skills/`, which makes it internal documentation.  Internal docs are out of scope for the audit itself (see "Defer / out of scope" at the bottom), so this body cites `Decision NNNN`, `CHU0NN`, and `plans/` paths freely.  The tone rules in [`docs/contributing/agent-style-guide.md`](../../../docs/contributing/agent-style-guide.md) still apply, including the em-dash ban, the AI-tic phrase list, the per-noun `the X` forward-reference test, and the degraded-passage rewrite discipline.  The body below is written to demonstrate those rules in practice.

## Scope

User-facing markdown.  The common shapes are root and library READMEs, `libraries/<name>/docs/guide.md`, `workbench/<name>/docs/guide.md`, `INSTALL.md`, contributing guides, and hosted-docs source pages.

Out of scope for this skill:

* Internal docs (`plans/`, `AGENTS.md`, decision records under `plans/decisions/`, `.github/skills/<name>/SKILL.md`).  Different audience, different rules.  Use `audit-skill` for SKILL.md files.
* Auto-generated API reference docs.

Argument: a file path, defaulting to `README.md`.  Examples: `/audit-docs README.md`, `/audit-docs libraries/wifi/README.md`, `/audit-docs libraries/wifi/docs/guide.md`.

## Audit philosophy

Three readers land on the same paragraph wanting different things.  The skill's job is to find prose that loses any one of them.

* **Cold reader.**  Landed from a search result.  Does not know the project's vocabulary.  Does not have the workspace cloned.  Has roughly 60 seconds of patience.  Bails when a paragraph fails to tell them what this is or why they would want it.
* **Advanced reader.**  Already knows the field.  Bails when the doc reads like a tutorial for content they have seen 50 times.  *"First, install Python…"* burns them.
* **Beginner reader.**  Earlier on the curve than the cold reader.  Bails when the doc assumes context they do not have, names tools they have not seen, or skips the *"why would I want this?"*.

**Degraded passages get rewritten, not re-trimmed.**  The dimensions below are operationally subtractive (drop a tic word, cut a history note, shrink a ratio).  Run a subtractive pass enough times on the same paragraph and each pass removes a word while none asks *what should this say?*  The result is a README sentence as illegible as the worst code comment.  When a passage has rotted that far, discard it and rewrite from a fresh read of what the thing actually is and why a reader would want it (the cold-reader test).  Trimming the wreckage again only makes it shorter and no clearer.  This is the prescriptive counterpart to *"don't golf"* in the "What NOT to do" section: that rule stops over-cutting a good passage, while this one says what to do with an already-degraded one.

Most doc problems fall into the following families.

* **Jargon leak.**  Internal vocabulary used before defining it.
* **Implementation-detail leak.**  Internal metrics in user-facing prose, such as coverage percentages, specific test-board names, lint codes, or `plans/` references.
* **AI-tic filler and grammar tics.**  Words and phrases that read non-human or dilute meaning.  Includes the redundant definite articles flagged by the `the X` forward-reference test.
* **Unverified technical claims.**  Sweeping default-behavior claims that have not been bench-tested.
* **Historical rationale.**  `<!-- removed in 0.x -->`, *"previously this…"*, and dated migration notes that document what is not there.
* **Explanation-to-content ratio off.**  Paragraphs of rationale wrapping a 2-line `return a + b`.
* **Structural flow.**  Sections do not match the cold-reader question arc.
* **Visual inconsistency.**  Centered and left-aligned alignment bouncing, dead anchor links, misaligned comment columns in code blocks.
* **Stale examples.**  Code that does not actually run as written.

## Audit dimensions

Run each.  Capture findings as `<line>:<col>` (or section name) plus a one-line description plus a dimension tag (see "Output format" below).

### 1. Stumble-walk

Read top-to-bottom three times, one per reader (see philosophy above for who bails on what).  Flag every stumble.

**Cold-reader findings.**

* **Jargon used before defined.**  Words like *"Workspace"*, *"mono-repo"*, *"runner-shaped"*, *"the canonical X"* need a concrete naming on first use, or a definition.  *"The mono-repo itself is a ChuMicro workspace"* near the top loses the cold reader on two terms in one clause.
* **Acronyms used without expansion.**  *"MQTT"*, *"TLS"*, *"REPL"* are usually fine for the embedded audience.  *"UF2"*, *"esptool"*, *"mbedTLS"*, *"PIO"* benefit from a one-phrase gloss the first time.
* **Cross-references that do not help a cold read.**  *"see Decision 0047"*, *"per CHU009"*, *"`plans/workstreams/foo.md`"* are internal navigation.  Inline a one-line summary instead.
* **Assumed context.**  *"When you ran the X command above"* needs verification that X was actually shown above with the right name.
* **Implicit "we".**  *"we ship X"* in a public README assumes the reader is on the team.  Rephrase.

**Advanced-reader findings.**

* **Tutorial framing for known content.**  *"First, install Python…"* or *"Make sure you have a terminal open"* burns an experienced dev's patience.  Move beginner-onboarding into a clearly-marked section or its own doc.  Do not gate the differentiators behind it.
* **Filler before substance.**  Three sentences of stage-setting before the first concrete API name or capability.  An advanced reader needs the *what's different* claim in the first paragraph or they leave.
* **Redundant safety paragraphs.**  *"This requires Python 3.9 or later"* repeated in five different sections.  State once at the install point.

**Beginner-reader findings.**

* **Assumed tooling.**  *"Run `mip install …` from your REPL"* fails a beginner who doesn't know what `mip` is, what a REPL is in this context, or how to access either.  Either define inline or link to a single onramp doc.
* **Audience-split mentions of mono-repo-only tooling.**  Library and workbench READMEs serve two audiences: PyPI / circup / mip consumers who just want to use the package, and mono-repo contributors who have the workspace cloned.  Mentions like *"register a board with `chumicro-workspace add-device`"* are useful to the second audience but confusing to the first.  Flag every reference to mono-repo-only CLIs (`chumicro-workspace`, `python scripts/run.py`, `chumicro-deploy`) in a published library or workbench README and ask: *"can a PyPI installer act on this?  If not, prefix with 'In the [mono-repo](url)…' or move to the dev-contributing section."*
* **Pitch missing the "why".**  A beginner reads the install instructions, runs the example, and asks *"what would I use this for?"*.  The differentiators section needs at least one concrete production scenario, not just feature bullets.
* **Feature bullets that lead with implementation instead of use.**  *"Constructor-injected duck-typed I/O dependencies"* fails the consumer reader.  Name what the user can DO instead, such as *"Bring your own socket, your own clock"*.  Avoid type-system jargon (`duck-typed`, `Protocol`, `structural typing`), inline method-name lists, *"valid producer"*-style abstractions, and test-fake framing.  Lead with concrete library class names, stdlib alternatives, and production scenarios.  Acknowledge defaults before swap-outs.  See [style-guide § Documentation tone](../../../docs/contributing/style-guide.md#documentation-tone).

### 2. Vocabulary and grammar tics

The phrase bans, the standing regex, and the per-word handling all live in [`docs/contributing/agent-style-guide.md`](../../../docs/contributing/agent-style-guide.md).  One source, every audit skill cites it.  Do not carry a private copy in this skill.

**Run the regex from [§ Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex)** over the target file.  Treat hits per [§ Phrase bans](../../../docs/contributing/agent-style-guide.md#phrase-bans):

* Hard-ban hits (`canonical`, `idempotent`, the empty adjectives) almost always need a rewrite.
* Soft hits (`under the hood`, definite-article tics) are case-by-case.

**Read for the grammar tics that no regex catches.**  Definite-article shapes (forward-reference test, brand names, stacked articles, "X is the one that Y", "The same X" at sentence-start) and the abstract-opener-em-dash-restate pattern.  See agent-style-guide.md § Phrase bans for the worked examples.

**When the user surfaces a new flagged word during the audit**, add it to the right phrase-ban subsection in agent-style-guide.md and append it to the regex there.  Other audit skills pick it up automatically.

### 3. Implementation-detail leakage

User-facing docs should not expose internal metrics or development jargon.

* **Coverage percentages.**  *"96 % workspace coverage"* is for contributors, not users.  If the doc wants to assert testedness, list what is tested, not the percent.
* **Lint codes in prose.**  `CHU009 / CHU010` is workspace-internal.  Name the rule's intent.
* **`plans/` and `Decision NNNN` references in publishable docs.**  These are internal navigation aids.  Inline a one-line summary.
* **Specific test-board names.**  *"WeMos / Lolin S2 plus Pi Pico W in CP and MP"* is bench setup.  *"Tested on real CircuitPython and MicroPython boards before each release"* carries the same trust without naming hardware.
* **File:line refs.**  Fine in code comments and commit messages.  Jarring in user docs.
* **Internal `run.py` task names without context.**  *"`python scripts/run.py preflight`"* is fine in a "Running tests" section.  *"run preflight before committing"* in passing prose, without saying what preflight does, is jargon.
* **Cross-package redirects in publishable docs.**  *"This package doesn't do X.  Use `other-package` for X instead"*, or *"For X, lives one level up in Y"*, leaks mono-repo awareness into a leaf package's PyPI-facing surface.  Relative paths like `../workspace/` only resolve in the mono-repo docs site, and break PyPI README rendering.  State what THIS package does.  Do not apologize for non-features by naming siblings.  See [style-guide § Documentation tone](../../../docs/contributing/style-guide.md#documentation-tone).

### 4. Verify load-bearing technical claims

Claims a reader might rely on need verification before they ship.  Stratify by stakes.

**Bench-test (deploy a probe to a real board)** when the claim is behavioral, cross-runtime, or security-significant.

* **Cross-runtime claims.**  Does it work the same on CircuitPython, MicroPython, and CPython?  Runtime defaults often differ silently.  Concrete case from earlier audit work: *"built-in trust store validates against major public CAs"*.  True on CP (firmware-bundled `x509-crt-bundle`).  False on MP (`ssl.wrap_socket` with no context skips verification entirely).  Caught by deploying an `expired.badssl.com` probe to all four boards.
* **Default-behavior claims.**  *"X validates by default"*, *"Y auto-reconnects"*.  Verify with a deliberate failure case (expired cert, broker offline, and similar).
* **Performance claims.**  *"fast"*, *"in seconds"*, or specific numbers.  Either measure or remove.

**Source-read verify** (grep or Read tool, no hardware) when the claim is API-surface or pure-Python.

* **API-shape claims.**  *"`Heartbeat.period_ms` is read-only"*, *"`X.from_config` accepts empty dict"*.  Verify by reading the class source.
* **Compatibility claims.**  *"works on every board with ≥ 256 KB / 4 MB"*.  At minimum, list the families actually tested.
* **Detection-table claims.**  *"`supervisor.ticks_ms` on CircuitPython 7+; `time.ticks_ms` on MicroPython"*.  Verify by reading the detection logic.

If a claim cannot be verified, soften to a capability mention (*"supports TLS"* instead of *"validates TLS by default"*) or remove.  If the gap is structural and worth fixing in code, file it as a research item under `plans/next-up.md` → `## Investigations` and roll back the claim in the doc.

### 5. Structural flow

Three different cold-reader arcs depending on what the doc is.

**Project / mono-repo README** (multi-library or framework-scale):

1. **What is this?**  Hero (logo, title, tagline, nav) plus intro paragraphs.
2. **What is special about it?**  Differentiators bullet block, often before code so the reader knows whether to keep reading.
3. **What does the code look like?**  Quickstart code samples.
4. **How do I install it?**  Install section, placed early so readers can try the code they just saw.
5. **What is available?**  Library and API inventory (table).
6. **How do I run / deploy / test it?**  Workflow sections.
7. **What else comes with it?**  Tools, related packages, integrations.
8. **For real project work.**  Project-template or scaffold pointer.  Deferred, since the reader needs context from above first.
9. **Reference.**  Documentation links and repo layout.
10. **Contributing.**
11. **License.**

**Single-library / package README** (one publishable package):

A simpler arc.  The tagline carries the differentiator, so a separate "What makes X different" block is usually not needed.

1. **What is this?**  Hero (title, short tagline, one or two sentences of description).
2. **How do I install it?**  Install section.  This is the first thing a PyPI, circup, or mip reader looks for.
3. **What does it look like?**  Quick example that runs as-is on the relevant runtimes.
4. **What is available?**  API inventory (Tick functions, Heartbeat, Testing tables, or whatever the public surface is).
5. **Related libraries.**  *"If you need X, also see Y"* pointers.
6. **Reference.**  Platform support tables, runnable-examples table, links to hosted docs and to PyPI or bundle.
7. **Developing this library.**  Contributing notes.  Audience-split: PyPI consumers can ignore this, mono-repo contributors use it.
8. **License.**  At minimum a one-line footer linking to the parent repo's LICENSE so PyPI consumers reading the rendered README see the license.

**Library or workbench `docs/guide.md`** (hosted-docs source page):

A different audience than the README.  Readers came in via the docs site and are already past the *"should I install this?"* question.  Lead with the conceptual model, not the install instructions.

1. **What is the mental model?**  One paragraph that names the moving parts and how they fit.
2. **How do I use it?**  Task-shaped walkthroughs (deploy, configure, integrate).
3. **Reference.**  Public API surface, configuration knobs, error classes.
4. **Related.**  Adjacent libraries, upstream docs.
5. **Troubleshooting / FAQ** if the question volume warrants it.

Common reorderings worth checking.

* **Install too low.**  If it sits after Libraries or Tools, readers cannot try the code shown earlier.  Move Install right after the first code samples.
* **Pitch too low.**  If differentiators come after the inventory, readers may leave before being convinced.  Consider moving above code samples.
* **Project-template too early.**  Readers have not seen what real use looks like yet.  Defer until after libraries and workflow sections.
* **Status section mixing two concerns.**  *"## Status & contributing"* with one paragraph about development status and another about how to contribute usually wants to be split, or the status content removed entirely if it just reads as a hedge.
* **Library README missing License footer.**  The rendered README on PyPI is often the only license artefact a user sees from the package.  At minimum a one-line `## License — [MIT](https://github.com/.../LICENSE)` pointer.
* **Library README's contributing section assumes mono-repo context.**  Mentioning `chumicro-workspace add-device` without telling the PyPI reader they need the mono-repo cloned creates a context cliff.  Prefix the section or split the audience.

### 6. Visual layout, markup, and hero/nav

**Hero / nav block.**

* **Title.**  Must say what the project is.  *"# Project name"* alone is not enough.
* **Tagline.**  Answers *"what is this for?"* in one phrase.  Pair it with a *"for whom?"* phrase if the audience is not obvious.  *"Cross-runtime hardware utilities"* names the what.  *"for CircuitPython, MicroPython, and Python"* names the for-whom.  Both needed.
* **Nav block.**  Usually includes Install and Contributing.  Workspace-template and external-repo links pay off when they exist.
* **`<big>` for nav.**  For nav blocks with many entries, `<big>` (GitHub-rendered) helps them feel like navigation rather than running prose.

**Centered and left-aligned bouncing.**  A centered hero, then a wall of left-aligned intro text, then a centered nav block, then a horizontal rule creates visual whiplash.  Keep the hero block together (logo, title, tagline, nav), insert the `---` ruler, then start left-aligned body content.

**Comment column alignment in code blocks.**  When a block has trailing `# comment` annotations across multiple lines, all `#` symbols should land at the same column.  Verify with:

```
awk 'NR>=N1 && NR<=N2 {n=index($0,"#"); printf "L%d col=%d\n",NR,n}' <file>
```

**Dead anchor links.**  Renaming a section without updating links breaks navigation silently.  After every section rename, verify all `(#...)` references resolve:

```
grep -nE '\(#[a-z0-9-]+\)' <file>
```

GitHub anchor slug rules: lowercase, spaces become hyphens, em-dashes and parentheses drop.  Test on github.com if in doubt.

**Mixed conventions.**  `python` vs `python3` invocations, `http://` vs `https://` URLs that should match the published examples, two different ways of writing the same brand name.  Pick one per doc.

**Markup-style consistency.**

* **Backticks.**  Used for identifiers, file paths, CLI invocations, and literal config keys.
* **Italic.**  Used for emphasis and the first use of a term being defined.
* **Bold.**  Used sparingly, for the load-bearing claim of a paragraph.  If three things in one paragraph are bold, none are.
* **Heading depth.**  A README starts at H1 (the title) and rarely needs deeper than H3.  `docs/guide.md` usually starts at H1 too (the page title).  If the docs-site renderer injects a title, start at H2.
* **Paragraph length.**  When a paragraph runs past four sentences, ask whether it is actually two paragraphs.

**Render before flagging layout.**  Some intent is only visible rendered (centered alignment, `<big>`, table widths, image scaling).  If the raw markdown does not make the intent clear, push to a draft branch and view on github.com before flagging.

### 7. Stale examples

Code examples should actually run.

* **Pseudocode masquerading as real code.**  If an example shows the SHAPE but skips real imports or uses a wrong attribute name (such as `wifi.radio` when the API is `wifi.adapter.radio`), flag it.  Verify against the actual library source.
* **Examples that import libraries the README has not introduced.**  Install instructions must cover everything the example imports.
* **Hardcoded placeholders that look real.**  `your-network`, `your-password`, `broker.example.com` are clearly placeholders.  `10.0.0.5` looks like a real local IP and confuses readers.
* **URLs that imply guarantees.**  `https://example.com` in a code example, after the surrounding prose has explicitly disclaimed TLS verification claims, is an inconsistency.  Switch to `http://` or restore the claim with verification.
* **Examples shown but never tested on hardware.**  If the README walks through `chumicro-workspace deploy-example wifi connect_to_ap` and similar, those should actually still deploy and run.  Confirm with the published example file's docstring plus a spot deploy.

### 8. Inline comments and code-comment density

Trailing `# comment` annotations should narrate behavior, not label operations.  They should also pull their weight, since example blocks ship as flash bytes when copy-pasted.

Scope note.  This dimension covers comments *in markdown example blocks*.  Comments and docstrings in `src/` (the actual library or workbench code) belong to `/audit-comments`.  Route those there.  Do not fix them from a docs pass.

* **Labels.**  *"# start a request"* is a label.  Flag.
* **Narration.**  *"# every 30 s, queue a fetch for example.com"* tells the reader something they could not infer.  Keep.
* **Runtime / runner relationship narration.**  For runner-shaped code, the comment should name the runner's call relationship.  Examples: *"# Runner calls this every 30 s — if no fetch is in flight, queue a new one"*, *"# Runner asks this every tick — True once the response is ready"*.
* **Density.**  An example block with a comment on every line usually has labels masquerading as narration.  Three comments on a 20-line block is a healthy rate when each names a *why*.
* **Per-change audit-style comments do not belong in examples.**  *"# bench-validated -25 % allocation"* or *"# skips the bytes() copy"* are commit-message material, not example code.  See AGENTS.md → Code comments for the broader rule.  `/audit-library` and `/audit-embedded` carry the audit-pass operational detail.

### 9. Historical rationale

History belongs in `git log`, not in the artefact.

* **"Previously this…" paragraphs.**  Flag.  The reader does not need to know what the API used to do.  They need to know what it does now.
* **`<!-- removed in 0.x -->` HTML comments.**  Flag.  If a section is removed, remove the marker too.
* **Dated migration notes.**  *"As of 2025-11-02, the X parameter…"* loses the date.  If the migration is still ongoing, name what is still pending instead.  If it is complete, the note should not be in user docs.
* **Retrospective rationale paragraphs.**  *"This was originally implemented with Y, but we changed to Z because…"*.  The *why* of the current code can stay (one sentence at most).  The history of how it got there should not.
* **`## Update (YYYY-MM-DD)` sections.**  Drop.  Rewrite the affected prose in place.  Let `git log` carry the timeline.

This rule applies to user-facing docs.  Internal docs are exempt: ADRs under `plans/decisions/` (recording the decision is their job), and SKILL.md bodies under `.github/skills/` (including this one).

### 10. Explanation-to-content ratio

If the prose around a thing is much longer than the thing itself, ask whether the prose needs to exist.

* **Two-line function with a five-paragraph docstring.**  Either the function is doing more than it looks like (rewrite it to be clearer), or the docstring is overgrown (cut to one line).
* **Trivial example with elaborate framing.**  *"In this section we will explore how to import a library…"* followed by a single `import` line.  Drop the framing.  Let the code speak.
* **Section headers that promise more than the section delivers.**  *"## Advanced configuration patterns"* containing one paragraph and one code block does not earn the *"Advanced"* qualifier.  Rename or fold up.
* **Same idea explained three times.**  Often a sign that the first explanation was not clear enough.  Fix the first.  Drop the other two.

Flash cost matters here too.  Every byte in `docs/guide.md` that gets mirrored into example payloads or shipped with the package costs.

## Procedure

Walk these passes in order.  Each dimension's body has the specific check (regex, grep, awk) inline.

1. **Stumble-walk** (dim 1).  Three reads end-to-end.  Take notes as you go for dims 3, 7, and 8 since they surface during the read.
2. **AI-tic and grammar grep** (dim 2).  Run the standing regex from [`agent-style-guide.md` § Standing AI-tic regex](../../../docs/contributing/agent-style-guide.md#standing-ai-tic-regex).  Hard-ban hits almost always need rewriting.  Soft hits are case-by-case.
3. **Structure map** (dim 5).  `grep -nE '^## ' <file>`, then compare against the question arc for the doc's type.
4. **Visual passes** (dim 6).  Anchor check with `grep -nE '\(#[a-z0-9-]+\)' <file>`, plus the comment-column awk on any block that has trailing `#` annotations.
5. **Load-bearing claims** (dim 4).  List every claim a reader might rely on for security, correctness, or compatibility.  For each, bench-verify or soften.
6. **History and trivia sweep** (dims 9 and 10).  Grep `previously`, `used to`, `as of `, `<!-- removed`, `## Update`.  Read for explanation-to-content ratio on long sections.

### Punch-list

Group findings by confidence.  Tag by dimension (see Output format).

### Execute the HIGH-confidence batch

After the user gives the go-ahead, execute the HIGH-confidence fixes as a single edit pass.  MEDIUM items wait for user confirmation.  LOW items wait for user answers.

### After-action sweep and exit condition

Re-run the dim 2 grep and the dim 6 anchor check on the changed file.  The audit is done when:

* AI-tic grep returns no unjustified hits (legitimate technical-term uses are fine).
* Every accepted punch-list item has a corresponding edit, or a deferred entry in `plans/next-up.md` if the fix is bigger than the audit.
* The three-reader reread (cold, advanced, beginner) does not surface a new stumble.

If the post-audit reread still surfaces stumbles, that is a separate pass.  File as a follow-up rather than expanding the current one.

## Output format

When presenting the punch-list, structure it like:

```
Docs audit: <file>
==================

HIGH-CONFIDENCE (safe to fix):

  ai-tic       L<n> — <one-line description>
  jargon       L<n> — <one-line description>
  impl-leak    L<n> — <one-line description>
  history      L<n> — <one-line description>
  comment      L<n> — <one-line description>
  stale        L<n> — <one-line description>
  ...

MEDIUM-CONFIDENCE (sign-off needed):

  rewrite      §<section> — <passage rotted by prior trim passes;
                             proposed replacement text shown inline>
  structure    §<section> — <restructure proposal + rationale>
  claim        L<n> — <claim to verify or soften>
  trivia       §<section> — <explanation/content ratio off>
  ...

LOW-CONFIDENCE (questions for the user):

  visual       §<section> — <layout / markup question>
  ...
```

**Worked example** (synthetic; illustrative shape, not a real file):

```
Docs audit: libraries/widget/README.md
======================================

HIGH-CONFIDENCE (safe to fix):

  ai-tic       L14 — "comprehensive API" — drop or list what's covered
  jargon       L9  — "runner-shaped" used before defining the term
  impl-leak    L43 — "96 % coverage" in user-facing prose
  history      L27 — "Previously this used X..." — git log carries this
  comment      L52 — example block's # comments label ops, don't narrate
  stale        L68 — example imports chumicro_thing not in install section

MEDIUM-CONFIDENCE (sign-off needed):

  structure    §How it works — sits above Install; readers can't try the
                               code shown earlier without seeing Install
  claim        L18 — "auto-reconnects on disconnect" — bench-verify or
                     soften to "supports reconnect via X()"
  trivia       §Reference — 4-paragraph history wraps a 3-line table

LOW-CONFIDENCE (questions for the user):

  visual       hero — title-only nav, missing Install / Contributing links;
                      add or keep terse?
```

Tag taxonomy.

* `jargon`.  Internal vocabulary used before defining (dim 1).
* `ai-tic`.  Vocabulary or grammar tic from dim 2.
* `impl-leak`.  Internal metric, lint code, or `plans/` reference in user-facing prose (dim 3).
* `claim`.  Load-bearing technical claim, verify or soften (dim 4).
* `structure`.  Section ordering, splitting, renaming (dim 5).
* `visual`.  Layout, markup, hero/nav, anchor (dim 6).
* `stale`.  Example does not run as written (dim 7).
* `comment`.  Inline-comment label vs narration (dim 8).
* `history`.  Historical rationale that should be in `git log` (dim 9).
* `trivia`.  Explanation-to-content ratio off (dim 10).
* `rewrite`.  Passage degraded by prior subtractive passes.  Discard and rebuild from a fresh read (see Audit philosophy).  Replacement text shown inline.  MEDIUM by default, since the rebuilt prose is a judgment call needing sign-off.

## Surface questions instead of guessing

When the same patterns recur across audits, ask rather than acting.

| Symptom | Question to surface |
|---|---|
| Section name too narrow for what it now covers | *"This section started as 'Hello, blink' but now spans LED + WiFi + HTTP + MQTT.  Want me to rename it?"* |
| Section sits at an awkward position | *"This section is at position N; given the cold-reader arc, M might read better.  Want me to move it?"* |
| Implementation detail in user-facing prose | *"`<thing>` looks like internal metric / jargon to me — is it something users of the library should care about?  Otherwise I'll drop it."* |
| Sweeping technical claim, unverified | *"This claim says X.  Want me to bench-verify on the boards we have plugged in, or soften to a capability mention?"* |
| Visual layout / styling | *"The hero + body have inconsistent alignment.  Want me to wrap nav in `<big>` / move the ruler / etc?"* |
| Example URL or host looks ambiguous | *"`<URL>` — is this a real working example or a placeholder?  Should the example use `http://example.com` to avoid implying TLS / endpoint guarantees?"* |
| Multi-runtime code: unify vs split | *"Three separate variants vs one unified block with a `sys.implementation.name` branch — which reads cleaner for the section's purpose?"* |
| Two unrelated concerns in one section | *"`## Status & contributing` has a status paragraph and a contributing paragraph — they target different audiences.  Split or drop the status part?"* |
| Inline comments not pulling weight | *"The trailing `# comment`s here label operations rather than narrating.  Want me to rewrite them to describe what each tick does?"* |
| Historical rationale | *"This paragraph explains what the API used to do — `git log` covers that.  Drop it?"* |
| Section much longer than what it covers | *"This 4-paragraph rationale wraps a 2-line example.  Cut the framing or expand the example?"* |

## What NOT to do

**Content don'ts** (what not to write into the punch-list).

* **Don't golf for word count.**  Sometimes longer prose is clearer.  User framing: *"you don't have to be so compact, these one-liners don't say much."*  Add words when they help comprehension.
* **Don't re-trim a degraded passage.  Rewrite it.**  If a paragraph is already rotted from prior subtractive passes (illegible, says nothing, survived three audits a word lighter each time), removing another word is the wrong fix.  Discard it and rewrite from a fresh read of what the thing is.  See "Audit philosophy" above for the rule.  A `rewrite` finding shows the proposed replacement text inline, same as `/audit-comments`.
* **Don't strip every "the".**  *"the LED"*, *"the loop"*, *"the request"* are specific singular nouns.  Dropping the article reads wrong.  Only flag the genuinely-redundant ones.  Apply the per-noun three-way test from [`feedback_the_forward_reference`](../../../../.claude/projects/-Users-chuxor-circuitpython-chumicro/memory/feedback_the_forward_reference.md).
* **Don't restructure based on taste alone.**  The three-reader walk gives an objective lens.  *"I'd write it differently"* is not a reason to move things.

**Verification don'ts** (what not to skip before flagging).

* **Don't ship sweeping claims without bench verification.**  Even features that should work cross-runtime sometimes do not.  Verify or soften before letting a claim land in a finding.
* **Don't trust raw-markdown reads for layout intent.**  Some visual decisions are only legible rendered.  Push a draft and view on github.com when in doubt (see dim 6).

**Process don'ts** (how not to act on the punch-list).

* **Don't auto-commit.**  Docs changes need user review.  Surface as a punch-list first.  Execute the HIGH-confidence batch only after explicit go-ahead.
* **Don't reinvent the AI-tic list per pass.**  [`agent-style-guide.md`](../../../docs/contributing/agent-style-guide.md) is the source of truth for the phrase bans, the regex, and per-word handling.  When the user surfaces a new flagged word, add it to the right phrase-ban subsection there and append it to the regex.  Do not maintain a private copy in this skill.
* **Don't expand the audit scope mid-pass.**  If the post-audit reread surfaces a new stumble, file it as a follow-up rather than folding it into the current audit's edit batch.

## Defer / out of scope

* **API reference docs.**  Autogenerated from docstrings.  This skill targets human-curated prose.
* **Internal docs** (`plans/`, `AGENTS.md`, `.github/skills/<name>/SKILL.md`, decision records under `plans/decisions/`).  Different audience, different rules.  Use `audit-skill` for SKILL.md files.  Use `audit-publishable-isolation` for leak detection between internal and shipped trees.
* **Tone calibration** (friendly vs formal, second-person vs third-person).  Match the project's existing tone.  Do not impose a new one.
* **Long-form rewrites.**  If more than roughly 30 % of the doc needs reshaping, this is a rewrite, not an audit.  Surface the scope and let the user decide whether to escalate.
