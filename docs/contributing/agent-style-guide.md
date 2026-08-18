# Style guide for AI coding agents

Audience: AI agents writing prose, code comments, docstrings, commit messages, and markdown docs in this repo.  Humans should read [style-guide.md](style-guide.md) instead, which covers Python style, naming, imports, type annotations, and lint.

This guide is the long-form home for tone, phrasing, and writing-discipline rules.  AGENTS.md keeps the everyday firing rules at top-of-mind.  This file carries the detail, worked examples, and the nuanced cases that don't belong inline in the operating manual.  For how humans and agents collaborate here (what to expect from an agent, how to frame a task, what to do when a session feels off), see [Working with Agents](working-with-agents.md).

## Why an agent-specific guide

AI-generated prose has a characteristic shape.  Dense em-dash chains.  Symbolic shortcuts where a sentence belongs.  Generic-sounding adjectives without a referent.  Abstract nouns sitting where the actor should.  Humans usually don't reach for those, so the human style guide doesn't warn against them.  They show up in agent output, so this guide names them.

## Say it out loud

Read each sentence the way you'd say it out loud to a colleague, and write it that way.  If you would not say it to a person, rewrite it.  Everything else in this guide is a list of shapes that tend to fail that test, collected so you know what to listen for.  They are suspects to check by ear, not commands to find-replace.

The framing is load-bearing, because the find-replace reflex degrades prose.  Swapping a flagged phrase on sight, without reading the result aloud, trades a real sentence for a worse one and calls it a fix.  *"This is a required gate, not a soft check"* once became the flatter *"The gate is required, not a soft check"* exactly that way, a ban applied against the ear.  When a flagged phrase reads fine out loud, keep it.

Two kinds of rule are non-negotiable.  Lint-backed ones a check enforces, so the agent's opinion is not part of the gate: the CHU-code ban (`CHU006`) is one, and anything marked "Enforced by CHU" is another.  The em-dash ban is the other kind: the project rules it absolute (see [§ Sentence form](#sentence-form)), even though no lint catches it.  Everything else answers to the ear: the article tests, the "canonical X" framing, the semicolons and arrows, the empty adjectives, all of it.  Some shapes fail the read-aloud test most of the time (the empty adjectives in [§ Empty adjectives](#empty-adjectives) and the loose connectors in [§ Sentence form](#sentence-form)) and most of the time you can fix them quickly; even those go through the read-aloud check, because a swap that leaves a worse sentence is a regression, not a fix.  The structural rule below is the most important shape to listen for.

## Sentence form

Write in sentences.  Em-dashes are banned outright: never use one, in code comments, docstrings, or any markdown prose.  Replace each with a period, a comma, a colon, or parentheses (an em-dash introducing a definition is usually a colon or a `which` clause in disguise), rewriting the sentence so it reads naturally.  A bare hyphen dropped in where the em-dash was is not a fix.  This is the project's ruling, set in [style-guide.md § Voice](style-guide.md#voice) and the repo's CLAUDE.md.  No em-dash earns its way out of it.

Semicolons and arrows are the suspects that do answer to the ear.  They often paper over missing connective tissue, in which case two sentences or a comma-and-connector reads better.  When the connective tissue is there and the line reads well out loud, keep them.  Applies to code comments, docstrings, and all markdown prose.

Specific shapes that usually fail the read-aloud test:

- A semicolon joining two clauses is usually two sentences.
- An arrow (→) is usually rendering a flow that wants verbs and a sentence.

Read aloud, then decide.

## Concrete subject, real verb (the structural rule)

This is the deepest way a sentence fails the read-aloud test, and the one no word-level scan catches. A sentence can carry no banned word, no em-dash, no flagged phrase, and still be unreadable, because the damage is in the structure. It is the most common reason agent prose reads as sludge.

The rule is not optional and it is not a lint. No word is wrong, so no regex can flag it. That does not soften it: the audit skills enforce it as a required pass over every rewrite, and a rewrite that still leads with an abstract subject is not done. It reshapes a sentence rather than lengthening it, so it sits with the "signal-to-noise, not byte count" rule, not against the subtractive passes.

One sentence shape does most of the damage: an abstraction in the subject slot with a weak verb. Worked case, with no banned word in it:

Before: *"Its floor is the WFI-idle that `ipoll` gives."*

After: *"A connected board idles the CPU between events, which is what `ipoll` does."*

The rewrite finds the real actor (a board) and lets it act (idles). Three faults turned the original opaque, and they travel together:

- **An abstraction in the subject slot.** *"Its floor is…"*, *"The win is…"*, *"The cost is…"*, *"The goal is…"*. The sentence is about a thing, but an abstract noun sits where the actor should. Find who acts (the board, the runner, the request, `ipoll`) and put it in the subject.
- **A nominalization carried by a weak verb.** An action frozen into a noun, propped up by a hollow verb. *"the WFI-idle that `ipoll` gives"* hides the plain sentence *"`ipoll` idles the CPU"*. The tell is a noun ending in -tion, -ment, -ing, or -al next to *is*, *gives*, *provides*, *performs*, *does*, or *has*.
- **Coined compound jargon.** *"WFI-idle"* is a noun invented on the spot and never defined. Name the action (*"idle the CPU"*), do not stack a label.
- **A trailing relative clause holding the real meaning.** *"the X that Y gives / delivers / provides"* hangs the point off the abstract noun. Lead with the point.

The test: **read the sentence the way you'd say it out loud to a colleague.** If you would not say it that way to a person, rewrite it so someone or something concrete does something.

You catch it by reading, not by grepping. The standing AI-tic regex cannot find an abstract subject or a nominalization, because no specific word is wrong. Catching it takes a per-sentence read, which is why the audit skills apply this rule as a required judgment pass and not a regex sweep.

## AI-tic phrases

Watch for AI-tic phrases.  They sound non-human, drop information, and make prose harder to skim.  The fix is usually structural, not vocabulary.  When you write "the X promise" or "the X pattern", name X concretely in the same sentence or rewrite the sentence to demonstrate the property concretely instead of asserting it abstractly.  When the phrase carries real content and reads fine out loud, keep it.

## Verify domain terminology

Code identifiers are not canonical domain vocabulary.  A method named `addCommand` does not make the thing being added a "command" in the domain sense.  A class named `XYZRenderer` does not make its output a "render" in the domain sense.  Method names are written by engineers for code-local convenience and drift from the domain over time.

Before promoting a code identifier into authoritative prose (a docstring's first sentence, a README claim, a PR description):

1. Check sibling code, prior usage in the same file or package, or related ADRs / PRs / docs for what the team actually calls this thing.
2. If you cannot verify, either hedge explicitly ("I'm using 'command' because the API is `addCommand`; please verify") or ask before drafting.

The failure mode this prevents: confident prose using wrong domain terms slips through review because the surrounding text reads fluent.  Worse than visible uncertainty.

## Phrase bans

The "ban" framing is shorthand.  These are suspects the read-aloud test flags for a listen, not commands, across all writing: code comments, docstrings, markdown docs, ADR bodies, commit messages.  Check each by ear, do not find-replace it.  When it reads fine out loud, keep it.  The lint-backed exceptions are named in [§ Say it out loud](#say-it-out-loud).

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

### Abstract opener, em-dash, concrete restatement

A sentence names a category or abstraction, an em-dash bridges, then the same thing gets said concretely.  The clause after the em-dash is the real content.  The opener adds nothing, and often mislabels (an artifact called a "rule", a file called a "policy").  Delete the opener and lead with the concrete.

Before: *"The config is declarative — you list your devices in a YAML file."* <!-- noqa: CHU037 -->

After: *"List your devices in `devices.yml`."*

Hard to spot because each half reads fine alone.  Catch it by asking whether the pre-em-dash clause survives deletion (it usually should).

### Empty adjectives

Watch for adjectives that don't carry information.  The standing list: `comprehensive`, `robust`, `seamless` / `seamlessly`, `cutting-edge`, `best-in-class`, `first-class`, `one-stop`, `out of the box`, `effortless`, `painless`, `intuitive`, `elegant`, `streamlined`, `battle-tested`, `magic`, `powerful`, and marketing phrasings like `got you covered`.

If you'd reach for `comprehensive`, list what it covers.  If you'd reach for `robust`, name what it survives.  If you'd reach for `first-class`, name the commands that make a workflow first-class.  These almost always fail the read-aloud test, but they still go through it: when the word carries real content in context (`first-class` describing a citizenship the API genuinely confers), keep it.

### Filler verbs and abstract-property claims

A small set of verbs and abstract properties tend to show up as filler.  Listen for them, and reach for the plain alternative or demonstrate the property concretely if it is real.

- `leverage` is usually `use`.
- `harness` is usually filler ("harnesses X to do Y").
- `idempotent` is often filler.  When the property is real (a retried operation reaches the same end state), demonstrate it concretely instead of asserting it abstractly.
- `under the hood` reads better rephrased concretely.  *"These tools execute the deploy"* beats *"this is what was happening under the hood"*.
- `by construction` is math jargon in casual prose.  *"One codebase, three runtimes"* beats *"cross-runtime by construction"*.
- `empowers` and `unleash` are marketing verbs.

When the original word IS the right one in context, keep it.  The check is the read-aloud test, not a substitution table.

### Filler sentence-openers

Sentence-opener filler usually adds nothing.  "It is worth noting that", "It should be noted that", "Note that", "Let's dive into", "Let's explore", "In this section, we will", "Simply put", "In essence".  Start with the content.  Keep when the opener is genuinely orienting the reader and a cold read needs it.

### CHU lint codes in prose

In publishable trees, don't cite CHU lint codes in prose.  Name the rule's intent instead.  For example, write "silent test skips" rather than "CHU999".

Enforced by `CHU006`.  The `# noqa: CHUNNN` directive is exempt.

## Standing AI-tic regex

The operational anchor for the phrase bans above is a single grep regex.  The audit skills (`/audit-docs`, `/audit-comments`, `/audit-skill`) all consume it.  New flagged words land in the bans above and this regex picks them up.

```
grep -niE 'canonical|idempotent|comprehensive|seamless|robust|cutting-edge|best-in-class|leverage|intuitive|elegant|streamlined|battle-tested|first-class|one-stop|out of the box|worth noting|dive into|let.?s explore|effortless|painless|empowers|harness|unleash|by construction|under the hood|got you covered|simply put|in essence|magic|powerful' <file>
```

**Handling a hit.**  The regex surfaces candidates, it does not decide.  Hard-ban hits (`canonical`, `idempotent`) almost always need rewriting, soft hits (`under the hood`) are case-by-case, and either way the swap is not done until the new sentence reads right said out loud.  A regex hit cleared from a sentence that now reads worse is a regression, not a fix.  See the phrase-ban subsections above for per-word guidance.

**Keep `the` for genuinely-specific singular nouns.**  *"the LED"*, *"the loop"*, *"the request"* refer to a specific instance in the example, and dropping the article reads wrong.  Only flag the genuinely-redundant ones.

**Paraphrasing keeps filler.**  When rewriting prose that already contains AI-tic words, the easy move is to keep the filler intact and swap the rest.  Audit the net delta on flagged words across the rewrite.  *"canonical"* should drop, not survive paraphrased.

## Degraded prose is rewritten, not trimmed again

A passage rotted by repeated subtractive edits is not fixed by removing another word.  That only makes it shorter and no clearer.  Discard it and rewrite from a fresh read of what the thing is and why it exists.  The rewrite has a target shape, not just "fresh": the structural rule above (a concrete subject doing something, said the way you'd say it out loud).  A fresh draft that still leads with an abstract subject and a nominalization has rewritten the words and kept the defect.

Several skills apply this rule in their scope:

- [`audit-comments`](https://github.com/ChuMicro/ChuMicro/tree/main/.github/skills/audit-comments/SKILL.md) for code comments.
- [`audit-docs`](https://github.com/ChuMicro/ChuMicro/tree/main/.github/skills/audit-docs/SKILL.md) for user-facing markdown.
- [`audit-skill`](https://github.com/ChuMicro/ChuMicro/tree/main/.github/skills/audit-skill/SKILL.md) for SKILL.md bodies.
- The in-place-edit rule in [`plans/decisions/README.md`](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/README.md) for ADR bodies.
