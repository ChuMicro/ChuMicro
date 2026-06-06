# Handoff 2026-05-30 — comment-generation: round 19 analyzed (corrected), round 20 run and analyzed (lean-triage + body-rule writer wins)

Supersedes `2026-05-30-comment-generation-round19-soul-vs-correctness.md`. **That file's round-19
verdict was overstated; the corrected verdict is below.** This is the active doc.

## My role

Orchestrator / analysis seat. I read outputs, decide the spec, edit the agent files, build the
package, and store what I learn here. `RUN.md` is the dispatch session's operational brief only;
analysis knowledge lives here. Agents load at session start, so I build and a fresh session runs.

## Round 20 — result and decision (the pipeline going forward)

Ran clean (42 agents). Read run-1 across all three files (full `ticks.py` and `_ca_bundle.py`;
`client.py` warm W1/W2 full) plus run-2 `ticks.py`, every magnitude checked against computation.

- **Computable nuance is recovered code-only.** On `ticks.py` all code-only configs recomputed the
  wrap facts correctly from `1 << 29` (run-1 and run-2, both voices): ~6.2 days, ~3.1 days, wrong-sign
  aliasing, and a verified `~149 h / ~74.5 h` cross-unit. No fabrication.
- **Non-computable facts are NOT recovered, but are NOT fabricated either.** On `_ca_bundle.py` the
  code-only writers honestly omitted the 17-roots / 16 KB / subset-of-CP facts (they live only in
  prose); only the lean-triage arm carried them, bound correctly (round-19's "16 KB per root" gone).
  The anti-fabrication rule held: the failure mode is a missing fact, not a wrong one.
- **Body-rule axis:** round-19's AI-tic sprawl is gone in BOTH bare arms (the bare voice reading code
  directly, not expanding a soupy ledger, is the fix). W2 (body rule) is leaner than W1, which piles
  on derivable internal-state comments. **W2 wins.**
- **Arg coverage:** both arms document every `__init__` param incl. `username`/`password` from the
  signature. The round-18 skip did not recur.

**Decision (user, this session): keep the LEAN TRIAGE + the W2 writer; do NOT go pure no-triage.**
Code-only rebuilt the computable nuance, but not enough of the non-computable data survived, and that
data matters. So the pipeline is: **lean nuance-triage (non-computable facts only) -> W2 writer (bare
voice + docstring-format requirements + "a body exists only for non-derivable nuance"), which reads
the code and recovers computable nuance itself.** Triage is kept but narrow; W2 is the writer.

**Deferred, not solved: structural / relational narrative (the `ProtocolState` transition map).** W2's
body rule drops it. The user is only slightly concerned, because that comment was probably never
accurate and never flowed. The call: this class of content (state maps, design rationale, the deeper
"why") is NOT for auto-generation. It belongs to a future **human-in-the-loop interview pass** that
constructs and verifies it with the human directly. Do not try to fix it inside the automated writer.

## Round 19 — corrected verdict (I got it wrong the first time)

I first reported guided-soul recovered the voice with clean bodies. **That was wrong, and the error
was mine: I judged the bodies by length and surface, never read them as prose, and never read run-2
at all before pronouncing.** On an actual read:

- **Correctness held:** guided-soul documented every param incl. `username`/`password` (Args block).
- **Bodies are AI-tic, not clean.** warm-guided-soul run-2 class body: *"The client owns its socket:
  once you hand one over or let it build one, `disconnect()` is what closes it."* That is a `The X`
  opener stating ownership trivia, an incoherent colon, the `X is what does Y` indirection, plus an
  invented consequence. Same disease in run-1 (`the client owns it: ... for you`, `so you never have
  to worry ... somewhere`), in `_force_non_blocking` (signature-restatement Args on a trivial
  private), and `from_config` ("Defaults to `None`." restating the signature).
- **Soul not recovered.** What I called "warm asides" are AI-tic filler. Loosening the sentence
  restraints bought *length*, not voice.
- **The no-body rule is vindicated, not retired.** "Let the body breathe" reopened exactly the
  essay/AI-tic door the ban was built to shut.
- **Bare's credential coverage is run-dependent** (skipped in round-18 run-1, covered in round-19
  run-1 via a bullet list). The `Args:` requirement makes guided/guided-soul deterministic; that is
  the real argument for the structure.

Net: loosening restraints is the wrong lever. The voice problem is unsolved; "warmth" is not "more
sentences."

## Round 20 — design (built, ready to run)

Question: does the triage step need to exist at all, and does one rule keep bodies clean? Premise:
from code alone a writer can rebuild clean comments; the only facts it can't get are non-derivable
nuance (the `ticks` wrap, computed magnitudes). So writers read **stripped, comment-free code** and
trace it for nuance; document every arg from the signature.

Three conditions, two voices (warm, engineer), sharing the **w2-notriage** anchor:
- **w1-notriage vs w2-notriage** — same code-only writer; w2 adds the rule "a body exists only to
  carry non-derivable nuance." Tests whether that one rule kills the round-19 sprawl.
- **w2-notriage vs w2-leantriage** — same writer; leantriage also hands it a lean nuance ledger.
  Tests whether tracing recovers the nuance, or the ledger is still needed.

Files: `timing/ticks.py` (the canonical wrap nuance), `sockets/_ca_bundle.py` (16 KB total / 500 B
per root / ~150 Mozilla nuance), `mqtt/client.py` (complex; full arg coverage incl. credentials).
2 runs. 6 triage + 36 writers = 42 agents. Reuses round-18 inputs read-only.

Agents (5 new, names verified, 0 em-dashes): `commenter-r20-triage-lean` (nuance-only: no PARAM
lines, no derivable behavior), `commenter-r20-{warm,engineer}-fmt` (W1), and
`commenter-r20-{warm,engineer}-fmt-bodyrule` (W2). Writers are bare voice + correct docstring
structure (summary, Args/Returns/Raises, document every arg) + a hard **anti-fabrication** rule
("never invent a fact; a wrong nuance is worse than a missing one") + trace-for-nuance.

Note on the body-rule A/B: the treatment is the rule **plus** a matching nuance-body exemplar (W2's
examples show one method earning a body for a computed magnitude, the rest none). So it's a
rule+exemplar package, not a one-line diff. If W2 wins, that's what won; isolating rule-vs-exemplar
is a later step.

## What round 20 evaluates (analysis seat)

Read both runs of all three files in full, per condition. Judge:

1. **Nuance recovery.** Did w2-notriage (code only) recover the real non-derivable facts? `ticks.py`:
   the ~3.1 / 6.2-day wrap, computed from the raw constant. `_ca_bundle.py`: 16 KB is the *whole
   file*, 500 B is *per root* (round 19's guided-soul bound these wrong). Compare to w2-leantriage:
   did the ledger catch anything code-only missed?
2. **Fabrication (the no-triage risk).** Did "tracing" invent plausible-but-wrong nuance? Verify
   every stated magnitude by actually computing it. A confident wrong number is the failure mode that
   kills the no-triage idea.
3. **Body cleanliness (the body-rule axis).** w1-notriage vs w2-notriage: does the rule eliminate the
   sprawl (ownership trivia, `X is what does Y`, expand-for-expanding), leaving bodies only where a
   real nuance lives? This is the no-body-rule-retirement gate: clean means *correct and earned*, not
   just short.
4. **Arg coverage from code.** Does the code-only writer document every param incl.
   `username`/`password` on `client.py`, or does it skip "obvious" ones the way bare did?

Verdict the round owes: (a) can triage be dropped (code-only recovers nuance without fabricating)?
(b) does the body rule produce clean bodies? If both yes, the pipeline simplifies to one writer, no
triage. If code-only fabricates or misses, lean-triage stays. If the body rule fails, the voice
problem is still open.

## Memory pointers (do not duplicate; read these)

- `[[no-docstring-bodies]]` — provisional rule; round 20's body-cleanliness result is its retirement gate.
- `[[ai-tic-actual-list]]`, `[[agent-examples-must-be-neutral]]`, `[[no-speculative-validation]]`,
  `[[cold-write-loses-facts]]` (the origin of triage: cold-write dropped `ticks_diff`'s 3.1-day limit;
  round 20 tests whether a tracing writer recovers it).
- New this session: I declared a prose-quality verdict without reading the prose. Recorded so it
  doesn't recur.

## Gotchas

- `.claude/agents/` is not git-tracked; agents load only at session start. Dispatch is a fresh session.
- The auto-mode classifier intermittently denies edits/writes under `.claude/agents/`; retry passes.
- Em-dashes banned in agent files; `grep -c '—'` must return 0 after any edit.
- Round-20 reuses round-18 `fixing/` + `stripped/` read-only; writers read `stripped/` (comment-free),
  lean-triage reads `fixing/.../input/` (with comments).

## How to rebuild context fast

Read this handoff, then `round-20/RUN.md`, then diff a W1 against its W2
(`git --no-pager diff --no-index commenter-r20-warm-fmt.md commenter-r20-warm-fmt-bodyrule.md`) to
see the body rule under test.
