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

### "this is the / this is a" openers

Don't open sentences with "this is the" or "this is a" to point back at what was just said.  Restate the subject directly, or drop the meta sentence entirely.

For example, instead of "Run preflight before every commit.  This is the rule the recovery skill enforces", write "The recovery skill enforces preflight before every commit".

### Empty adjectives

Drop adjectives that don't carry information: `comprehensive`, `robust`, `seamlessly`, `cutting-edge`, `best-in-class`.

If you'd reach for `comprehensive`, list what it covers.  If you'd reach for `robust`, name what it survives.

### Filler sentence-openers

Don't open sentences with filler like "It is worth noting that", "It should be noted that", "Note that", "Let's dive into", "Let's explore", or "In this section, we will".  Start with the content.

### CHU lint codes in prose

In publishable trees, don't cite CHU lint codes in prose.  Name the rule's intent instead.  For example, write "silent test skips" rather than "CHU009".

Enforced by `CHU006`.  The `# noqa: CHUNNN` directive is exempt.

## Degraded prose is rewritten, not trimmed again

A passage rotted by repeated subtractive edits is not fixed by removing another word.  That only makes it shorter and no clearer.  Discard it and rewrite from a fresh read of what the thing is and why it exists.

Several skills apply this rule in their scope:

- [`audit-comments`](../../.github/skills/audit-comments/SKILL.md) for code comments.
- [`audit-docs`](../../.github/skills/audit-docs/SKILL.md) for user-facing markdown.
- [`audit-skill`](../../.github/skills/audit-skill/SKILL.md) for SKILL.md bodies.
- The in-place-edit rule in [`plans/decisions/README.md`](../../plans/decisions/README.md) for ADR bodies.
