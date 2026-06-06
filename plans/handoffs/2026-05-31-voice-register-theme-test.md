# Handoff 2026-05-31 — voice/register theme test (persona-only, on one real file)

Companion to `2026-05-30-comment-generation-round21-persona-bakeoff.md` (the running orchestrator doc).
This is the focused execution brief for the next thing to run. Read that doc's tail first for the full
arc; this file is self-contained for the immediate test.

## Why this test exists

Persona iteration kept producing comments that are accurate-ish but read as generic AI prose. Two
findings this session forced a reset of approach:

1. **Disposition is not register.** The "blunt kernel maintainer" voice paragraph specifies a
   *disposition* (hunt the trap, no decoration) but says nothing about *register*, so the model adopts
   the disposition and renders it in its native AI-tic prose. Confirmed on real code: the output was
   riddled with "The whole point of this module:", the "X is not Y, it's Z" antithesis (4x in one
   file), "load-bearing", "the entire", and em-dashes throughout.
2. **The persona's own prose register leaks into the output.** The voice paragraph is itself written
   theatrically ("read ten thousand bad comments and has no patience for any of them"), and the model
   imitates that register. The whole file is an exemplar of register, not just the ```python``` block.

Decision (user): stop tuning a named character. Test **theme-based** persona paragraphs, persona-only
(no rules, no ledger, no discipline block), against ONE real file, to find which theme produces *soul*
(a real point of view) with the fewest AI-tics. Add rules back ONLY after soul shows. The user's framing:
chicken-and-egg — the persona performs best with good exemplars, but the more the persona produces good
prose on its own, the better the exemplars we lift from it will be.

## Grounding lesson baked into the target file

A prior no-code voice test was worthless for grounding: with nothing to read, the agent recalled the
canonical token-bucket-rate-limiter lore (it picked that domain twice unprompted) and reverse-engineered
code to host the memorized gotchas. Recall, not reading. So the target below is a **non-canonical**
file the model has no stored lore for — it must actually read it. On that file the same voice DID ground
hard (found a real latent bug), which proves the voice reads when there is real unfamiliar code; the
register is the only thing still broken.

## Clean-context precondition (the reason for the reload)

Sub-agents inherit the main conversation's CLAUDE.md/memory. `CLAUDE.md` is now **empty** (the `@AGENTS.md`
import was removed) so a fresh session's sub-agents get NO project rules. Auto-memory is off and the store
is empty; git-status is off (`includeGitInstructions: false`). VERIFY before dispatching:

```bash
echo "CLAUDE.md=[$(cat CLAUDE.md)]"   # must be empty
grep -c '@AGENTS' CLAUDE.md           # must be 0
```

If CLAUDE.md is empty, sub-agents are clean and the persona paragraph is the only variable. (Re-reference
`@AGENTS.md` in CLAUDE.md before any real library commit — the repo rules must be live for normal work.)

## Target file (no comments — agent does pure markup)

`.scratch/regen-comments/voice-test/quality_ranking.py` — a `QualityRanking` comparison algorithm written
this session, deliberately no comments/docstrings. Domain: pick between two component builds by quality
flags + dual software versions (v1 always present, v2 optional), with a minor-version-drift rule that
disables v2 when the dual-stack build's v1 falls too far behind. Runs clean (`python` it: prints
`bravo True` / `alpha False`).

**Real traps in it (the grounding checklist — did the markup find these by reading?):**
- `_resolve_mixed` compares **minor only** and does not guard differing majors — a major bump makes the
  drift arithmetic meaningless. (The planted latent bug; the strongest grounding signal.)
- The drift gate is `>= MAX_MINOR_DRIFT` (3), and the demo's alpha-vs-bravo hits it **exactly** (2.7−2.4=3).
- "No v2" is handled two ways: `None` is the branch condition in `pick()`; `or Version(0,0)` in `_rank_key`
  is only a tiebreaker. Same concept, two places, different roles.
- `bin(flags).count("1")` popcount depends on the flag values being **distinct bits** — collapse them and
  the count silently lies.
- In the mixed branch, **flag count is ignored**; only version drift decides.
- Ties go to `left` (`>=`, not `>`).

## The 10 theme paragraphs to test (persona-only, no character)

Each is the ENTIRE style instruction for one arm. They are written flat on purpose (the spec's register
is the exemplar). Spread runs austere → voiced so we can see where soul appears vs where tics appear.

- **V1 economy:** You write the shortest true sentence and stop. A comment costs the reader time, so it
  has to return more than it costs. When a line of code already states something, you add nothing about
  it. When you do write, one fact per sentence, no warm-up and no summary of what you are about to say.
- **V2 trap-first:** You write down what will bite someone. A value that looks safe and is not, an order
  two calls have to keep, a case the code handles quietly that a reader would get wrong. You skip
  everything the code states plainly and spend words only where the code hides a consequence.
- **V3 flat declarative:** You state facts and let them sit. You do not frame them, build up to them, or
  set one against another for effect. Name the behavior, name the condition, name the result, in plain
  order, and trust the reader to draw the conclusion.
- **V4 the 3am reader:** You write for someone reading this at 3am with a system down. They are tired,
  they are scanning, and a wrong guess costs them an hour. Tell them the one thing that saves them, and
  nothing they could work out themselves given time they do not have.
- **V5 earned by reading:** You write only what you confirmed by reading the code. Every sentence traces
  to a line that runs, not to a name or a nearby string. A comment is your evidence that you read the
  function, so it says what the function does, never what you assumed it does.
- **V6 the inheritor:** You write for the next person who has to change this code. You tell them what
  breaks if they touch the wrong line, which pieces depend on each other, and which quiet assumption
  holds the whole thing together. You are handing off, not narrating.
- **V7 opinionated veteran:** You have watched this kind of code fail before, and you say so. When
  something is fragile you call it fragile and give the reason. When one decision holds up everything
  around it, you point at it. You are not neutral about this code. You have a read on it, and the read is
  what the reader came for.
- **V8 plain speech:** You explain it the way you would say it out loud to the person at the next desk.
  Real sentences, plain words, no ceremony, no jargon you would not use in conversation. If you would not
  say it to their face, you do not write it down.
- **V9 precision:** You name the exact thing: the exact value, the exact condition, the exact field that
  decides the outcome. You never reach for a category when a specific is sitting right there, and you
  never write "usually" or "some" when the real number is in the code. Vague reads the same as wrong to you.
- **V10 subtraction:** You start from silence and earn every comment. Most lines get nothing, because most
  lines are already clear. You add a sentence only when you can name something a reader could not get from
  the code in front of them, and when nothing clears that bar you write nothing and move on.

## Dispatch (temporary sub-agents, no sub-sessions, no workflow required)

For each theme, dispatch a temporary `general-purpose` sub-agent, `model: opus`. To keep orchestrator
context clean across ~40 runs, have each sub-agent WRITE its output and return only the path. Prompt
template (paste the theme paragraph verbatim as the voice; NO other rules):

```
You will add docstrings and comments to a Python file, in one specific voice. This paragraph is the
entire style instruction. There is no other style guide and no example to imitate:

"<THEME PARAGRAPH>"

Read CODE /Users/chuxor/circuitpython/chumicro/.scratch/regen-comments/voice-test/quality_ranking.py
Add docstrings and comments in the voice above, across the whole file. Add docstrings and comments only;
every line of executable code stays byte-identical. Write the marked-up file to
/Users/chuxor/circuitpython/chumicro/.scratch/regen-comments/voice-test/runs/<THEME>/run-<N>.py
(create the directory). Report only the path you wrote. Do not explain your choices.
```

Design: **10 themes × 4 runs = 40 dispatches.** Run count separates theme effect from run-to-run noise
(noise is real in this work). Batch the Agent calls in parallel (~8-10 at a time). A small Workflow can
fan out all 40 and is fine (it uses temporary sub-agents, not sub-sessions) if direct batching is tedious
— but direct Agent-tool dispatch matches the user's "just temporary sub agents."

## Eval (per theme, reading run outputs)

1. **Soul** (the actual selection axis): does it read like a person with a point of view, or like generic
   competent AI prose? This is the thing we are hunting.
2. **AI-tics** (the disqualifier): "the whole point" / "worth noting" / "the key insight" / "load-bearing"
   / "the entire X"; the **"X is not Y, it's Z"** antithesis; em-dashes; semicolons. Count and quote.
3. **Grounding** (proof it read): how many of the six real traps above did it find? Cross-major drift and
   the None-vs-(0,0) split are the hardest; finding them = genuine reading.
4. **Restraint:** length per docstring; did it stay terse or sprawl into essays.

Pick the theme(s) that show soul with the fewest tics while still grounding. Then (user): hand-edit the
best output to strip residual tics, OR start adding rules to see if the example self-fixes. Either way the
winning theme paragraph + its best output become the seed for the next persona.

## After a winner emerges (the rules half)

Voice fix method already worked out (do NOT re-derive): (1) flatten the persona's own prose and drop any
celebrity/character framing — naming a person invites an impression, which is performance; (2) hand-author
the ```python``` exemplars in true register (the agent can't — it emits tics — so a human writes them),
non-canonical domain; (3) before/after pairs for the specific tics (antithesis reversal → flat declarative;
"the whole point" → deleted); (4) mechanical bans for the enumerable prefaces (self-checkable, hold ~100%
like the em-dash ban). Subtraction (bans) kills tics; addition (flat spec + exemplars) installs register —
both halves needed.

Also agreed this session: **fix the stand-alone rule to allow SAME-FILE cross-symbol references** (the
voice naturally links interlocking methods like `pick` ↔ `_resolve_mixed`, and within one file that is
useful, not noise). The rule should ban cross-MODULE pointers, not same-file ones.
