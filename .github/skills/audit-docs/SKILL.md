---
name: audit-docs
description: Audit a user-facing markdown doc (README, INSTALL, library guides) for cold-reader readability, AI-tic phrases, jargon and implementation-detail leaks, unverified claims, section ordering, and visual / link consistency.  Produces a punch-list, executes safe cleanups with sign-off.  Use when a README has accumulated drift, after a feature pass, or before a release-prep pass.
---

# Docs audit

Audit one human-curated markdown doc (`README.md`, `libraries/<name>/docs/guide.md`, `INSTALL.md`, etc.) for the things that make a doc unreadable for a cold reader.  Output a prioritized punch-list, then execute the high-confidence batch with the user's go-ahead.  Surface medium / low confidence items as questions so the user can answer them rather than guessing.

> **About this skill's own prose.**  The SKILL.md you're reading is internal docs (`.github/skills/`).  Internal docs are explicitly out of scope (see "Defer / out of scope" at the bottom) — that's why this body cites `Decision NNNN`, `CHU0NN`, and `plans/` paths freely.  The bans on those constructs apply to *user-facing* docs, not to this skill's body.

## Scope

User-facing markdown — primarily READMEs, but also `libraries/<name>/docs/guide.md`, `workbench/<name>/docs/guide.md`, `INSTALL.md`, contributing guides, hosted-docs source pages.  Out of scope: internal docs (`plans/`, `AGENTS.md`, decision records under `plans/decisions/`, `.github/skills/<name>/SKILL.md`) — different audience, different rules.  Out of scope: auto-generated API reference docs.

Argument: file path (default `README.md`).  Example: `/audit-docs README.md`, `/audit-docs libraries/wifi/README.md`, `/audit-docs libraries/wifi/docs/guide.md`.

## Audit philosophy

Three readers land on the same paragraph and want different things.  The skill's job is to find prose that loses any one of them:

* **Cold reader** — landed from a search result, doesn't know the project's vocabulary, doesn't have the workspace cloned, has ~60 seconds of patience.  Bails when a paragraph fails to tell them what this is or why they'd want it.
* **Advanced reader** — already knows the field.  Bails when the doc reads like a tutorial for content they've seen 50 times.  *"First, install Python…"* burns them.
* **Beginner reader** — earlier on the curve than the cold reader.  Bails when the doc assumes context they don't have, names tools they haven't seen, or skips the *"why would I want this?"*.

Most doc problems fall into:

* **Jargon leak** — internal vocabulary used before defining
* **Implementation-detail leak** — internal metrics in user-facing prose (coverage %, specific test-board names, lint codes, `plans/` references)
* **AI-tic filler / grammar tics** — words/phrases that read non-human or dilute meaning; redundant definite articles
* **Unverified technical claims** — sweeping default-behavior claims that haven't been bench-tested
* **Historical rationale** — `<!-- removed in 0.x -->`, *"previously this…"*, dated migration notes that document what isn't there
* **Explanation-to-content ratio** — paragraphs of rationale wrapping a 2-line `return a + b`
* **Structural flow** — sections don't match the cold-reader question arc
* **Visual inconsistency** — centered/left-aligned bouncing, dead anchor links, misaligned comment columns in code blocks
* **Stale examples** — code that doesn't actually run as written

## Audit dimensions

Run each.  Capture findings as `<line>:<col>` (or section name) + one-line description + dimension tag (see "Output format" below).

### 1. Stumble-walk

Read top-to-bottom three times, one per reader (see philosophy above for who bails on what).  Flag every stumble.

**Cold-reader findings.**
* **Jargon used before defined.**  *"Workspace"*, *"mono-repo"*, *"runner-shaped"*, *"the canonical X"* — name the thing concretely on first use or define it.  *"The mono-repo itself is a ChuMicro workspace"* near the top loses the cold reader on two terms in one clause.
* **Acronyms used without expansion.**  *"MQTT"* / *"TLS"* / *"REPL"* are usually fine for the embedded audience; *"UF2"*, *"esptool"*, *"mbedTLS"*, *"PIO"* benefit from a one-phrase gloss the first time.
* **Cross-references that don't help a cold read.**  *"see Decision 0047"*, *"per CHU009"*, *"`plans/workstreams/foo.md`"* — internal navigation.  Inline a one-line summary instead.
* **Assumed context.**  *"When you ran the X command above"* — confirm X was actually shown above with the right name.
* **Implicit "we"** — *"we ship X"* in a public README assumes the reader is on the team.  Rephrase.

**Advanced-reader findings.**
* **Tutorial framing for known content.**  *"First, install Python…"*, *"Make sure you have a terminal open"* — burns an experienced dev's patience.  Move beginner-onboarding into a clearly-marked section or its own doc; don't gate the differentiators behind it.
* **Filler before substance.**  Three sentences of stage-setting before the first concrete API name or capability.  An advanced reader needs the *what's different* claim in the first paragraph or they leave.
* **Redundant safety paragraphs.**  *"This requires Python 3.9 or later"* in five different sections.  State once at the install point.

**Beginner-reader findings.**
* **Assumed tooling.**  *"Run `mip install …` from your REPL"* — beginner doesn't know what `mip` is, what a REPL is in this context, or how to access either.  Either define inline or link to a single onramp doc.
* **Audience-split mentions of mono-repo-only tooling.**  Library and workbench READMEs serve **two audiences**: PyPI / circup / mip consumers (just want to use the package) and mono-repo contributors (have the workspace cloned).  Mentions like *"register a board with `chumicro-workspace add-device`"* are useful to the second but confusing to the first.  Flag every reference to mono-repo-only CLIs (`chumicro-workspace`, `python scripts/run.py`, `chumicro-deploy`) in a published library / workbench README and ask: *"can a PyPI installer act on this?  If not, prefix with 'In the [mono-repo](url)…' or move to the dev-contributing section."*
* **Pitch missing the "why".**  Beginner reads the install instructions, runs the example, and asks *"what would I use this for?"*.  The differentiators section needs at least one concrete production scenario, not just feature bullets.

### 2. Vocabulary + grammar tics

**Standing regex** (this skill is the source-of-truth; sibling memories should be kept in sync with it):

```
grep -niE 'canonical|idempotent|comprehensive|seamless|robust|cutting-edge|best-in-class|leverage|intuitive|elegant|streamlined|battle-tested|first-class|one-stop|out of the box|worth noting|dive into|let.?s explore|effortless|painless|empowers|harness|unleash|by construction|under the hood|got you covered|simply put|in essence|magic|powerful' <file>
```

Per-word handling:

* **Drop outright:** `comprehensive`, `robust`, `seamless`, `cutting-edge`, `best-in-class`, `first-class`, `one-stop`, `out of the box`, `effortless`, `painless`.  Demonstrate the property concretely if it's real — list what's covered instead of saying *"comprehensive"*; name the commands that make a workflow *"first-class"*.
* **`leverage` → `use`.**
* **canonical** — flag every occurrence (user-flagged).  Drop or replace.  Keep only the real-term uses (canonical encoding / form / path / URL).  *"Canonical starter"* → *"Starter project"*.
* **idempotent** — flag every occurrence (user-flagged).  Often filler.  When the property is real (a retried operation reaches the same end state), demonstrate concretely instead of asserting abstractly.
* **harness** — flag.  Often filler (*"harnesses X to do Y"*).  Drop or replace with a plain verb.
* **under the hood** — rephrase concretely.  *"These tools execute the deploy"* beats *"this is what was happening under the hood"*.
* **by construction** — math jargon in casual prose.  Drop.  *"One codebase, three runtimes"* beats *"cross-runtime by construction"*.
* **worth noting / it should be noted / note that** as sentence openers — just say the thing.
* **let's dive into / let's explore / in this section we will** — start with the content.
* **`CHU0NN` codes in prose** — name the rule's intent (*"silent test skips"*) not the workspace-internal code.

**Grammar tics** (no regex — read for them):

* **"the" before brand names** — drop.  *"the Pi Pico W"* → *"Pi Pico W"*.  *"the ESP32"* depends on whether you're referring to a specific chip vs the family; usually drop.
* **"X is the one that Y"** — usually wordy.  *"`run.py` is the one that enforces coverage"* → *"`run.py` enforces coverage"*.
* **Stacked definite articles** — *"the X of the Y of the Z"* often has one too many.
* **"The same X"** at sentence-start — sometimes *"Same X"* reads cleaner; sometimes not.  Judgment call.

Keep *"the"* for genuinely-specific singular nouns: *"the LED"*, *"the loop"*, *"the request"* — these refer to a specific instance in the example and dropping the article reads wrong.

### 3. Implementation-detail leakage

User-facing docs should not expose internal metrics or development jargon.

* **Coverage percentages** — *"96 % workspace coverage"* is for contributors, not users.  If you want to assert testedness, list what's tested, not the percent.
* **Lint codes in prose** — `CHU009 / CHU010` is workspace-internal.  Name the rule's intent.
* **`plans/` / `Decision NNNN` references in publishable docs** — internal navigation aids.  Inline a one-line summary.
* **Specific test-board names** — *"WeMos / Lolin S2 + Pi Pico W in CP and MP"* is bench setup.  *"Tested on real CircuitPython and MicroPython boards before each release"* carries the same trust without naming hardware.
* **File:line refs** — fine in code comments / commit messages, jarring in user docs.
* **Internal run.py task names without context** — *"`python scripts/run.py preflight`"* is fine in a "Running tests" section; *"run preflight before committing"* in passing prose without saying what preflight does is jargon.

### 4. Verify load-bearing technical claims

Claims a reader might rely on need verification before they ship.  Stratify by stakes:

**Bench-test (deploy a probe to a real board)** when the claim is *behavioral / cross-runtime / security-significant*:
* **Cross-runtime claims** — does it work the same on CircuitPython, MicroPython, and CPython?  Runtime defaults often differ silently.  Concrete case from earlier audit work: *"built-in trust store validates against major public CAs"* — true on CP (firmware-bundled `x509-crt-bundle`), **false on MP** (`ssl.wrap_socket` with no context skips verification entirely).  Caught by deploying an `expired.badssl.com` probe to all four boards.
* **Default-behavior claims** — *"X validates by default"*, *"Y auto-reconnects"*.  Verify with a deliberate failure case (expired cert, broker offline, etc.).
* **Performance claims** — *"fast"*, *"in seconds"*, specific numbers.  Either measure or remove.

**Source-read verify** (grep / Read tool, no hardware) when the claim is *API-surface / pure-Python*:
* **API-shape claims** — *"`Heartbeat.period_ms` is read-only"*, *"`X.from_config` accepts empty dict"*.  Verify by reading the class source.
* **Compatibility claims** — *"works on every board with ≥ 256 KB / 4 MB"* — at minimum, list the families actually tested.
* **Detection-table claims** — *"`supervisor.ticks_ms` on CircuitPython 7+; `time.ticks_ms` on MicroPython"* — verify by reading the detection logic.

If a claim can't be verified, soften to a capability mention (*"supports TLS"* instead of *"validates TLS by default"*) or remove.  If the gap is structural and worth fixing in code, file it as a research item under `plans/next-up.md` → `## Investigations` and roll back the claim in the doc.

### 5. Structural flow

Three different cold-reader arcs depending on what the doc is.

**Project / mono-repo README** (multi-library or framework-scale):

1. **What is this?** — hero (logo + title + tagline + nav) + intro paragraphs
2. **What's special about it?** — differentiators bullet block (often before code so the reader knows whether to keep reading)
3. **What does the code look like?** — quickstart code samples
4. **How do I install it?** — install section, **early** (so readers can try the code they just saw)
5. **What's available?** — library / API inventory (table)
6. **How do I run / deploy / test it?** — workflow sections
7. **What else comes with it?** — tools, related packages, integrations
8. **For real project work** — project-template / scaffold pointer (deferred — reader needs context from above first)
9. **Reference** — documentation links, repo layout
10. **Contributing**
11. **License**

**Single-library / package README** (one publishable package):

Simpler arc — the tagline carries the differentiator, so no separate "What makes X different" block is usually needed.

1. **What is this?** — hero (title + short tagline + 1–2 sentence description)
2. **How do I install it?** — install section (the first thing a PyPI / circup / mip reader looks for)
3. **What does it look like?** — quick example, runs as-is on the relevant runtimes
4. **What's available?** — API inventory (Tick functions / Heartbeat / Testing tables, or whatever the public surface is)
5. **Related libraries** — *"if you need X, also see Y"* pointers
6. **Reference** — platform support tables, runnable-examples table, links to hosted docs + PyPI / bundle
7. **Developing this library** — contributing notes (audience-split: PyPI consumers can ignore this; mono-repo contributors use it)
8. **License** — at minimum a one-line footer linking to the parent repo's LICENSE so PyPI consumers reading the rendered README see the license

**Library or workbench `docs/guide.md`** (hosted-docs source page):

Different audience than the README — readers came in via the docs site, already past the *"should I install this?"* question.  Lead with the conceptual model, not the install instructions.

1. **What's the mental model?** — the one paragraph that names the moving parts and how they fit
2. **How do I use it?** — task-shaped walkthroughs (deploy, configure, integrate)
3. **Reference** — public API surface, configuration knobs, error classes
4. **Related** — adjacent libraries, upstream docs
5. **Troubleshooting / FAQ** if the question volume warrants it

Common reorderings worth checking:

* **Install too low** — if it's after Libraries / Tools, readers can't try the code shown earlier.  Move Install right after the first code samples.
* **Pitch too low** — if differentiators come after the inventory, readers may leave before being convinced.  Consider above code samples.
* **Project-template too early** — readers haven't seen what real use looks like yet.  Defer until after libraries + workflow sections.
* **Status section mixing two concerns** — *"## Status & contributing"* with one paragraph about development status and another about how to contribute usually wants to be split (or the status content removed entirely if it just reads as a hedge).
* **Library README missing License footer** — PyPI's rendered README is often the only license artefact a user sees from the package.  At minimum a one-line `## License — [MIT](https://github.com/.../LICENSE)` pointer.
* **Library README's contributing section assumes mono-repo context** — mentioning `chumicro-workspace add-device` without telling the PyPI reader they need the mono-repo cloned creates a context cliff.  Prefix the section or split the audience.

### 6. Visual layout + markup + hero/nav

* **Hero / nav block.**
  * **Title** — must say what the project is.  *"# Project name"* alone isn't enough.
  * **Tagline** — answers *"what is this for?"* in one phrase; pair it with a *"for whom?"* phrase if the audience isn't obvious.  *"Cross-runtime hardware utilities"* names the what; *"for CircuitPython, MicroPython, and Python"* names the for-whom.  Both needed.
  * **Nav block** — usually includes Install and Contributing; Workspace-template / external-repo links pay off when they exist.
  * **`<big>` for nav** — for nav blocks with many entries, `<big>` (GitHub-rendered) helps them feel like navigation rather than running prose.
* **Centered / left-aligned bouncing** — centered hero, then a wall of left-aligned intro text, then a centered nav block, then a horizontal rule creates visual whiplash.  Keep the hero block together (logo + title + tagline + nav), insert the `---` ruler, then left-aligned body content.
* **Comment column alignment in code blocks** — when a block has trailing `# comment` annotations across multiple lines, all `#` symbols should land at the same column.  Verify with:
  ```
  awk 'NR>=N1 && NR<=N2 {n=index($0,"#"); printf "L%d col=%d\n",NR,n}' <file>
  ```
* **Dead anchor links** — renaming a section without updating links breaks navigation silently.  After every section rename, verify all `(#...)` references resolve:
  ```
  grep -nE '\(#[a-z0-9-]+\)' <file>
  ```
  GitHub anchor slug rules: lowercase, spaces → hyphens, em-dashes / parentheses dropped.  Test on github.com if in doubt.
* **Mixed conventions** — `python` vs `python3` invocations, `http://` vs `https://` URLs that should match the published examples, two different ways of writing the same brand name.  Pick one per doc.
* **Markup-style consistency.**
  * **Backticks** for identifiers, file paths, CLI invocations, literal config keys.
  * **Italic** for emphasis and the first use of a term being defined.
  * **Bold** sparingly — for the load-bearing claim of a paragraph.  If three things in one paragraph are bold, none are.
  * **Heading depth.**  README starts at H1 (the title) and rarely needs deeper than H3.  `docs/guide.md` usually starts at H1 too (the page title); if the docs-site renderer injects a title, start at H2.
  * **Paragraph length.**  When a paragraph runs past four sentences, consider whether it's actually two paragraphs.
* **Render before flagging layout.**  Some intent is only visible rendered (centered alignment, `<big>`, table widths, image scaling).  If the raw markdown doesn't make the intent clear, push to a draft branch and view on github.com before flagging.

### 7. Stale examples

Code examples should actually run.

* **Pseudocode masquerading as real code** — if the example shows the SHAPE but skipped real imports or used a wrong attribute name (e.g. `wifi.radio` when the API is `wifi.adapter.radio`), flag.  Verify against the actual library source.
* **Examples that import libraries the README hasn't introduced** — install instructions must cover everything the example imports.
* **Hardcoded placeholders that look real** — `your-network` / `your-password` / `broker.example.com` are clearly placeholders; `10.0.0.5` looks like a real local IP and confuses readers.
* **URLs that imply guarantees** — `https://example.com` in a code example after the surrounding prose has explicitly disclaimed TLS verification claims = inconsistency.  Switch to `http://` or restore the claim with verification.
* **Examples shown but never tested on hardware** — if the README walks through `chumicro-workspace deploy-example wifi connect_to_ap` and similar, those should actually still deploy + run.  Confirm with the published example file's docstring + a spot deploy.

### 8. Inline comments + code-comment density

Trailing `# comment` annotations should narrate behavior, not label operations — and they should pull their weight, since example blocks ship as flash bytes when copy-pasted.

* **Labels** — *"# start a request"* — flag.
* **Narration** — *"# every 30 s, queue a fetch for example.com"* — keep.
* **Runtime / runner relationship narration** — for runner-shaped code, the comment should name the runner's call relationship: *"# Runner calls this every 30 s — if no fetch is in flight, queue a new one"*, *"# Runner asks this every tick — True once the response is ready"*.
* **Density.**  An example block with a comment on every line usually has labels masquerading as narration.  Three comments on a 20-line block is a healthy rate when each names a *why*.
* **Per-change audit-style comments don't belong in examples.**  *"# bench-validated -25 % allocation"* or *"# skips the bytes() copy"* — these are commit-message material, not example code (see `feedback_audit_comments_in_commit_not_code.md` for the broader rule on user-facing artefacts).

### 9. Historical rationale

History belongs in `git log`, not in the artefact.

* **"Previously this…" paragraphs** — flag.  The reader doesn't need to know what the API used to do; they need to know what it does now.
* **`<!-- removed in 0.x -->` HTML comments** — flag.  If a section is removed, remove the marker too.
* **Dated migration notes** — *"As of 2025-11-02, the X parameter…"* — drop the date; if the migration is still ongoing, name what's still pending instead.  If it's complete, the note shouldn't be in user docs.
* **Retrospective rationale paragraphs** — *"This was originally implemented with Y, but we changed to Z because…"* — the *why* of the current code can stay (one sentence at most); the history of how it got here should not.
* **`## Update (YYYY-MM-DD)` sections** — drop.  Rewrite the affected prose in place; let `git log` carry the timeline.

This rule applies to user-facing docs.  Internal docs are exempt: ADRs under `plans/decisions/` (recording the decision is their job), and SKILL.md bodies under `.github/skills/` including this one.

### 10. Explanation-to-content ratio

If the prose around a thing is much longer than the thing itself, ask whether the prose needs to exist.

* **Two-line function with a five-paragraph docstring.**  Either the function is doing more than it looks like (rewrite it to be clearer) or the docstring is overgrown (cut to one line).
* **Trivial example with elaborate framing.**  *"In this section we will explore how to import a library…"* followed by a single `import` line.  Drop the framing; let the code speak.
* **Section headers that promise more than the section delivers.**  *"## Advanced configuration patterns"* containing one paragraph and one code block doesn't earn the *"Advanced"* qualifier.  Rename or fold up.
* **Same idea explained three times.**  Often a sign that the first explanation wasn't clear enough — fix the first, drop the other two.

Flash cost matters here too: every byte in `docs/guide.md` that's mirrored into example payloads or shipped with the package costs.

## Procedure

Walk these passes in order (each dimension's body has the specific check — regex / grep / awk — inline):

1. **Stumble-walk** (dim 1) — three reads end-to-end; notes-as-you-go for dims 3, 7, 8 since they surface during the read.
2. **AI-tic + grammar grep** (dim 2) — run the standing regex from dim 2; hard-ban hits (`canonical`, `idempotent`) almost always need rewriting, soft hits (`under the hood`) are case-by-case.
3. **Structure map** (dim 5) — `grep -nE '^## ' <file>`, compare against the question arc for the doc's type.
4. **Visual passes** (dim 6) — anchor check (`grep -nE '\(#[a-z0-9-]+\)' <file>`) + comment-column awk on any block that has trailing `#` annotations.
5. **Load-bearing claims** (dim 4) — list every claim a reader might rely on for security / correctness / compatibility; for each, bench-verify or soften.
6. **History + trivia sweep** (dims 9, 10) — grep `previously`, `used to`, `as of `, `<!-- removed`, `## Update`; read for explanation/content ratio on long sections.

### Punch-list

Group findings by confidence and tag by dimension (see Output format).

### Execute the HIGH-confidence batch

After the user gives the go-ahead, execute the HIGH-confidence fixes as a single edit pass.  MEDIUM items wait for user confirmation; LOW items wait for user answers.

### After-action sweep + exit condition

Re-run the dim 2 grep and the dim 6 anchor check on the changed file.  The audit is done when:

* AI-tic grep returns no unjustified hits (legitimate technical-term uses fine).
* Every accepted punch-list item has a corresponding edit (or a deferred-to-`plans/next-up.md` entry if the fix is bigger than the audit).
* The three-reader reread (cold / advanced / beginner) doesn't surface a new stumble.

If the post-audit reread still surfaces stumbles, that's a separate pass — file as a follow-up rather than expanding the current one.

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

  structure    §<section> — <restructure proposal + rationale>
  claim        L<n> — <claim to verify or soften>
  trivia       §<section> — <explanation/content ratio off>
  ...

LOW-CONFIDENCE (questions for the user):

  visual       §<section> — <layout / markup question>
  ...
```

**Worked example** (synthetic — illustrative shape, not a real file):

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

Tag taxonomy:

* `jargon` — internal vocabulary used before defining (dim 1).
* `ai-tic` — vocabulary or grammar tic from dim 2.
* `impl-leak` — internal metric / lint code / `plans/` reference in user-facing prose (dim 3).
* `claim` — load-bearing technical claim, verify or soften (dim 4).
* `structure` — section ordering, splitting, renaming (dim 5).
* `visual` — layout, markup, hero/nav, anchor (dim 6).
* `stale` — example doesn't run as written (dim 7).
* `comment` — inline-comment label vs narration (dim 8).
* `history` — historical rationale that should be in `git log` (dim 9).
* `trivia` — explanation-to-content ratio off (dim 10).

## Surface questions instead of guessing

When the same patterns recur across audits, **ask** rather than acting:

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

**Content don'ts** (what not to write into the punch-list):

* **Don't golf for word count.**  Sometimes longer prose is clearer.  User framing: *"you don't have to be so compact, these one-liners don't say much."*  Add words when they help comprehension.
* **Don't strip every "the".**  *"the LED"*, *"the loop"*, *"the request"* are specific singular nouns — dropping the article reads wrong.  Only flag the genuinely-redundant ones.
* **Don't restructure based on taste alone.**  The three-reader walk gives an objective lens.  *"I'd write it differently"* is not a reason to move things.

**Verification don'ts** (what not to skip before flagging):

* **Don't ship sweeping claims without bench verification.**  Even features that *should* work cross-runtime sometimes don't.  Verify or soften before letting a claim land in a finding.
* **Don't trust raw-markdown reads for layout intent.**  Some visual decisions are only legible rendered — push a draft and view on github.com when in doubt (see dim 6).

**Process don'ts** (how not to act on the punch-list):

* **Don't auto-commit.**  Docs changes need user review.  Surface as punch-list first; execute HIGH-confidence batch only after explicit go-ahead.
* **Don't reinvent the AI-tic list per pass.**  The regex in dim 2 is the source-of-truth; add new flagged words to `feedback_doc_writing_taste.md` user memory when the user surfaces new ones, and update the regex here too so they stay in sync.
* **Don't expand the audit scope mid-pass.**  If the post-audit reread surfaces a new stumble, file it as a follow-up rather than folding it into the current audit's edit batch.

## Defer / out of scope

* **API reference docs** — autogenerated from docstrings; this skill targets human-curated prose.
* **Internal docs** (`plans/`, `AGENTS.md`, `.github/skills/<name>/SKILL.md`, decision records under `plans/decisions/`) — different audience, different rules.  Use `audit-skill` for SKILL.md files; use `audit-publishable-isolation` for leak detection between internal and shipped trees.
* **Tone calibration** — friendly vs formal, second-person vs third-person.  Match the project's existing tone; don't impose a new one.
* **Long-form rewrites** — if more than ~30 % of the doc needs reshaping, this is a rewrite, not an audit.  Surface the scope and let the user decide whether to escalate.
