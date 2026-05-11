---
name: audit-docs
description: Audit a user-facing markdown doc (README, INSTALL, library guides) for cold-reader readability, AI-tic phrases, jargon and implementation-detail leaks, unverified claims, section ordering, and visual / link consistency.  Produces a punch-list grouped by confidence, then executes high-confidence cleanups with user sign-off.  Use when a README has accumulated drift, after a substantial feature pass, or before a release-prep pass.
---

# Docs audit

Audit one human-curated markdown doc (README.md, INSTALL.md, `libraries/<name>/README.md`, etc.) for the things that make a doc unreadable for a cold reader.  Output a prioritised punch-list, then execute the high-confidence batch with the user's go-ahead.  Surface medium / low confidence items as questions so the user can answer them rather than guessing.

## Scope

User-facing markdown — primarily READMEs, but also INSTALL.md, contributing guides, hosted-docs source pages.  Out of scope: internal docs (`plans/`, `AGENTS.md`, decision records under `plans/decisions/`) — those have a different audience and different rules.  Out of scope: auto-generated API reference docs.

Argument: file path (default `README.md`).  Example: `/audit-docs README.md`, `/audit-docs libraries/wifi/README.md`, `/audit-docs INSTALL.md`.

## Audit philosophy

The lens is **"can a cold reader follow this top to bottom?"**  Assume the reader landed from a search result.  They don't know the project, don't know the team's vocabulary, don't have the workspace cloned, and have ~60 seconds of patience.  Every paragraph either advances them or loses them.

Most doc problems fall into:

* **Jargon leak** — internal vocabulary used before defining ("the runner", "the canonical X", "mono-repo", "workspace")
* **Implementation-detail leak** — internal metrics in user-facing prose (coverage %, specific test-board names, CHU lint codes, `plans/` references)
* **AI-tic filler** — words/phrases that read non-human or dilute meaning
* **"The" overuse + grammar tics** — articles before brand names, "is the one that" redundancies, stacked definites
* **Unverified technical claims** — sweeping default-behavior claims that haven't been bench-tested
* **Structural flow** — sections don't match the cold-reader question arc
* **Visual inconsistency** — centered/left-aligned bouncing, dead anchor links, misaligned comment columns in code blocks
* **Stale examples** — code that doesn't actually run as written, or no longer matches the libraries' shipped behaviour

## Audit dimensions

Run each.  Capture findings as `<line>:<col>` (or section name) + one-line description + dimension tag.

### 1. Cold-reader test

Read top-to-bottom and flag every place you stumble.

* **Jargon used before defined.**  "Workspace", "mono-repo", "runner-shaped", "the canonical X" — name the thing concretely on first use or define it.  Today's example: *"The mono-repo itself is a ChuMicro workspace"* near the top — reader has no idea what either of those mean.
* **Acronyms used without expansion.**  "MQTT" / "TLS" / "REPL" are usually fine for the embedded audience; "UF2", "esptool", "mbedTLS", "PIO" benefit from a one-phrase gloss the first time.
* **Cross-references that don't help a cold read.**  *"see Decision 0047"*, *"per CHU009"*, *"`plans/workstreams/foo.md`"* — these are internal navigation.  Inline a one-line summary instead.
* **Assumed context.**  *"When you ran the X command above"* — confirm X was actually shown above with the right name.
* **Implicit "we"** — *"we ship X"* in a public README assumes the reader is on the team.  Rephrase.
* **Audience-split mentions of mono-repo-only tooling.**  Library and workbench READMEs serve **two audiences**: PyPI / circup / mip consumers (just want to use the package) and mono-repo contributors (have the workspace cloned).  Mentions like *"register a board with `chumicro-workspace add-device`"* are useful to the second but confusing to the first.  Flag every reference to mono-repo-only CLIs (`chumicro-workspace`, `python scripts/run.py`, `chumicro-deploy`) in a published library / workbench README and ask: *"can a PyPI installer act on this?  If not, prefix with 'In the [mono-repo](url)…' or move to the dev-contributing section."*

### 2. AI-tic word audit

Standing regex (also stored in `feedback_doc_writing_taste.md` user memory):

```
grep -niE 'canonical|idempotent|comprehensive|seamless|robust|cutting-edge|best-in-class|leverage|intuitive|elegant|streamlined|battle-tested|first-class|one-stop|out of the box|worth noting|dive into|let.?s explore|effortless|painless|empowers|unleash|by construction|under the hood|got you covered|simply put|in essence|magic|powerful' <file>
```

Per-word handling:

* **canonical** — flag every occurrence (user-flagged).  Drop or replace.  Keep only the real-term uses (canonical encoding / form / path / URL).  *"Canonical starter"* → *"Starter project"*.
* **idempotent** — flag every occurrence (user-flagged).  Often filler.  When the property is real (a retried operation reaches the same end state), demonstrate concretely instead of asserting abstractly.
* **comprehensive / robust / seamless / cutting-edge / best-in-class / first-class / one-stop / out of the box / effortless / painless** — drop outright.  Demonstrate the property concretely if it's real: list what's covered instead of saying *"comprehensive"*; name the commands that make a workflow *"first-class"*.
* **leverage** — replace with *"use"*.
* **under the hood** — rephrase concretely.  *"These tools execute the deploy"* beats *"this is what was happening under the hood"*.
* **by construction** — math jargon in casual prose.  Drop.  *"One codebase, three runtimes"* beats *"cross-runtime by construction"*.
* **worth noting / it should be noted / note that** as sentence openers — just say the thing.
* **let's dive into / let's explore / in this section we will** — start with the content.
* **`CHU0NN` codes in prose** — name the rule's intent (*"silent test skips"*) not the workspace-internal code.

### 3. "The" overuse + grammar tics

* **"the" before brand names** — drop.  *"the Pi Pico W"* → *"Pi Pico W"*.  *"the ESP32"* depends on whether you're referring to a specific chip vs the family; usually drop.
* **"X is the one that Y"** — usually wordy.  *"`run.py` is the one that enforces coverage"* → *"`run.py` enforces coverage"*.
* **Stacked definite articles** — *"the X of the Y of the Z"* often has one too many.
* **"The same X"** at sentence-start — sometimes *"Same X"* reads cleaner; sometimes not.  Judgment call.

Keep *"the"* for genuinely-specific singular nouns: *"the LED"*, *"the loop"*, *"the request"* — these refer to a specific instance in the example and dropping the article reads wrong.

### 4. Implementation-detail leakage

User-facing docs should not expose internal metrics or development jargon.

* **Coverage percentages** — *"96 % workspace coverage"* is for contributors, not users.  If you want to assert testedness, list what's tested, not the percent.
* **CHU lint codes in prose** — `CHU009 / CHU010` is workspace-internal.  Name the rule's intent.
* **`plans/` / `Decision NNNN` references in publishable docs** — internal navigation aids.  Inline a one-line summary.
* **Specific test-board names** — *"WeMos / Lolin S2 + Pi Pico W in CP and MP"* is bench setup.  *"Tested on real CircuitPython and MicroPython boards before each release"* carries the same trust without naming hardware.
* **File:line refs** — fine in code comments / commit messages, jarring in user docs.
* **Internal run.py task names without context** — *"`python scripts/run.py preflight`"* is fine in a "Running tests" section; *"run preflight before committing"* in passing prose without saying what preflight does is jargon.

### 5. Verify load-bearing technical claims

Claims a reader might rely on need verification before they ship.  Stratify by stakes:

**Bench-test (deploy a probe to a real board)** when the claim is *behavioural / cross-runtime / security-significant*:
* **Cross-runtime claims** — does it work the same on CircuitPython, MicroPython, and CPython?  Runtime defaults often differ silently.  Today's example: *"built-in trust store validates against major public CAs"* — true on CP (firmware-bundled `x509-crt-bundle`), **false on MP** (`ssl.wrap_socket` with no context skips verification entirely).  Caught by deploying an `expired.badssl.com` probe to all four boards.
* **Default-behavior claims** — *"X validates by default"*, *"Y auto-reconnects"*.  Verify with a deliberate failure case (expired cert, broker offline, etc.).
* **Performance claims** — *"fast"*, *"in seconds"*, specific numbers.  Either measure or remove.

**Source-read verify** (grep / Read tool, no hardware) when the claim is *API-surface / pure-Python*:
* **API-shape claims** — *"`Heartbeat.period_ms` is read-only"*, *"`X.from_config` accepts empty dict"*.  Verify by reading the class source.
* **Compatibility claims** — *"works on every board with ≥ 256 KB / 4 MB"* — at minimum, list the families actually tested.
* **Detection-table claims** — *"`supervisor.ticks_ms` on CircuitPython 7+; `time.ticks_ms` on MicroPython"* — verify by reading the detection logic.

If a claim can't be verified, soften to a capability mention (*"supports TLS"* instead of *"validates TLS by default"*) or remove.  If the gap is structural and worth fixing in code, file it as a research item under `plans/next-up.md` → `## Investigations` and roll back the claim in the doc.

### 6. Structural flow

Two different cold-reader arcs depending on what the doc is.

**Project / mono-repo README** (a multi-library or framework-scale README):

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

Common reorderings worth checking:

* **Install too low** — if it's after Libraries / Tools, readers can't try the code shown earlier.  Move Install right after the first code samples.
* **Pitch too low** — if differentiators come after the inventory, readers may leave before being convinced.  Consider above code samples.
* **Project-template too early** — readers haven't seen what real use looks like yet.  Defer until after libraries + workflow sections.
* **Status section mixing two concerns** — *"## Status & contributing"* with one paragraph about development status and another about how to contribute usually wants to be split (or the status content removed entirely if it just reads as a hedge).
* **Library README missing License footer** — PyPI's rendered README is often the only license artefact a user sees from the package.  At minimum a one-line `## License — [MIT](https://github.com/.../LICENSE)` pointer.
* **Library README's contributing section assumes mono-repo context** — mentioning `chumicro-workspace add-device` without telling the PyPI reader they need the mono-repo cloned creates a context cliff.  Prefix the section or split the audience.

### 7. Visual layout consistency

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

### 8. Stale examples

Code examples should actually run.

* **Pseudocode masquerading as real code** — if the example shows the SHAPE but skipped real imports or used a wrong attribute name (e.g. `wifi.radio` when the API is `wifi.adapter.radio`), flag.  Verify against the actual library source.
* **Examples that import libraries the README hasn't introduced** — install instructions must cover everything the example imports.
* **Hardcoded placeholders that look real** — `your-network` / `your-password` / `broker.example.com` are clearly placeholders; `10.0.0.5` looks like a real local IP and confuses readers.
* **URLs that imply guarantees** — `https://example.com` in a code example after the surrounding prose has explicitly disclaimed TLS verification claims = inconsistency.  Switch to `http://` or restore the claim with verification.
* **Examples shown but never tested on hardware** — if the README walks through `chumicro-workspace deploy-example wifi connect_to_ap` and similar, those should actually still deploy + run.  Confirm with the published example file's docstring + a spot deploy.

### 9. Inline comments in code blocks

Trailing `# comment` annotations should narrate behaviour, not label operations.

* **Labels** — *"# start a request"* — flag.
* **Narration** — *"# every 30 s, queue a fetch for example.com"* — keep.
* **Runtime / runner relationship narration** — for runner-shaped code, the comment should name the runner's call relationship: *"# Runner calls this every 30 s — if no fetch is in flight, queue a new one"*, *"# Runner asks this every tick — True once the response is ready"*.

### 10. Hero / nav block

* **Title doesn't say what the project is** — *"# Project name"* alone is not enough.  Tagline must answer *"what is this for?"* in one phrase.
* **Tagline that doesn't answer "for whom?"** — *"Cross-runtime hardware utilities"* names the what; *"for CircuitPython, MicroPython, and Python"* names the for-whom.  Both needed.
* **Nav block missing entry points** — Install and Contributing should usually be there; Workspace template / external repo links pay off if they exist.
* **Nav font matches body font** — for nav blocks with many entries, `<big>` (GitHub-rendered) helps them feel like navigation rather than running prose.

## Procedure

### Step 1: Read the whole doc end-to-end

Read top-to-bottom in cold-reader mode.  Take notes — every place you stumble, every place a jargon term lands without setup, every claim that feels too strong.

### Step 2: Run the AI-tic + grammar grep

```
grep -niE 'canonical|idempotent|comprehensive|seamless|robust|cutting-edge|best-in-class|leverage|intuitive|elegant|streamlined|battle-tested|first-class|one-stop|out of the box|worth noting|dive into|let.?s explore|effortless|painless|empowers|unleash|by construction|under the hood|got you covered' <file>
```

Add hits to the punch-list.  Hard-ban hits (`canonical`, `idempotent`) almost always need rewriting; soft hits (`under the hood`) are case-by-case.

### Step 3: Map the current structure

List the section headers (`grep -nE '^## ' <file>`) and compare against the cold-reader question arc (dimension 6 above).  Note re-orderings and renames worth proposing.

### Step 4: Anchor + link audit

```
grep -nE '\(#[a-z0-9-]+\)' <file>
```

For each `(#anchor)`, confirm a section with the matching slug exists.  Spot-check external links.

### Step 5: Comment-column alignment in code blocks

For each multi-line code block with trailing `#` comments, run the awk check above.  Note any block where columns drift.

### Step 6: Identify load-bearing claims worth bench-verifying

List every claim a reader might rely on for security / correctness / compatibility.  For each, decide: bench-verify (write a probe + deploy to a real board) or soften / remove.  Don't ship a sweeping claim that hasn't been verified — soften to a capability mention until the bench evidence exists.

### Step 7: Surface as a punch-list

Present to the user grouped by confidence:

```
## Audit findings — <file>

### HIGH confidence (drop-in fixes)
- L<n>: <one-line fix>
- L<n>: <one-line fix>

### MEDIUM confidence (proposal — user sign-off needed)
- §<section>: <restructure proposal + rationale>

### LOW confidence (questions for the user)
- §<section>: <what we don't know + what to verify>
```

### Step 8: Execute the HIGH-confidence batch

After the user gives the go-ahead, execute the HIGH-confidence fixes as a single edit pass.  MEDIUM items wait for user confirmation; LOW items wait for user answers.

### Step 9: After-action sweep

Re-run the AI-tic grep + anchor check on the changed file.  Confirm the punch-list items the user accepted are resolved.

## Surface questions instead of guessing

Today's audit was a long back-and-forth because the same patterns recurred.  When you spot one, **ask** rather than acting:

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

## What NOT to do

* **Don't golf for word count.**  Sometimes longer prose is clearer.  User framing: *"you don't have to be so compact, these one-liners don't say much."*  Add words when they help comprehension.
* **Don't strip every "the".**  *"the LED"*, *"the loop"*, *"the request"* are specific singular nouns — dropping the article reads wrong.  Only flag the genuinely-redundant ones.
* **Don't ship sweeping claims without bench verification.**  Even features that *should* work cross-runtime sometimes don't.  Verify or soften.
* **Don't restructure based on taste alone.**  The cold-reader test gives an objective lens.  *"I'd write it differently"* is not a reason to move things.
* **Don't auto-commit.**  Docs changes need user review.  Surface as punch-list first; execute HIGH-confidence batch only after explicit go-ahead.
* **Don't reinvent the AI-tic list per pass.**  The standing regex above is the canonical list; add new flagged words to `feedback_doc_writing_taste.md` user memory when the user surfaces new ones.

## Defer / out of scope

* **API reference docs** — autogenerated from docstrings; this skill targets human-curated prose.
* **Internal docs** (`plans/`, `AGENTS.md`, decision records under `plans/decisions/`) — different audience, different rules.  Use `audit-publishable-isolation` for leak detection between internal and shipped trees.
* **Tone calibration** — friendly vs formal, second-person vs third-person.  Match the project's existing tone; don't impose a new one.
* **Long-form rewrites** — if more than ~30 % of the doc needs reshaping, this is a rewrite, not an audit.  Surface the scope and let the user decide whether to escalate.
