# Style guide for AI coding agents

Audience: AI agents writing prose, code comments, docstrings, commit messages, and markdown docs in this repo.  Humans should read [style-guide.md](style-guide.md) instead, which covers Python style, naming, imports, type annotations, and lint.

This guide is the long-form home for tone, phrasing, and writing-discipline rules.  AGENTS.md keeps the everyday firing rules at top-of-mind.  This file carries the detail, worked examples, and the nuanced cases that don't belong inline in the operating manual.

## Why an agent-specific guide

AI-generated prose has a characteristic shape.  Dense em-dash chains.  Symbolic shortcuts where a sentence belongs.  Generic-sounding adjectives without a referent.  Pointer-back openers like "this is the X that…".  Humans typically don't reach for those constructions in the first place, so the human style guide doesn't need bans for them.  They show up specifically in agent output, and they get specific bans here.

## Sentence form

Write in sentences.  Don't use em-dashes, semicolons, or arrows as shortcuts that paper over missing connective tissue.  If two ideas are linked, write them as two sentences or join with a comma and a connector.  This applies to code comments, docstrings, and all markdown prose.

Specific failure modes:

- An em-dash introducing a definition is usually a colon or a `which` clause in disguise.
- A semicolon joining two clauses is usually two sentences.
- An arrow (→) is rendering a flow that wants verbs and a sentence.

## AI-tic phrases

Cut AI-tic phrases.  They sound non-human, drop information, and make prose harder to skim.  The fix is usually structural, not vocabulary.  When you write "the X promise" or "the X pattern", name X concretely in the same sentence.  When you catch yourself writing one, rewrite the sentence to demonstrate the property concretely instead of asserting it abstractly.

## Phrase bans

These apply to all writing: code comments, docstrings, markdown docs, ADR bodies, commit messages.  Tone guidance, not lints (except where noted at the end).

### "the canonical X" framing

Avoid "the canonical X" framing.  Often "the X" or "the standard X" works as well, and frequently the bare phrase reads better still.

Keep `canonical encoding`, `canonical form`, and `canonical path`.  These are real technical terms with no fluff substitute.

### "the one / single / sole X that…"

Avoid "the one / single / sole X that…" as a definition opener.  It is the same tic as canonical X.  Say plainly what X does.

Legitimate invariant prose like "the single owner of the staging path" stays.  Tone guidance, not a lint.

### The `the X` forward-reference test

Use "the X" only when X is an established singular referent the reader already has.  Use "a X" or "an X" for forward references or categories the reader has not acquired yet.  Use bare X for systems and brand names where the article is decoration.

For example, write "ESP32-S2 firmware" rather than "the ESP32-S2 firmware".

Two nouns in one sentence often need different articles.  Indefinite articles are not clinical.  Reaching for "the" everywhere to sound terse is a frequent miss.

Apply the test per noun in every sentence of a rewrite.  Inherited `the`s compound across passes when the test isn't applied at each one.

### Definite-article tics

Beyond the forward-reference test above, three common `the`-related shapes degrade prose.

- **`the` before brand names.**  Drop.  *"the Pi Pico W"* becomes *"Pi Pico W"*.  *"the ESP32"* depends on whether the sentence refers to a specific chip or to the family.  Usually drop.
- **"X is the one that Y".**  Wordy.  *"`run.py` is the one that enforces coverage"* becomes *"`run.py` enforces coverage"*.  Same tic family as "the one X" framing, in mid-sentence form.
- **Stacked definite articles.**  *"the X of the Y of the Z"* often has one too many.  Read each `the` against the forward-reference test and drop the one that does not earn its place.
- **"The same X" at sentence-start.**  Sometimes *"Same X"* reads cleaner, sometimes not.  Judgment call.

### "this is the / this is a" openers

Don't open sentences with "this is the" or "this is a" to point back at what was just said.  Restate the subject directly, or drop the meta sentence entirely.

For example, instead of "Run preflight before every commit.  This is the rule the recovery skill enforces", write "The recovery skill enforces preflight before every commit".

### Abstract opener, em-dash, concrete restatement

A sentence names a category or abstraction, an em-dash bridges, then the same thing gets said concretely.  The clause after the em-dash is the real content.  The opener adds nothing, and often mislabels (an artifact called a "rule", a file called a "policy").  Delete the opener and lead with the concrete.

Before: *"The config is declarative — you list your devices in a YAML file."*

After: *"List your devices in `devices.yml`."*

Hard to spot because each half reads fine alone.  Catch it by asking whether the pre-em-dash clause survives deletion (it usually should).

### Empty adjectives

Drop adjectives that don't carry information.  The standing list: `comprehensive`, `robust`, `seamless` / `seamlessly`, `cutting-edge`, `best-in-class`, `first-class`, `one-stop`, `out of the box`, `effortless`, `painless`, `intuitive`, `elegant`, `streamlined`, `battle-tested`, `magic`, `powerful`, and marketing phrasings like `got you covered`.

If you'd reach for `comprehensive`, list what it covers.  If you'd reach for `robust`, name what it survives.  If you'd reach for `first-class`, name the commands that make a workflow first-class.

### Filler verbs and abstract-property claims

A small set of verbs and abstract properties show up as filler in agent prose.  Replace each with the plain alternative, or demonstrate the property concretely if it is real.

- `leverage` becomes `use`.
- `harness` is usually filler ("harnesses X to do Y").  Drop or replace with a plain verb.
- `idempotent` is often filler.  When the property is real (a retried operation reaches the same end state), demonstrate concretely instead of asserting abstractly.
- `under the hood` should be rephrased concretely.  *"These tools execute the deploy"* beats *"this is what was happening under the hood"*.
- `by construction` is math jargon in casual prose.  Drop.  *"One codebase, three runtimes"* beats *"cross-runtime by construction"*.
- `empowers` and `unleash` are marketing verbs.  Drop or replace with the plain verb.

### Filler sentence-openers

Don't open sentences with filler like "It is worth noting that", "It should be noted that", "Note that", "Let's dive into", "Let's explore", "In this section, we will", "Simply put", or "In essence".  Start with the content.

### CHU lint codes in prose

In publishable trees, don't cite CHU lint codes in prose.  Name the rule's intent instead.  For example, write "silent test skips" rather than "CHU009".

Enforced by `CHU006`.  The `# noqa: CHUNNN` directive is exempt.

## Standing AI-tic regex

The operational anchor for the phrase bans above is a single grep regex.  The audit skills (`/audit-docs`, `/audit-comments`, `/audit-skill`) all consume it.  New flagged words land in the bans above and this regex picks them up.

```
grep -niE 'canonical|idempotent|comprehensive|seamless|robust|cutting-edge|best-in-class|leverage|intuitive|elegant|streamlined|battle-tested|first-class|one-stop|out of the box|worth noting|dive into|let.?s explore|effortless|painless|empowers|harness|unleash|by construction|under the hood|got you covered|simply put|in essence|magic|powerful' <file>
```

**Handling a hit.**  Hard-ban hits (`canonical`, `idempotent`) almost always need rewriting.  Soft hits (`under the hood`) are case-by-case.  See the phrase-ban subsections above for per-word guidance.

**Keep `the` for genuinely-specific singular nouns.**  *"the LED"*, *"the loop"*, *"the request"* refer to a specific instance in the example, and dropping the article reads wrong.  Only flag the genuinely-redundant ones.  Per-noun three-way test in [`feedback_the_forward_reference`](../../../.claude/projects/-Users-chuxor-circuitpython-chumicro/memory/feedback_the_forward_reference.md).

**Paraphrasing keeps filler.**  When rewriting prose that already contains AI-tic words, the easy move is to keep the filler intact and swap the rest.  Audit the net delta on flagged words across the rewrite.  *"canonical"* should drop, not survive paraphrased.

## Degraded prose is rewritten, not trimmed again

A passage rotted by repeated subtractive edits is not fixed by removing another word.  That only makes it shorter and no clearer.  Discard it and rewrite from a fresh read of what the thing is and why it exists.

Several skills apply this rule in their scope:

- [`audit-comments`](../../.github/skills/audit-comments/SKILL.md) for code comments.
- [`audit-docs`](../../.github/skills/audit-docs/SKILL.md) for user-facing markdown.
- [`audit-skill`](../../.github/skills/audit-skill/SKILL.md) for SKILL.md bodies.
- The in-place-edit rule in [`plans/decisions/README.md`](../../plans/decisions/README.md) for ADR bodies.
