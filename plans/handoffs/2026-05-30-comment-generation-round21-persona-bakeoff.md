# Handoff 2026-05-30 — comment-generation (round 21 bake-off → exp1–exp8 voice/ruleset study)

Supersedes `2026-05-30-comment-generation-round20-triage-necessity.md` (keep it for the round-19/20
verdict detail). This is the active doc. **Latest state is the `## 2026-06-04 (cont. 3) — exp5–exp8`
section near the bottom — start there;** rounds 20–31 above are the older `commenter-r21-*` lineage
(ticks.py/client.py). The exp1–exp8 thread (synthetic `quality_ranking.py`, voices linus-sebastian/
cantrill/cutler/elon/torvalds/hemingway/pewdiepie) is the current work; settled answer = generator
`vf` (the `No showboating.` rule was FALSIFIED by the exp8.5 n=5 A/B), harvest best-of-N by human
pick, tic target human-level.

## My role

Orchestrator / analysis seat. I build the spec + agents, a fresh session runs, I read the output and
decide. `RUN.md` is the runner's brief; analysis knowledge lives here. Agents load at session start.

## Settled state coming in (from round 20)

The pipeline is decided: **a lean nuance-triage (non-computable facts only; no PARAM lines, no
derivable behavior) feeds a W2-style writer (bare voice + docstring-format requirements + "a body
exists only for non-derivable nuance" + document-every-arg + trace-for-nuance).** A code-only writer
recovers computable nuance (it recomputed timing's ~6.2 / ~3.1-day wrap from `1 << 29`) and omits
non-computable facts rather than fabricating them, so triage stays but only for the prose-only class.
Structural/relational narrative (state-transition maps, deep rationale) is deferred to a future
human-in-the-loop interview pass, not auto-generated. Detail in the superseded round-20 handoff.

## Round 21 — what it is

A **persona bake-off**: hold that whole discipline constant and vary only the voice, to find which
register writes the best comments. Eight writer personas, each the same W2 spec with a different
personality + exemplar; all comment the SAME `RateLimiter` exemplar (only the prose differs), and at
runtime all read the SAME lean ledger + stripped code. So any difference in output is voice.

- Voices: `elon` (terse first-principles), `linus` (blunt, trap-focused), `mayo` (calm clinical
  plain-language), `foreman` (folksy enthusiast), `dexter` (precise boy-genius), `pewdiepie`
  (high-energy casual), `charlie` (deadpan dry), `attenborough` (naturalist observer, my added pick).
- Files: `timing/ticks.py` + `mqtt/client.py`. 2 runs. 36 agents (4 lean-triage + 32 writers).
- Reuses `commenter-r20-triage-lean`; reuses round-18 inputs read-only. Agents verified: names match
  filenames, 0 em-dashes, no exemplar docstring opens with `The`/`That's`.
- Goal: pick **3-4 winner voices**, then a later round runs only those.

## What round 21 evaluates (how to pick winners)

The discipline is held constant, so correctness should be roughly uniform; the differentiator is
**voice quality for code comments**. Read all 8 on `ticks.py` in full first (small, efficient
primary screen), then spot-check `client.py` for how the voice holds on complex code. Judge each:

1. **Does the personality fight the discipline?** A voice that forces a banned `The`/`That's` opener
   (watch `charlie`'s deadpan closers), adds hype (`foreman`, `pewdiepie`), or lets wonder obscure
   the fact (`attenborough`) is penalized. The best voice rides the discipline, doesn't strain it.
2. **Accuracy held?** Nuance recovered correctly (the wrap magnitudes), no fabrication, every param
   documented, body only where a non-derivable fact lives. Should be uniform; flag any persona that
   slips.
3. **Is it genuinely readable and professional?** Pleasant to read, clear to a cold reader, and not
   embarrassing in a shipped library. That is the actual selection axis.
4. Read in full, quote the lines that earn each verdict (do not judge by surface or one file).

Deliverable: 3-4 voices that read best, with quoted evidence, recorded here for the next round.

## Round 21 result — winners picked

Ran clean: 4 ledgers + 32 files. Both ticks.py ledgers caught the full nuance (6.2-day wrap,
3.1-day half-period, monotonic truncation, diff aliasing). Accuracy held uniformly: every persona
recovered the wrap magnitudes on `ticks.py` and the per-tick recv cap / FIN-vs-EAGAIN distinction on
`client.py._read_inbound`. So the call is voice quality, as designed.

Two cross-persona notes, neither a disqualifier:
- **"MQTT 3.1.1"** appears in `pewdiepie` (both runs), `linus` (run-2), `charlie` (run-2). Three
  independent agents converging means it is domain inference from the visible packet set
  (CONNACK/PUBACK/SUBACK + QoS 0/1 = protocol level 4), not invention. Still the one claim to
  human-spot-check: the version byte lives in `_wire.encode_connect`, not in `client.py`.
- **Module docstring drop**: `linus` and `charlie` omitted the `client.py` module docstring in run-1,
  included it in run-2. Run-to-run variance, not categorical. A reliability watch, equal for both.

### Winners (4), with evidence

1. **elon** (terse minimalist) — top overall. Best density and signal-to-noise; module docstring in
   both runs. `ticks.py`: *"Wrapping millisecond clock that fits every tick value in a small
   integer."* `client.py`: *"Drives an MQTT session against a non-blocking socket, one tick at a
   time."* / *"A zero-length read is the peer's FIN and raises; EAGAIN no-data takes the same zero
   path without error."* Nothing wasted, nothing missing.
2. **dexter** (precise complete) — most thorough and reliable; the careful-senior-engineer register.
   Fullest Args, consistent module docstring. *"advancing a small state machine from ``DISCONNECTED``
   through ``AWAITING_TRANSPORT``, ``CONNECTING``, and ``CONNECTED``, falling to ``FAILED`` on any
   protocol or socket fault. QoS 0 and QoS 1 publish are supported; QoS 2 is deliberately absent."*
3. **charlie** (deadpan dry) — best distinctive voice that stays professional, with the sharpest
   mental models. `ticks.py`: *"Treat the numbers as positions on a circle, not as growing
   integers."* / *"Strictly less passes; equal or more does not."* `client.py`: *"The five strings
   the client's ``state`` attribute can hold. Nothing more."* / `allow`: *"It will not warn you
   first."* Watch: the run-1 module-docstring drop.
4. **mayo** (clinical plain) — the reliable neutral house voice. Complete, never cute, never wrong,
   module docstring in both runs. *"Speaks MQTT to a broker without ever blocking, advancing one
   small step each time the runner calls it."* Slightly wordy/long lines is its only weakness.

### Alternate for the 4th slot

- **linus** (blunt trap-flagger) — highest *practical* value of any voice; it warns about the gotcha
  no one else does. `ticks.py`: *"Never compare two tick values with ``<`` or subtract them raw, the
  wrap will bite you."* `_AWAIT` tags: *"The string value never leaves this module; it only has to
  compare equal to itself."* Held out of the top 4 only on format looseness: semicolons in
  docstrings, run-on single-line class docstrings, one coined compound (`zero-with-no-error`), and
  the run-1 module-docstring drop. If a later round tightens its format block (kill semicolons, split
  long docstrings, guarantee the module docstring), it should displace `mayo`. Worth harvesting its
  warning instinct into the shared exemplars regardless.

### Cut, with reason

- **foreman** — warm and readable but tips into cute/hype: *"No threads, no blocking sends, no
  surprises."* Least serious for a shipped library.
- **pewdiepie** — energetic and disciplined but the most casual register (*"A QoS 1 publish that's
  out the door but hasn't been PUBACK'd yet."*) and the origin of the version claim. Casual is a risk
  for a published API.
- **attenborough** — elegant in isolation but verbose, with run-on single-line module/class
  docstrings that never split summary from body. Weakest format-fit for code docs.

Next round runs only the winners (elon, dexter, charlie, mayo; or swap mayo->linus with a tightened
format block) on a wider file set.

### User's final verdict (authoritative; supersedes the analysis-seat ranking above)

Keepers: **elon, foreman, linus, pewdiepie.** The user's taste diverged from the analysis seat on two
voices and that calibration is worth keeping:

1. **elon** — most data, best wording and legibility. (Agreed.)
2. **foreman** — "energetically technical." The analysis seat cut it for mild hype; the user reads that
   energy as a feature, not a defect. Recalibration: folksy-but-technical is wanted, not penalized.
3. **linus** — kept *despite* the run-1 module-docstring drop, because of how it documented
   `ProtocolState`: it pulled in state-machine behavior (which `_AWAIT`/state means what) that the lean
   nuance-triage never carried. That detail came from the writer **tracing the code**, not a ledger
   bias. Confirms the round-20 finding: code-tracing writers recover structural detail the triage drops.
4. **pewdiepie** — "the casual behavior is actually quite enjoyable, the best casual comment stream."
   The analysis seat down-ranked it for register; the user wants a strong casual voice in the set.

Down-ranked by the user (not kept):
- **dexter** — "actually good, but gets a bit breathy, a little too verbose." True to persona, not to
  the user's taste.
- **mayo** — "pretty good but the persona may be too generic, so it's leaking to AI-tic behaviors."
  Cited word-soup: *"The seconds-based timeouts are stored internally in milliseconds."* A too-generic
  persona drifts back toward AI-tic phrasing; personality has to be specific enough to anchor the voice.
- **attenborough** — "very clear verbiage but the run-on sentences were systemic."

Taste signal for future rounds: a distinct, specific persona resists AI-tic drift better than a generic
"good engineer" one; energy and casual registers are wanted as long as they stay technical and legible;
systemic run-on sentences are a hard fail regardless of clarity.

## Round 21.b — warm + engineer comeback (built, ready)

Round 21 dropped the two repeat pre-bake-off winners (`warm`, `engineer`). They never faced the keepers
on the settled discipline, so 21.b runs them head-to-head. Built apples-to-apples: `commenter-r21-warm`
and `commenter-r21-engineer` carry the round-21 discipline block **byte-identical** (verified equal md5
to `commenter-r21-elon`), differing only in `## The personality` + the `RateLimiter` exemplar. They
reuse round-21's existing 4 ledgers (no re-triage) and write into `round-21/runs/{warm,engineer}/` so
the output sits beside the keepers.

- Files: `timing/ticks.py` + `mqtt/client.py`. 2 runs. 8 writer dispatches, no triage phase.
- Workflow: `round-21/round-21b-workflow.js`. Dispatch brief: `round-21/RUN-21b.md`.
- Verify after run: 8 files under `runs/warm` + `runs/engineer`.
- Question it answers: are warm/engineer worth saving alongside elon/foreman/linus/pewdiepie, or did the
  bake-off voices fully replace them? Judge on the same axis (voice quality, AI-tic drift, run-ons),
  and specifically whether the generic-persona drift the user flagged on `mayo` also afflicts these two.

### Round 21.b result

Both accurate; both recovered the two non-derivable `MQTTClient.__init__` nuances (ping = half
keep-alive floored at 1s -> 30s default; tx-deque sized 64 over `max_tx_queue_size` so PUBACK/PINGREQ
bypass the user cap). The decisive split was the mayo drift.

- **warm — worth saving.** Distinct warm voice, held the discipline, and did NOT drift: documented
  `ack_timeout_seconds` as *"How long to wait for any ack before failing"* with no internal-storage
  leak, and kept `_new_tx_queue` runtime-agnostic (*"the runtimes that support it"*). Overlaps foreman
  (both friendly); warm is "experienced-dev notes," foreman "folksy enthusiast" - user may keep both or
  pick one.
- **engineer — marginal as a standalone.** Complete and precise, but showed the mild form of the mayo
  tic: on `ack_timeout_seconds`, *"...overdue; stored internally as milliseconds"* (internal-storage
  leak warm omitted), plus it named CircuitPython/MicroPython/CPython in `_new_tx_queue` (brushes the
  "every comment stands alone" rule) and a *"twice a fortnight"* flourish on ticks. As a standalone it
  overlaps elon (better minimalist) and the cut dexter (verbose-complete). Its value is likely as a
  hybrid backbone - defer the keep/cut to the 21h read.
- **Cross-cutting fix for round 22:** run-1 module-docstring drop has now hit linus, charlie, AND warm
  (all recovered in run-2). Add one line to the discipline block - "every module file opens with a
  module docstring" - to close the only recurring reliability defect before round 22. (Recommended, not
  yet applied; a hard rule could over-fire on trivial files - user's call for round 22.)

### Discipline-block fix APPLIED — docstring body placement (user-caught)

The user caught warm/engineer parking the non-derivable-nuance body as a trailing paragraph AFTER
`Raises:` on `MQTTClient.__init__`. Root cause: the block said "add a body for nuance" but never said
where, and no exemplar showed a symbol with both a body and `Args:`, so every voice put it at the
bottom. Wrong; the body is the extended description and belongs directly under the summary, before
`Args:` (order: summary, body, `Args:`, `Returns:`, `Raises:`). Fixed in all 10 round-22-bound agents
(elon, foreman, linus, pewdiepie, warm, engineer + 4 hybrids): added a placement rule to `## Format`
and `## A body...`, plus a structural skeleton showing body-then-Args. Block re-verified uniform
(md5 `0f275805...`), 0 em-dashes. Memory: `[[docstring-body-placement]]`.

IMPORTANT for the 21h read: 21h ran with the OLD block (agents loaded before this fix), so its outputs
still carry body-after-sections. That placement bug is present equally in all four hybrids and is fixed
for round 22 - ignore it when judging 21h; judge voice only. Same caveat applies to the already-run
round-21 keepers and 21.b outputs.

## Round 21h — hybrid voices, the 2x2 grid (built, ready)

The user wants to try fused personas before round 22, since a hybrid winner changes round 22's roster.
A hybrid splits into a **backbone** (code-reading instincts: depth, traps, completeness) and a **skin**
(register). Built as a full 2x2: backbones {`engineer`, `linus`} x skins {`pewdiepie`, `foreman`}.

- Agents: `commenter-r21h-{linus-pewdiepie, linus-foreman, engineer-pewdiepie, engineer-foreman}`.
  Discipline block byte-identical to the keepers (verified equal md5 to `commenter-r21-elon`); only the
  fused `## The personality` + exemplar differ. The linus-backbone exemplars keep linus's trap-flagging
  ("a no now can be a yes", "crank it too high and you've killed the limit"); the engineer-backbone
  exemplars stay terse-and-complete. The skin sets register (pewdiepie second-person casual; foreman
  folksy plain-spoken).
- Reuses round-21's 4 ledgers (no re-triage). ticks.py + client.py, 2 runs. 16 writer dispatches.
- Workflow: `round-21/round-21h-workflow.js`. Brief: `round-21/RUN-21h.md`. Outputs in
  `round-21/runs/{linus-pewdiepie,linus-foreman,engineer-pewdiepie,engineer-foreman}/`.
- The grid gives two controlled reads. Down a skin column (fix pewdiepie, compare linus vs engineer
  backbone) answers **which voice reads code better**. Across a backbone row (fix linus, compare
  pewdiepie vs foreman skin) answers **which register carries it best**. Watch whether a hybrid keeps
  linus's depth (the `ProtocolState` state-machine recovery) without inheriting its module-docstring
  drop, and whether the casual/folksy skin stays technical and legible.

### Round 21h verdict (user) — persona work parked

The user judged the hybrids done: a good try to revisit later, not now. Engineer-backbone mashups did
NOT work; linus-backbone was better; intuition for next time is `pewdiepie x elon`. Decision: stop
persona iteration after round 22. The 4 hybrid agents stay on disk for a future revisit.

### Voice set: elon, foreman, linus, pewdiepie, warm (the 5 that RAN round 22)

`engineer` dropped ("basically a bad elon" - it also showed the mild mayo leak in 21.b). `warm` added
(held the discipline in 21.b, dodged the drift). `dexter`/`mayo`/`charlie`/`attenborough` already cut.

### Voice set churn, then settled: elon, foreman, linus, pewdiepie

The user briefly dropped `linus` and `warm`, then RESTORED `linus` after seeing it out-document elon on
`ProtocolState` (state-machine narration linus volunteered and elon suppressed). `warm` stays dropped.
Settled set: elon (terse minimalist), foreman (folksy energetic), linus (blunt, high-disposition depth),
pewdiepie (casual energetic). linus is kept specifically for its natural depth-disposition, accepting its
voice warts (the "the"-opener tic, blunter register) because its substance leads.

### Guiding principle (user, post-round-22): natural disposition beats bolt-on rules

The user's standing direction for this work: prefer a voice that does the right thing NATURALLY over a
minimalist voice patched with a rule telling it where to expand. Every "expand here / don't expand there"
rule is a treadmill - you add one per gap forever. Keep the discipline subtle; let the personality carry
the judgment. This reframes the depth-ceiling finding: rather than raise elon's ceiling with per-gap rules,
keep a high-disposition voice (linus) in the set and point it at depth-heavy files. Memory:
`[[natural-disposition-over-rules]]`.

RESOLVED: the enum/state-narration rule was REVERTED (user confirmed). linus is kept and owns state-heavy
files naturally. All current voices use the subtle block, no expand/don't-expand bolt-ons. See round 23
below for the rule-count-flat swap that followed.

### Built: linus x elon hybrid + round 23 (tonal nudge A/B)

The user reversed the defer: "we need some kind of elon linus hybrid." Built `commenter-r21h-linus-elon`
on the WHAT/HOW split that explains why elon reads better than linus despite its ruthless cut. The two
differ on two axes - WHAT to include (linus volunteers traps/transitions; elon keeps the minimum) and HOW
to phrase (linus explains, piling clauses/semicolons/"the X is"; elon writes short declarative bursts on
strong verb+noun). elon wins HOW (the cut IS the readability); linus wins WHAT (depth). The hybrid takes
linus's WHAT + elon's HOW: "the maintainer decides what is worth saying, the minimalist decides how few
words say it." Block identical to the voices; its personality bans semicolons and "the X is" openers.

Then a net-flat rule swap (user: "natural disposition, we may be over-ruleing"): added one subtle nudge
to the shared block and DROPPED rule 4 in trade, so the bullet count held at 5. New nudge: *"Let the
writing breathe: vary how lines open and how they are built... lean on a precise verb and a concrete noun
rather than propping a line with `the` or opening on `That's`. Cut or recast where cleaner. Keep it light:
structural variety, not synonym-hunting, never a forced tic."* It subsumes rule 4's `That's`/`The`-opener
flag more constructively and adds tone variability. All 5 agents (4 voices + hybrid) now share block md5
`59d8ef2c...`, 0 em-dashes.

Round 23 (RAN): `round-23/round-23-workflow.js` + `RUN.md`. 5 agents on `mqtt/client.py` +
`timing/ticks.py`, reusing round-22 run-1 ledgers; 10 writer dispatches, no triage. Two reads:
(1) nudge A/B - round-23's 4 voices vs round-22 (more tonal variety, less `the`, no harm?) - still to
analyze; (2) the linus-elon hybrid - FAILED.

### linus-elon hybrid FAILED, rebuilt as linus-tight for round 24

The round-23 `linus-elon` hybrid collapsed into elon and lost linus's depth: it documented `ProtocolState`
by just counting states (elon-level, none of linus's transition semantics) and added banned ownership
trivia ("The client owns..."). Cause: it was written as a WHAT/HOW framework (two instincts in tension),
and elon's forceful "delete by default" dominated, suppressing linus's "volunteer the trap." The skin ate
the backbone. Memory: `[[build-hybrid-persona-as-one-character]]`.

Rebuilt as `commenter-r21h-linus-tight`, linus-first: linus's depth-hunting is the whole identity ("that
instinct is the whole of you, and it never yields"); compression is "a discipline laid over the instinct,
never a brake on it." One character, depth as the core, brevity layered on. Block identical to the voices
(md5 `59d8ef2c...`), 0 em-dashes, 0 semicolons. Old `commenter-r21h-linus-elon` left on disk as the
round-23 artifact's source, superseded. `commenter-r21-linus` kept unchanged (doing well).

Round 24 (BUILT): `round-24/round-24-workflow.js` + `RUN.md`. ONLY the rebuilt hybrid, on the files that
stress depth and tightness: `mqtt/client.py` (the ProtocolState collapse site), `kvstore/_backends/cp_nvm.py`
(the OverflowError trap linus surfaced), `timing/ticks.py` (baseline). Reuses round-22 run-1 ledgers; 3
writer dispatches, no triage. The read: did it keep linus's depth (narrate ProtocolState, surface the trap)
while writing tighter than linus (no "the X is" openers, no semicolons, no clause-piles)?

### Round 24 result + linus-tight v2 (round 24b, BUILT)

v1 succeeded at the core job and failed on one fault. Depth recovered: `ProtocolState` got the full state
machine (rest state, each state's meaning, the FAILED self-heal CONDITION) richer than linus's round-22,
and cp_nvm carried the 65535 cap. Tight on the small files. User likes the voice. BUT on `client.py` it
leaked ~25 semicolons into dense `Args:` prose (stripped code has only 3) - linus's semicolon reflex
recurred under the pressure of a 24-arg constructor. Root cause = our own core-wins lesson: depth was the
core and compression a layered discipline, so the linus-core's semicolon habit beat the no-semicolon
discipline on dense content. (Depth-vs-no-semicolon do NOT conflict on content, unlike depth-vs-minimalism,
so the fix is safe.)

v2 fix (applied, block unchanged `59d8ef2c...`, 0 em-dashes/semicolons): folded "short, clipped sentences,
never a semicolon" INTO the core identity ("that is how you talk, not a rule you obey"), co-equal with the
trap-hunting, since the two govern different things (form vs content). Guarded hard against the user's
stated risk that elevating short-sentences could license "opening up" into AI-tics / generic "the X":
"Splitting is repunctuation, not permission to add a word... never a third sentence you did not need,
never a new opener like 'the X is' or 'That's'... Short does not mean less said."

Round 24b (BUILT) - turned into an A/B after the user flagged the v2 personality as over-ruled: "im
partly worried the personality is over-ruled... last time rules were put into the personality block it
backfired." Correct - the v2 fix added 5 prohibitions to the personality (never a semicolon / long line /
third sentence / "the X is" opener / qualifier) and even wrote "not a rule you obey" amid the rule list,
the same rule-stuffing that sank the first hybrid. So round 24b runs two variants head-to-head on the same
3 files:
- `commenter-r21h-linus-tight` (rule-heavy v2, 5 prohibitions in the personality).
- `commenter-r21h-linus-tight-lean` (0 prohibitions: clipped prose from character only - "thinks in
  short sentences, distrusts the semicolon as a crutch"; restraint from "say it then stop / waste
  nothing"; the no-`the`/no-`That's` guidance left to the shared block's nudge, not duplicated).
Both block md5 `59d8ef2c...`, 0 em-dashes. Workflow `round-24b/round-24b-workflow.js` + `RUN.md`, writes to
`round-24b/runs/<variant>/` (round-24 v1 preserved as baseline). 6 dispatches.

The hypothesis under test: if lean (no explicit guards) stays clean, the rules were clutter and
over-ruling is confirmed; if lean drifts into semicolons / AI-tics / "the X" / padding, the rules were
load-bearing. DEEP-EVAL (user: "evaluate what happens pretty deeply") - read line-by-line, not by counts:
(1) semicolons in client.py Args toward the baseline of 3; (2) depth held (ProtocolState + cp_nvm);
(3) no AI-tics / "the X" / "That's" / padding / drift-to-less in EITHER variant.

### Round 24b result — over-ruling CONFIRMED, lean wins

v2 (5 prohibitions in the personality) and lean (0, character-only) came out indistinguishable on every
axis: client.py semicolons 13 vs 12 (v1 was 30), AI-tics 0/0, ProtocolState fully narrated in both (lean's
self-heal condition slightly MORE complete), `__init__` nuances + cp_nvm 65535 trap held in both, and v1's
Args-semicolon leak fixed in both (Args now period-split). The 5 prohibitions bought nothing over lean's
one character line ("thinks in short sentences, distrusts the semicolon as a crutch"). The user's drift
worry did not materialize: lean stayed clean without the guards. So the rule-pile was clutter - decisive
confirmation of `[[natural-disposition-over-rules]]`.

DECISION: lean is the keeper. Promote `commenter-r21h-linus-tight-lean` to be the linus-tight hybrid;
retire the rule-heavy v2. (Pending user confirm at time of writing.)

RESIDUAL (both variants, not a rule problem): ~12 method-body semicolons survive, joining two related
clauses ("encoded UTF-8; a bytes payload is copied"). The Args leak moved to method bodies. v2 PROVES more
rules will not fix it (it had the prohibition and still did it ~12 times). Lever, if we care: a light
exemplar showing a two-clause method body split with a period - never another prohibition. Or accept it
(readable). Minor.

### Round 25 — lean exemplar micro-variants A/B/C/D (BUILT). Promotion DEFERRED.

User: "we need to a/b/c/d this. no promotion yet until we have results from a couple angles." Chose the
exemplar-micro-variant framing (isolate which exemplar change helps), same 3 files. Four arms differ ONLY
in the exemplar (block md5 `59d8ef2c` + personality md5 `da839e63` byte-identical across all four; verified):
- `A-lean` = `commenter-r21h-linus-tight-lean` (baseline, no fix).
- `B-opener` = `commenter-r21h-lean-opener` (exemplar `__init__` gains a body opening on a plain subject,
  "A capacity under 1...", to teach the generic body opener and kill the "the `<param>`" slip).
- `C-semicolon` = `commenter-r21h-lean-semicolon` (exemplar closing adds a before/after: two facts are two
  sentences, never one semicolon).
- `D-both` = `commenter-r21h-lean-both`.

Two craft findings drove this (both via `add_pattern_handler`, lean vs rule-heavy): lean wrote the better
docstring overall (richer grounded depth, cleaner summary) but (1) reached past the file for a domain
detail ("`+`/`#` wildcards" - matching lives in `_topic_levels_match`, not this method; strong MQTT
inference like the accepted "3.1.1", but the spot where over-reach hides), and (2) opened its body "The
pattern is split..." - a false-definite forward ref, since `pattern` is defined in `Args:` below, not
above. The "the `<param>`" rule is now memory (`[[docstring-body-no-the-param]]`).

Workflow `round-25/round-25-workflow.js` + `RUN.md`, writes to `round-25/runs/<arm>/`. 12 dispatches, no
triage. Read: which arm's exemplar (if any) removes the "the `<param>`" body opener and trims the
method-body semicolons, with no new harm - and whether B/C/D beat A enough to fold a fix into the keeper.
Only THEN promote.

### Round 25 result + PIVOT to adjusting original linus

Result: the exemplar fixes ERODED depth on the lean base, dose-response. ProtocolState narration: A-lean
full, C-semicolon full, B-opener thinned, D-both COLLAPSED to one line. The more exemplar form-guidance
added, the more the depth disposition gave way - even exemplar-level brevity guidance suppresses depth on
the already-compressed lean base. (Caveat: n=1 per arm, ProtocolState narration is partly probabilistic.)

User's call: likes D's voice, but the comparison used the wrong base. PIVOT - stop refining the
elon-derived hybrid (lean/tight descend from linus x elon); **adjust ORIGINAL linus** (`commenter-r21-linus`,
the no-elon voice already kept for its depth) instead of inventing a new voice. Bet: linus's depth is more
robustly core, so the same fixes should keep the ProtocolState mapping lean-D lost. `commenter-r21-linus`
stays the depth north star; the lean/tight hybrid line is effectively parked.

### Round 26 — adjust linus, exemplar-fix vs rules (BUILT)

User chose A/B exemplar-vs-rules, linus base only. Three arms, each changing exactly ONE thing vs original
linus (verified: block `59d8ef2c` uniform; `linus` == `linus-exemplar` personality `45b476f9`; `linus` ==
`linus-rules` exemplar `309daac7`):
- `linus` = `commenter-r21-linus` (control).
- `linus-exemplar` = `commenter-r21-linus-exemplar` (ONLY the exemplar changes: its 2 semicolons split into
  sentences, plus a generic body-opener instance "A capacity below 1...". Fix SHOWN.)
- `linus-rules` = `commenter-r21-linus-rules` (ONLY the personality gains two light rules: short sentences /
  no semicolon, and body opens on a plain subject not "the <param>". Exemplar UNCHANGED, still models 2
  semicolons - so this tests whether a rule overrides the habit its own exemplar shows. Fix TOLD.)

Files: client.py + cp_nvm + ticks. Workflow `round-26/round-26-workflow.js` + `RUN.md`. 9 dispatches, no
triage. Read: (1) does linus-base keep ProtocolState depth where lean-D lost it; (2) exemplar-fix vs
rule-fix on the residuals (predict exemplar wins, and linus-rules still semicolons because its exemplar
models them); (3) any new harm. This decides whether "adjusted linus" replaces the lean hybrid as the
keeper.

### Round 26 result — prediction WRONG, rules beat the exemplar; linus-rules is the candidate keeper

client.py semicolons (code=3): control linus 28, linus-exemplar 30 (NO help), linus-rules 10 (~25 prose ->
~7). The clean exemplar did not dislodge linus's baked-in semicolon habit; the two light RULES did. 0
AI-tics in all three; linus-rules body openers all plain (the "plain subject" rule held). This REVISES
`[[natural-disposition-over-rules]]`: a rule is clutter only when it restates an existing disposition; a
TARGETED rule for a specific mechanical habit the persona strongly exhibits (linus's semicolons) can
outperform a sparse clean exemplar that cannot overpower the habit on a dense file. (Reconciles with 24b:
the no-semicolon rule did nothing on lean because lean had no semicolon habit to curb.)

Depth: INCONCLUSIVE at n=1. linus-exemplar collapsed ProtocolState but nailed the cp_nvm OverflowError
trap; linus-rules nailed ProtocolState but was thinner on cp_nvm's class doc. No clean arm effect - run
noise. So no depth-erosion claim from this (and round-25's lean depth read was likely noisier than stated).

Candidate keeper: **`commenter-r21-linus-rules`** (original linus + two light targeted rules) - keeps
voice + depth, curbs the semicolon tic, 0 AI-tics. Vindicates the user's "adjust linus with rules" call.
NEXT, before promotion: re-run `linus-rules` + control 2-3x to confirm the semicolon drop holds and depth
stays reliable across runs (n=1 + noisy depth). Only then promote linus-rules as the keeper over the
parked lean hybrid.

### Round 27 — strict no-"The"-opener rule on linus (BUILT)

User's read, both verified against round-26 artifacts: (1) original linus is the strongest voice; its one
real flaw is opening sentences on "The" (~20 in client.py, untouched by EVERY arm so far - linus-rules
still ~18). (2) regular linus's semicolons are not that bad overall; the win in linus-rules was better
Args descriptions, and semicolons cluster in Args (12 of linus's 28 are Args-line semicolons, driven by
length). Hypothesis: a hard, no-exceptions "never open a sentence with The" rule fixes the flaw and may
shift phrasing more broadly.

Expanded to a POSITIVE-vs-NEGATIVE framing bake-off (user: "should we try a negative set to see which
wins?" - we'd been assuming positive framing beats negative; test it). FIVE arms, each changing ONLY
linus's personality (block `59d8ef2c` + exemplar `309daac7` identical to `commenter-r21-linus`; 0 em-dashes):
- `linus` = control.
- `linus-strict` (POS) = "You open every sentence on a verb or a concrete noun, never on 'The'."
- `linus-strict-neg` (NEG) = "You never open a sentence on 'The'." (same content, prohibition framing)
- `linus-strict-nosemi` (POS) = the POS no-"The" + "You write in short, concise sentences explaining one
  concrete item."
- `linus-strict-nosemi-neg` (NEG) = the NEG no-"The" + "You never join two facts with a semicolon, and you
  never let a sentence run long."
B-vs-C isolates framing on the opener; D-vs-E on both traits.

Craft note (user, refined twice): persona traits are POSITIVE IDENTITY - state what the persona DOES
("You open on a verb or a concrete noun", "You write... one concrete item"), not a prohibition with
meta-justification ("One rule: never X. This matters most in Y, where..."). Lead with the habit, not the
ban; keep a tight boundary clause ("never on 'The'") only to stay strict. The persona should just BE the
trait.

Files: client.py + cp_nvm + ticks. Workflow `round-27/round-27-workflow.js` + `RUN.md`. 15 dispatches
(5 arms x 3 files), no triage. Read: (1) does either framing drive "The" openers toward zero; (2)
**positive vs negative - which wins** (cleaner phrasing, broader behavior shift, fewer awkward contortions);
(3) does the +concise/no-semicolon trait tighten Args without new harm; (4) depth and AI-tics hold.
Candidate keeper is now "original linus + one or two POSITIVE identity traits" (or negative, if it wins),
displacing both lean-hybrid and linus-rules if it lands.

### Round 27 result — POSITIVE framing wins; then the metrics-vs-substance reckoning

Positive beat negative: positive arms hit 0 summary-"The" openers; the negative-STACKED arm
(`nosemi-neg`) hit 4 (worse than control) - piling prohibitions backfired (over-ruling again). The concise
trait crushed semicolons (POS 3, NEG 8, vs 34-46 without). `linus-strict-nosemi` (POS both) looked best on
every surface metric: 0 summary-"The", ~0 semicolons, full ProtocolState, 0 AI-tics, flowing not choppy.

THEN the user read the actual content and found two things the metrics never measured:
- **Accuracy:** `linus-strict-nosemi` wrote "Pass both to get self-heal" - WRONG. Self-heal is gated on
  the `connector_factory` alone (code line 529 + `_attempt_self_heal`); a factory enables it with or
  without an initial socket. A confident mis-trace of a cross-method fact.
- **Word soup:** its `__init__` body crammed 4 per-param nuances (self-heal, tx-queue +64, ping, send
  timeout) into one wall - each is "one concrete item per sentence" so it passed every tic check, but
  reads as a dump. Cause: per-param nuance dumped in the shared body instead of riding in each `Args:` entry.

RECKONING (the key lesson): every metric we optimized for rounds (no-"The", semicolons, depth-present,
framing) is SURFACE. The two things that actually disqualify a docstring - accuracy of recovered nuance
and word-soup density - are not measured by any of them, and are NOT controlled by persona style. Re-reading
round-24 `linus-tight`: it got self-heal RIGHT ("a factory is required for the self-heal path; supplying
both uses the socket now and the factory later") and had RICHER per-param `Args:` - but we moved past it
chasing its ~30 semicolons + a hybrid-vs-original-linus purity pivot, both surface. We over-optimized the
measurable and regressed on substance. Memory: `[[metrics-are-surface-accuracy-is-the-gate]]` (to record).

### Round 28 — the mix (BUILT) + triage upgrade (QUEUED)

Mix test (user: "can't we mix 24 with the 27 updates before moving on?"): `commenter-r21h-linus-tight-pos`
= the linus-tight HYBRID's depth-para + exemplar (round-24's persona, the substance source) with round-27's
two POSITIVE traits swapped in for its old rule-pile. Block `59d8ef2c`, 0 em-dashes, exemplar clean. Round
28 runs it vs `linus-strict-nosemi` (round-27 winner) on the 3 files (`round-28/round-28-workflow.js` +
`RUN.md`, 6 outputs). Tests whether the hybrid's depth-framing keeps round-24's rich+accurate Args while
the positive traits clean the surface. NOTE: self-heal accuracy is run-variable, not persona-controlled -
the mix tests Args RICHNESS + surface, not accuracy.

### Round 28 result — mix did NOT win; linus-strict-nosemi holds; hybrid line parked for good

Read all 6 outputs in full against the stripped code. The mix (`linus-tight-pos`) lost to the round-27
winner (`linus-strict-nosemi`) on balance.

- **Accuracy (real gate 1) — tie, reckoning CONFIRMED.** Both arms got self-heal RIGHT this run.
  `linus-strict-nosemi` wrote `connector_factory: "...used for self-heal reconnect even when a socket was
  passed"` and `handle()`: "From FAILED with a factory and a user still wanting connection, attempts
  self-heal." No "pass both" error. SAME persona + SAME file as round 27, opposite result - the cleanest
  proof that accuracy is run-variable, not persona-controlled.
- **Word-soup (real gate 2) — neither reproduced it.** Round-27's 4-nuance `__init__` wall did not recur
  in either arm. Also a run artifact, not a trait.
- **Surface — nosemi clearly cleaner.** The mix let linus's semicolon reflex back into dense Args
  (`root_topic`, `clean_session`, `will_topic`, `send_timeout_seconds` each on a semicolon; `publish`
  body runs long). nosemi period-splits throughout. EXACTLY round-24's finding repeating: the hybrid
  depth-para drags the semicolon habit back on dense content, and the positive "one concrete item per
  sentence" trait did not suppress it under the 24-arg constructor.
- **Args richness — leans nosemi, OPPOSITE the hypothesis.** We expected the hybrid to give richer Args;
  nosemi actually traced MORE (from_config config keys + defaults, `max_message_bytes`->`when_oversized`
  link, the connector_factory "even when a socket was passed" nuance). The mix's depth showed up in only
  two narrow places: `ProtocolState` per-state narration (richer - names what each state does) and cp_nvm
  `Raises` completeness (listed `OverflowError`/`RuntimeError` where nosemi only prosed them). Real but
  narrow, bundled with the semicolon regression.

DECISION: `linus-strict-nosemi` (original linus + the two positive traits) is the better all-around
keeper. Park the hybrid line for good. Its one genuine edge (per-state class narration) IS the
depth-disposition lever - and the reliable way to get that is the triage upgrade below, not the persona.
This closes persona iteration: the keeper voice is settled.

### Triage upgrade — the accuracy + depth lever (QUEUED, user-specified, spec next)

The accuracy gap is NOT a persona problem. Source comments are
suspect, so triage must read the CODE as truth and TRACE cross-method facts (self-heal gate, tx-queue
reservation), ADDING what it finds rather than lifting comments; emit in tight prose (persona-matched);
flag uncertainty. KEY: both triage AND the writer independently attempt the hard facts (defense in depth) -
neither finds them reliably alone, but if either catches it, it lands. This is the real lever for accuracy.

### Round 29 — triage upgrade BUILT (tracing triage vs lean triage, keeper writer held constant)

Built `commenter-r29-triage-trace` (forked from `commenter-r20-triage-lean`). Stance change: code is the
ONLY truth, existing comments are suspect hints to verify against the code (never lifted), and a
comment that contradicts the code is recorded as a finding. Emits two fact classes: (1) the old
non-derivable nuance (computed magnitudes, thresholds, edges, surprising effects, valid-only-when), and
(2) the headline NEW class - traced CROSS-METHOD facts, each as **assertion + verify-site (`method() Lnn
-> other()`) + confidence (high/medium/low)**. May follow one call into a sibling file only when an
asserted fact depends on it. The assertion+site form is the user's pick (fork: pointers / assertions+conf
/ both-with-site) - it hands the writer the depth AND a checkable site so a wrong assertion can't spread
unchallenged. Triage stays neutral plain prose, not persona voice (writer rewrites and is told not to
copy ledger lines). 0 em-dashes verified.

Design tension surfaced + resolved: defense-in-depth catches OMISSIONS cleanly (one finds what the other
misses), but a confidently-WRONG triage assertion could pollute an otherwise-correct writer. Mitigation
baked into the round-29 writer PROMPT (not the keeper persona, which stays isolated): "high-confidence =
confirm at the named site before writing; medium/low = a lead to verify; on any ledger-vs-code conflict
the code wins; never copy a line." The keeper writer already traces independently and is told never to
invent, so the site + confidence + code-wins rule is the guard.

Test design REVISED (user, supersedes the round-28 "keep nosemi" rec): round 29 is now a 3-WRITER
BAKE-OFF on the upgraded triage, not a triage A/B. One tracing-triage runs per file; its ledger feeds all
three depth-writer variants. Pipelined per file: trace-triage the with-comments round-22 input -> 3 writers
in parallel, each reading the round-22 STRIPPED code + the same traced ledger. The variable is the writer
personality. 3 triage + 9 writer dispatches; 3 ledgers + 9 outputs (`runs/{linus-tight,linus-tight-lean,
linus-tight-pos}/`). The old-lean-vs-new-trage triage A/B is dropped; we trust the upgraded triage and
compare the three writers on it. nosemi is not in round 29.

WRITER BASELINE + the v1/v2 recovery (user-driven, IMPORTANT): the baseline persona is
`commenter-r21h-linus-tight` restored to its **v1** personality - the version that actually RAN in round 24
and produced the output the user admired ("You spend your words on the trap... that instinct is the whole
of you... You also write lean, a discipline laid over the instinct"). It had drifted on disk to the v2
rule-fold ("that is how you talk, not a rule you obey", 5 prohibitions) applied in round 24b. The user
pasted v1 believing it matched disk; reading the body (not just frontmatter) showed disk was still v2 and
the v1 paste had landed CORRUPTED (terminal line-wrap baked in: "acates" for truncates, "# f:" for
"# ruff:", dropped phrases) in the `-lean` file under a duplicate name. Recovery: reconstructed clean v1
(mechanical de-wrap; one dropped phrase matched from v2), wrote it to the baseline + rebased `-pos` para-1
to v1; the user concurrently restored `-lean` to a clean round-24b variant. The three children:
`linus-tight` (v1 depth + compression-discipline para), `linus-tight-lean` (depth + character-only
restraint, 0 prohibitions), `linus-tight-pos` (v1 depth + round-27 positive traits). Lineage confirmed by
user: round-24 `linus-tight` is the parent; lean (24b) and pos (28) are its two direct children. Exemplar
held byte-identical (clean period version) across all three; v1's semicolon exemplar-closing NOT
reintroduced (would have a no-semicolon persona model semicolons).

RESOLVED (lean rebased onto v1): the three are now clean siblings. `diff` of `linus-tight` vs
`linus-tight-lean` shows ONLY name, description, H1, and the restraint para differ; para-1 (v1 depth), the
"Blunt, technical, correct, and tight" closer, the full exemplar, and the discipline block are
byte-identical. Same holds vs `linus-tight-pos`. So round 29 varies ONLY the restraint treatment:
- `linus-tight` para-2: compression-as-discipline ("You also write lean, a discipline laid over the
  instinct... short declarative sentences... do not open on 'the X is', do not chain... semicolon, do not
  pad with qualifiers"). The v1 prohibition-style restraint.
- `linus-tight-lean` para-2: character-only ("You think in short, clipped sentences, and you distrust the
  semicolon as a crutch for two thoughts that should be two sentences"). 0 prohibitions.
- `linus-tight-pos` para-2: round-27 positive identity ("You open every sentence on a verb or a concrete
  noun, never on 'The'. You write in short, concise sentences explaining one concrete item").
All three: 0 em-dashes, v1 depth-para, shared block + exemplar. Round 29 ready.

TRIAGE SELF-CHECK FIX (user-caught, applied to `commenter-r29-triage-trace` before dispatch): the old
lean triage fed "ping interval = half keep_alive floored at 1s -> 30s default" as nuance, and the round-28
writers turned it into a clunky derivable body line ("The ping interval is half of keep_alive_seconds..."
- also a no-"The" violation in `linus-tight-pos`). But `max(1000, keep_alive*1000//2)` shows "half, floored
at 1s" on its face and half of 60 is 30: it is DERIVABLE, not nuance. Two edits to the triage: (1) a sharper
fact-class-1 rule killing arithmetic restatements ("X is half/double/sum/default-N of Y"); a computed
magnitude survives only when its SCALE is non-obvious (1<<29 ms = 6.2 days yes; 60/2 = 30 no); (2) a new
"check your own work" pass: re-read every drafted fact and cut any the writer could get from the code alone,
under-emit on doubt. 0 em-dashes re-verified.

TRIAGE FIX #2 (round 29 RAN, user caught two defects in the client.py ledger): (a) the ping-floor fact came
back ANYWAY ("`max(1000, keep_alive*1000//2)` floors at 1000 ms, so keep_alive <= 2 still pings every 1 s",
confidence:high) - my fix #1 only caught "X is half of Y" arithmetic; this dressed as a THRESHOLD and slipped
through. (b) WORSE: the triage stated facts as finished prose sentences, so the writer lifted the noun and
front-loaded it ("The ping interval is floored at 1000 ms, so any keep_alive_seconds of 2 or less still pings
once a second") - the exact phrasing the pipeline tries to kill. The old lean triage used telegraphic STUBS
precisely so nothing was paste-able; my assertion+verify+confidence format regressed that to prose. Fix:
(a) visible-guard cut rule - a threshold bounded by `max`/`min`/clamp/literal comparison is derivable (reader
sees the bound), ping floor named as the recurring offender, cut it; a non-guard implicit cap like
`to_bytes(2)` overflow at 65535 still survives. (b) stub-form for ALL lines incl. traced facts ("the writer
must not be able to paste your line"; pin the condition as a fragment, not a sentence) + a paste-check in the
self-review. Example in the agent converted to stubs. 0 em-dashes. NOTE the rest of the round-29 ledger was
GOOD (self-heal gate, tx +64 reserve, clean-session wipe, two-knob keepalive all correct) - the triage has
real value, it had an over-capture gap + a prose-leak, both now fixed.

CONSEQUENCE: round 29 ran with the pre-fix triage, so its ledgers carry the ping-floor + prose form and its
outputs carry the lifted "The ping interval" sentence. Round 29 should be RE-RUN (triage + writers) with the
fixed `commenter-r29-triage-trace` for a clean read. Round 30 (no triage) is unaffected by this fix.

TRIAGE FIX #3 - STRUCTURAL REDESIGN (user: "are you sure this triage agent is written right?"). No. Two
deeper defects the incremental patches above could not fix:
1. CONTAMINATED EXAMPLES. The agent illustrated its rules with the ACTUAL code under test - `max(1000,
   keep_alive*1000//2)`, the self-heal gate, the tx `+64` reserve, `1<<29`=6.2 days, the 65535 cap, the
   clean-session wipe. That handed the triage the exact facts it is supposed to TRACE, so round 29 was not
   testing tracing ability, it was testing whether the model copies its own instructions. Violates
   `[[agent-examples-must-be-neutral]]`. (Author error, mine.)
2. SELF-CONTRADICTION drove the ping-floor failure. Fact class 1's bullet "keep a threshold where behavior
   changes" INVITED the ping floor (keep_alive <= 2 changes ping behavior); lines 35/37 then said cut it.
   Keep-and-cut in one breath; the model followed the invitation and stamped confidence:high. Piling on
   more cut-rules was the SAME over-ruling that backfires on personas.
REDESIGN: the triage is now CROSS-METHOD-ONLY. One principle: "emit a fact only if establishing it required
reading more than one method (or a sibling call); name both sites, else it is the writer's job." Fact class
1 (single-method nuance: magnitudes, guard thresholds, edges) is DELETED - it was the entire over-capture
source AND the writer recovers it from the one expression (round 20; round 30 confirms). The ping floor is
now unrepresentable (one expression in `__init__`), no cut-rule needed. All examples neutral
(pool/cache/backoff), verified 0 code-under-test identifiers, 0 em-dashes. Same agent name, so round 29's
workflow is unchanged.

This also makes round 29-vs-30 a CLEANER test: cross-method-ledger vs no-ledger isolates exactly "does
cross-method tracing help," with no single-method-nuance noise. On the round-29 re-run, the ledger should
carry ONLY cross-method facts (self-heal gate, tx `+64` reserve, clean-session wipe, two-knob keepalive,
each with two verify sites) and ZERO single-method facts (no ping floor, no bare 65535, no wrap magnitude) -
that absence is the signal the redesign worked. Supersedes the criterion-1 "ping-half should be gone"
phrasing: now NO single-method line should appear at all.

### WRITER BLOCK FIX - the ping floor is WRITER-side, not triage-side (round 29 re-ran, user caught it)

Round 29 re-ran with the intermediate (visible-guard-cut) triage. The ledger DID drop the ping floor.
But ALL THREE writers regenerated it anyway from the code: linus-tight "The ping interval is floored at
1000 ms, so any keep_alive_seconds of 2 or less still pings once a second"; lean and pos the same.
**pos opened on "The ping interval" despite its explicit "never open on The" trait** - a stated trait is
not reliably obeyed (another metrics-are-surface data point). So the floor is a WRITER behavior, present
with or without triage; round 30 (no triage) would show it too.

Mechanism: same keep/cut contradiction as the triage, now in the WRITER's shared block. "Trace the code...
a constant has a human-scale size you'd have to compute... state the human-scale figure" INVITES the floor;
"a body only for non-derivable nuance" should forbid it; invitation won.

The decisive user reframe (better than "derivable" or "edge case"): the genuinely useful comment here is
GUIDANCE or INTENT ("use keepalive >= 60s", "the floor stops a misconfig hammering the broker") - which the
agent cannot derive from this file and must not invent. The mechanical restatement ("floor bites at
keep_alive <= 2") is the BOOBY PRIZE the writer reaches for because it lacks the context for the real thing.
Correct move: write NOTHING. This is a knowledge-boundary check the agent can self-run ("am I saying the
useful thing, or restating mechanism because I lack the context for the useful thing?"), tied to the
existing never-invent + body-only-for-nuance rules, not a fourth taste-rule. It also lines up with the
round-20 decision to park intent/rationale/guidance for the human-in-the-loop pass: the agent writes what
it can trace and stays silent where value lives in context it does not have.

FIX APPLIED to the shared writer block (all 3 writers, byte-identical, 0 em-dashes, block parity
re-verified): one paragraph appended to "## A body earns its place..." - "When the only thing worth saying
would be guidance or intent you cannot derive from this file... do not substitute a restatement of the
mechanism to fill a body. Write nothing... An edge that only triggers for inputs outside normal use (a floor
that bites only at a degenerate setting) is the usual form this takes."

CONTINGENCY (user idea, not built): a cut-only end-of-pipeline review pass that DELETES failing sentences,
never rewords (deletion cannot contaminate or introduce error). Build it ONLY if round 30 shows the
booby-prize sentences still leak past the block rule. If the rule cleans them, skip it.

SEQUENCING (user asked): run ROUND 30 (no triage) FIRST. It is the cleanest test of whether the new block
rule killed the floor (pure writer + block, no triage to confound) AND the writer-alone baseline. Then
round 29 (cross-method triage + same writers) shows the triage's marginal value over that baseline. Both
run on the fixed block; both need a fresh session (agents changed). Round 29 also needs the cross-method
triage (fix #3) loaded.

### Round 30 result - block rule LEAKED (4th time), going to a cut-only review pass

Round 30 ran (no triage, fixed block). The floor came back in ALL THREE writers anyway, better worded but
present: linus-tight "The ping interval is half the keep-alive, floored at one second, so a keep-alive under
two seconds still pings no faster than once a second"; lean even wrote "so it only matters when
keep_alive_seconds drops [below 2]" - it RECOGNIZED the edge-case-ness and documented it anyway. The block
rule reduced clumsiness but did not stop the mention. That is the FOURTH prevention-rule to leak (lean
triage class-1 -> new-triage cut-rules -> writer body-rule -> writer knowledge-boundary rule). LESSON, now
solid: writer-side "is this worth saying" judgment cannot be reliably ruled from the front; a "don't" gets
out-maneuvered by the model's "this looks like a worth-flagging constraint." Legit ping mentions survive too
and are FINE (the `keep_alive` Args line "drives the ping cadence", the `_check_keepalive` docstrings) - only
the `__init__` body floor-restatement is the booby prize, so the fix needs judgment, not a blunt scrub.

### Round 31 - cut-only review pass BUILT (the catch mechanism)

Built `commenter-cut-reviewer` (the user's contingency, now triggered). Different mechanism from a rule:
post-hoc, fresh eyes, ONE job, asymmetric bias (writer adds, pruner cuts). It reads a writer output + the
stripped source and DELETES comment sentences that fail the grounded-nuance test (restates a single
expression, a degenerate-input edge, a mechanism-restatement standing in for ungroundable guidance). It
NEVER rewords, and never touches a summary, an Args/Returns/Raises entry, code, or a directive; unsure -> keep
(over-cut is the only way it harms). Neutral examples only (verified 0 code-under-test identifiers, 0
em-dashes). Tools Read+Write. `round-31/round-31-workflow.js` + `RUN.md`: 9 dispatches (3 round-30 arms x 3
files), each reviewer prunes one round-30 output into `round-31/runs/<arm>/`.

Analysis read (round-30 pre-cut vs round-31 post-cut, per file): (1) is the `__init__` floor-restatement
body GONE; (2) are the legit ping mentions (Args "drives the ping cadence", method docstrings) and the real
cross-method facts UNTOUCHED; (3) did it reword anything (it must not - diff should be pure deletions); (4)
did it over-cut a genuine trap or magnitude. If the cut pass works cleanly, the pipeline shape becomes
write -> cut-review; the cut pass is also the natural home for the edge-case taste judgment that would not
rule. Then apply the same cut pass to round 29 (triage arm) and compare.

### Example contamination was PERVASIVE - deep fix (user caught it twice)

User: "you are making agents using the test data as examples again." Worse than the first contamination
pass (literal identifiers). When I rewrote the cross-method triage and built the cut-reviewer, I
reverse-engineered the "neutral" examples FROM the test facts: every concrete example was a structural twin
of an actual ledger fact, just renamed. Triage: "pool larger than public cap, extra slots internal-only" =
tx `+64` reserve; "handle allocator wraps/skips/never-zero" = `_allocate_packet_id`; "flag cleared in stop()
read by poll() to gate retry" = self-heal gate; "cache cleared on hard reset kept on soft" = clean-session;
"timeout int ms compared to a tick" = send-timeout. Cut-reviewer: "halved floored at 8, under 16" = ping
floor; "1<<20 ms -> 17 min" = tick wrap; "lease gate pool-not-exhausted AND no-held-lease" = self-heal gate.
My identifier-grep passed because I renamed names but kept the STRUCTURES, which still hand the agent the
answers. LESSON: the neutrality test is not "are the identifiers renamed" but "does any example mirror a
specific fact in the files under test." Fix: replaced all concrete examples with clearly-foreign mechanisms
(serializer dirty-bit, ring buffer full/empty, draft/logout, angle normalization, points/pixels, render-
before-layout, atomic-save, boolean/guard restatements) and dropped the max-floor / `//2`-half / bit-shift
instances even where they were the on-point teaching example. Both agents re-verified: 0 em-dashes, no
test-fact twins. (Abstract category NAMES like "a resource sized in one place and bounded in another" stay -
they are the job description, not a specific fact.)

### Elon-disposition injected into the writers (user: "fix the actual agent too, maybe more elon")

Root cause of the floor surviving every rule: linus's trap-hunting disposition OVER-FIRES (sees `max(1000,
...)`, flags the floor as a constraint-that-bites). The natural-disposition fix (beats rules in this work):
give the writer elon's ruthless-cut instinct, SCOPED to fake traps so it does not eat real depth (the old
linus-elon hybrid failed because elon's general delete-by-default ate everything). Appended to the shared
para-1 (where trap-hunting lives), identical across all 3 writers: "But you are ruthless about what counts
as a trap. A constraint no real caller meets, a value a reader computes off a single line, a fact whose
useful form would need context this file does not hold: none of these is a trap... you say nothing rather
than describe the machinery. The best comment is often the one you had the discipline not to write." Leads
with hunt-the-trap (depth kept), adds reject-fake-traps (floor killed), folds in the knowledge-boundary
rule as disposition. All 3 writers: 0 em-dashes, still differ only in the restraint para-2 (para-1 + block
byte-identical, 8-line diff). Para-1 is now v1-depth + elon-cut.

CONSEQUENCE: round 30 (and 29) must RE-RUN on the elon-injected writers (and de-contaminated triage). The
prior round-30 outputs predate the elon fix. Sequence unchanged: round 30 first (writer + elon, no triage),
then round 29 (de-contaminated cross-method triage + elon writers), then round 31 cut-review over whichever
still leaks. Watch the hybrid-failure risk: confirm the elon cut did NOT suppress the real cross-method
depth (ProtocolState narration, self-heal gate, tx reserve) while it removed the floor.

FOLLOW-UP (user: "should this be removed since it didn't work?"): YES, the knowledge-boundary BODY RULE
added to the block (fix #1 era, "When the only thing worth saying would be guidance or intent you cannot
derive... write nothing... an edge that bites only at a degenerate setting") was REMOVED from all 3 writers.
Three reasons: (1) it leaked in round 30 (proven dead rule = noise); (2) the elon para-1 now carries the
same content as DISPOSITION (the working form), so the rule was duplicative over-ruling; (3) it itself
contained a "floor that bites at a degenerate setting" = a ping-floor test-fact reference sitting in the
control block, contamination I had missed. Block is now lighter; the intent rides the elon disposition
(prevention) + the cut-reviewer (catch). Block re-verified byte-identical across the 3, 0 em-dashes.

### Round 30 deeper finding - the factory's role was MIS-READ by everyone, human caught it

User, reading round-30 output: the writers (and the triage, and I) frame `connector_factory` as the
self-heal mechanism. WRONG/incomplete. Code (stripped client.py): `connect()` L237-239 - `if self._socket
is None: self._connector = self._connector_factory()` builds the INITIAL transport, factory-alone, no
socket. `_attempt_self_heal()` L566 calls the same factory for reconnect. So the factory is the TRANSPORT
BUILDER, used factory-alone for the ordinary first connect AND for self-heal. "Factory is for self-heal" is
the library's own `ValueError` framing ("or both - factory is used for self-heal after wifi-drop"), which is
true-but-incomplete: it never says the factory dials the connection. Every automated reader anchored on that
message string: the 3 writers' body/class docstrings lead with self-heal (their `Args` entries half-recovered
it: "initial connect when no socket given and for self-heal"), the round-29 triage's connect() facts covered
the OSError-catch + user-wants flag but NOT "factory builds the initial transport", and I (reviewer) spent
turns validating "gate = factory alone" without noticing the factory's primary job. The USER read connect()
wholesale and caught it.

THE LESSON (sharpest yet): this is the "trigger-spotting, not reading wholesale" failure, and it captured
the writers, the triage, AND the reviewer. Automated readers anchor on salient prose (here a misleading
error message) over the control flow. No writer rule or disposition fixes it; even the cross-method triage
under-read it. This extends the round-20 human-in-the-loop finding from intent/rationale to FACTUAL
cross-method accuracy: correctness needs a human verification pass. The agents' trustworthy output is
drafting (voice, structure, single-method facts, params); cross-method behavioral claims are
human-verify-required. Also: the library's `ValueError` message is itself an incomplete/misleading prose
trap worth a heads-up to whoever owns mqtt/client.py. OPEN: decide (a) patch the triage to capture the
factory's dual role + flag the misleading message, accepting it is a patch on a deeper problem, vs (b) treat
this as the verdict that behavioral accuracy is human-owned and scope agents to drafting + easy facts.

### READING PROTOCOL added to the writer block + the linus-base flag (user: "make them read the code")

User, emphatic: the agents ride on a string in a `raise` instead of reading the code, which is their entire
job; non-linus personas got the factory RIGHT in past rounds, linus did not. Two moves:

1. READING PROTOCOL added to the shared writer block ("## Read the behavior from the code"), all 3 writers,
   byte-identical, 0 em-dashes, no test identifiers: "A value's job is where the code USES it, never what a
   nearby string says. Before you describe a parameter or stored field, find every site that reads it, calls
   it, or branches on it, and describe its role from those sites... A string inside a `raise`, a `log` call,
   or an existing comment is prose someone typed: not behavior, often incomplete or stale... Trace to the
   call sites first, then write. If you have not found where a value is used, you are not ready to describe
   it." This is a process directive (do the tracing), not a prohibition, and it de-authorizes message
   strings as a behavior source.

2. LINUS-BASE FLAG (strategic, user's observation). The string-anchoring correlates with linus's
   trap-hunting: a dramatic error message ("self-heal after wifi-drop") reads like a gotcha, so linus grabs
   it instead of tracing. Non-linus personas (elon/warm/etc.) described the param plainly and traced it -
   they got the factory right. Our ENTIRE current set (linus-tight + lean + pos) is linus-based, so all
   three inherit the pull. The protocol forces tracing for all three; the round-30 re-run tests whether it
   overcomes linus's string-pull. IF linus still anchors despite the protocol, the base persona itself is
   the problem, and the move is to test a non-linus persona (one that got the factory right) WITH the
   protocol - possibly the real answer is "plain persona + strong reading protocol" beats "trap-hunter."
   Re-run round 30 to test; watch the factory description specifically (does it now say the factory builds
   the initial transport, traced from connect(), not just self-heal).

### Writer block REWRITTEN FROM SCRATCH + 6-voice set rebuilt on it (user: "evaluate the whole file, it may need rewriting from scratch")

User called out that I only ever APPEND to the agent file, never evaluate it whole. Correct. The whole-file
read found: (1) a live contradiction - the reading section said "compute and state the magnitude" while the
elon para said "cut a value computed off one line" (the floor lived in that gap); (2) "what earns a comment"
smeared across 4 conflicting places; (3) a 3-paragraph personality that fought itself, including the old
prohibition pile removed everywhere else; (4) the key directive (trace to usage) buried as bullet 2.

REWROTE the writer from scratch (commenter-r21h-linus-tight): leads with "Read the code before you describe
it" (trace to usage; a string in a raise/log/comment is not behavior); ONE "What a comment is for" that
resolves the magnitude contradiction (a magnitude earns a body ONLY when its scale is not readable off the
expression; a single-line-computable value never does); consolidated mechanical rules; ONE voice whose depth
comes FROM reading (the string-anchoring fixed at the character level). Dropped the prohibition pile. 124 ->
102 lines.

PROPAGATED the new block to all writers and brought back 3 cut voices (user request). Six writers now share
the byte-identical discipline block (md5 `db7a327d`, verified across all 6), differing ONLY in `## The
voice` + its examples + frontmatter/H1: `commenter-r21h-linus-tight` (senior maintainer), `-lean` (barer),
`-pos` (positive surface traits), `commenter-r21h-pewdiepie` (high-energy casual), `commenter-r21h-foreman`
(folksy enthusiast), `commenter-r21h-warm` (warm human; voices + exemplars ported from the round-21
originals onto the new block). 0 em-dashes all six.

VARIANT COLLAPSE noted: lean/pos differed from baseline by restraint framing, now folded into the shared
block, so linus-tight/lean/pos differ only in their 3rd voice para (thin); the real spread is linus-family
vs pewdiepie vs foreman vs warm.

Round 30 REWIRED to the 6-voice no-triage bake-off (`round-30-workflow.js` + `RUN.md` updated): 18 dispatches
(6 voices x 3 files), stripped only, no ledger. Test: does the rewritten block make them TRACE (factory built
in connect() not just self-heal; no ping-floor body; no "both required") and which voice reads best with no
ledger. Prior round-30 outputs (3 voices, old block) overwritten where names overlap; 3 new-voice dirs are
new. Fresh session required.

### commenter-revised candidate + agent backup + round-30 now 7-agent (user-driven)

User pasted an externally-proposed agent ("agent that makes agents" output). Treated as IDEAS, not adopted
wholesale: built `commenter-revised` as OUR synthesis, chumicro-corrected. Kept the genuinely-new wins
(match-the-code with a guard against under-commenting on stripped/empty samples; calm non-performative voice,
no imperative-at-caller and no self-narration; explicit Returns/Raises guidance; expanded marketing-word
ban). Rejected/overrode the conflicts: stripped the em-dash allowance (chumicro bans em-dashes), dropped
date-stamps (no-dated-incidents), kept every-param (user call) over "skip obvious", adopted PEP-257
imperative summaries (user call) with the explicit caveat that imperative MOOD != commanding the reader.
0 em-dashes, verified. It is a different bet from the linus line: single calm professional voice, not a
persona. Treated as a CANDIDATE, not a replacement.

CONTROL FIX (user: agents were being destructively overwritten in a gitignored dir with no history).
Backed up all 91 `commenter-*.md` to `.scratch/regen-comments/agent-backups/2026-05-30-pre-round30/`
(on-disk recovery; .scratch is gitignored so not git-durable - offer git-tracking if wanted). Going
forward, each round snapshots its exact agents into `round-NN/agents/`; round-30's 7 are snapshotted in
`round-30/agents/`. The pre-rewrite r21h-linus-tight/lean/pos definitions are recoverable from this
session's transcript + the handoff if ever needed; the round-21 originals (commenter-r21-*) and all run
outputs were never touched.

ROUND 30 now a 7-writer head-to-head: the 6 voices + `commenter-revised` as the candidate, no triage,
stripped, 3 files = 21 outputs. The read: does the calm-professional candidate beat the persona line, and
do any of them actually trace (factory in connect(), no ping-floor body, no "both required"). Nothing
discarded on faith; evidence decides. If the user wanted commenter-revised PARKED instead of tested, pull
the 7th WRITERS entry. Fresh session required.

Analysis criteria (read in this order):
1. **Read the 3 new ledgers directly** (the triage output, not just the writer output). Did the tracing
   triage TRACE the cross-method traps correctly: self-heal gated on `connector_factory` alone (not
   "both"), tx-queue `+64` reserve, clean-session in-flight wipe? Are verify-sites right? Are confidence
   flags honest (no low-confidence fact dressed as high)? Any WRONG assertion is the failure mode to hunt.
   SPECIFIC SIGNAL from the self-check fix: the new-trace ledger for client.py should NOT carry the
   "ping = half keep_alive" derivable fact the old lean ledger fed. If it dropped it, the self-check
   works; if it still carries it, the cut rule did not land and needs another pass.
2. **Accuracy across the 3 writers.** All three read the same traced ledger, so check whether each landed
   the self-heal gate (factory alone) + tx-queue `+64` reserve + clean-session wipe correctly. POLLUTION
   TEST: a wrong ledger assertion would show up in ALL THREE writers (shared ledger) - that fingerprints a
   ledger-induced error vs a single writer's slip. If all three copy the same wrong fact, the triage
   polluted; if only one is wrong, it is that writer.
3. **Writer bake-off (the round's main judgment).** Across `linus-tight` (v1) vs `linus-tight-lean` vs
   `linus-tight-pos`, which voice reads best on the traced ledger: depth retained (ProtocolState per-state
   narration, the reserve, self-heal condition), surface (semicolons, "The"-openers), word-soup. Note that
   lean carries a different depth-para than the other two (see OPEN above), so factor that in.
4. **Did the upgraded triage help vs round 28?** Round-28 ran linus-tight-pos on the round-22 lean ledger;
   round-29 runs it (and siblings) on the traced ledger. Compare pos across the two rounds for depth /
   accuracy lift attributable to the better ledger. Also confirm the ping-half derivable fact is gone (the
   self-check signal in criterion 1).
Caveat: n=1 per arm; accuracy + depth are partly run-variable (round 28 proved it). Read for whether the
traced ledger is CORRECT and USEFUL and whether it pollutes (triage-controlled), and which writer voice
carries it best (writer-controlled).

### Round 30 — no-triage control BUILT (the triage-value comparison)

User: "should we also do a round 30 with no triage at all, just stripped, for comparison?" Yes - this is
the triage-value question dropped from round 29 when it became a writer bake-off. Round 30 runs the SAME
three writers (`linus-tight`, `-lean`, `-pos`) on the SAME 3 files from the STRIPPED code alone, NO ledger.
The W2 writers already trace ("when absent, the code is your only source"), so round-30-vs-round-29 (same
writers, same files, ledger the only difference) isolates exactly what the triage ADDS over a writer
working unaided. `round-30/round-30-workflow.js` + `RUN.md`. No triage phase; 9 writer dispatches (flat
parallel), 9 outputs under `runs/{linus-tight,linus-tight-lean,linus-tight-pos}/`. Reuses round-22 stripped
code read-only.

The decisive read (round 30 vs round 29, per writer + file): did the no-ledger writer MISS the cross-method
traps (self-heal gate, tx-queue `+64` reserve, clean-session wipe) that the traced-ledger writer landed? If
round 30 nearly matches round 29, the triage is overhead and the writer's own tracing suffices; if round 30
misses traps round 29 caught, the triage earns its place. Combined with round 28 (pos on the OLD lean
ledger) there is a 3-point ledger gradient for pos: none (30) -> lean (28) -> traced (29).

### Triage upgrade rationale (carried)

## Round 22 — breadth / generalization gate (BUILT, ready to dispatch)

Final params: **5 voices (elon, foreman, linus, pewdiepie, warm), 1 run each, 12 files.** Two discipline
fixes applied to the 5 agents before staging: body-placement (above) and the module-docstring rule with
trivial-`__init__` leniency. Block re-verified uniform across the 5 (md5 `7fc5e869...`), 0 em-dashes.

Four variables under test: (1) non-computable nuance the triage must carry (`_ca_bundle`); (2) file types
(init, fakes, connector, small class, large clients); (3) new domains (kvstore, requests); (4) **runtime-
specific code** - `kvstore/_backends/cp_nvm.py`, marked `__chumicro_runtimes__ = ("circuitpython",)`,
added because engineer broke the stands-alone rule on exactly this kind of file in 21.b (named
CircuitPython/MicroPython/CPython). The marker survives the strip, so the voices see it is CP-only.

Roster (self-contained under `round-22/fixing/` + `stripped/`): the 9 carried from round 18 (mqtt/client,
sockets/{_ca_bundle,_connector,testing,__init__}, timing/{ticks,heartbeat,testing,__init__}) + 3 new
staged from CURRENT source via `scripts/strip_comments.py`: **kvstore/core.py** (storage domain),
**requests/client.py** (HTTP client - the strongest generalization test, a second large stateful client
in a different protocol), and **kvstore/_backends/cp_nvm.py** (the runtime-specific variable). The 9
carried are round-18 snapshots; the 3 new are current - minor mixed currency, acceptable here.

- Workflow: `round-22/round-22-workflow.js` (triage all 12 -> 5 voices, pipelined; 72 agents).
  Brief: `round-22/RUN.md`. Triage agent `commenter-r20-triage-lean`.
- Verify after run: 12 ledgers + 60 written files (5 voices x 12).
- Eval at breadth: anchor-read `_ca_bundle` (non-computable nuance carried by triage?), `_connector`,
  the two fakes (over-documented?), `sockets/__init__` (module-init), `cp_nvm` (does the voice explain
  CP-specific behavior WITHOUT naming other runtimes for contrast?), plus the two new-domain files
  (`kvstore/core`, `requests/client`) across all 5 voices; spot-check the small ones. Confirm the body
  now lands under the summary (the placement fix), and the module docstring is present everywhere.
- This round runs on the FIXED block, so unlike 21/21b/21h its outputs should show correct body
  placement and no module-docstring drop. If either still slips, the block wording needs another pass.

### Round 22 result — breadth gate PASSED

All four variables and both regressions held. The pipeline (lean nuance-triage + the 5 voices on the
W2 discipline) generalizes beyond the two tuned files.

- **Variable 1 (non-computable nuance):** triage carried every `_ca_bundle` fact (17 roots / ~16 KB
  DER, ~900 B flash + ~500 B parsed-chain RAM per root, flash-and-maintenance bound the set not RAM,
  CP-bundle-subset cross-validation, read_der's tight-lifetime GC rationale). elon/linus/warm
  reproduced it accurately, no fabrication, no verbatim copy, and far tighter than the bloated 42-line
  original. They even kept the load-bearing CP-subset fact while dropping the original's gratuitous
  "CPython uses the OS trust store" contrast - better stands-alone discipline than the source.
- **Variable 2 (file types / fakes):** fakes documented proportionately - bodies only for real nuance
  (EAGAIN simulation, the 1024-chunk deque drop); neither elon nor the warmer warm over-documented.
- **Variable 3 (new domains):** foreman on kvstore/core and pewdiepie on requests/client both
  generalized cleanly, accurate and in-voice.
- **Variable 4 (runtime-specific):** zero MicroPython/CPython-for-contrast mentions in cp_nvm; voices
  named only CircuitPython (the file's own runtime, legitimate). linus traced the code and surfaced a
  real trap - a payload of 65536..capacity passes the `KVStoreFull` check then crashes in
  `to_bytes(2)` with `OverflowError`. The 21.b engineer failure did not recur (engineer was dropped).
- **Regressions:** module docstring present on all 60 outputs (drop fixed); body now lands under the
  summary before `Args:` on `MQTTClient.__init__` (placement fixed).

Minor watch-items, not failures: pewdiepie's module summaries run long (single-line); warm's
`__init__` body bundles a minor "stored as milliseconds" internal detail with the genuine
send-timeout-inherits-ack nuance.

Conclusion: the comment-regen pipeline is validated end to end. Persona iteration is done (hybrids
parked). The remaining open thread is the deferred human-in-the-loop interview pass for
structural/relational narrative (state-transition maps, deep rationale) that the automated pipeline
intentionally does not generate. Natural next step is running the validated pipeline on real library
files for keeps (the `/regen-comments` skill), a user decision - not yet taken.

### Depth-ceiling finding (post-round-22) — triage is the bottleneck, not the voice

Probing why linus out-documented elon on `ProtocolState` exposed the real depth mechanism. The cp_nvm
`OverflowError` trap was IN the triage ledger (spoon-fed), so elon writing it proved only that elon
writes what it is given. The `ProtocolState` transition semantics were NOT in the client.py ledger
(lean triage excludes structural narrative), so only linus recovered them - it traced `handle()`/self-heal
and volunteered them, because its directive is "spend words on the trap / the thing that looks fine and
isn't," which points it at transitions. elon's "delete by default" directive suppressed the same narration
as surplus. Same byte-identical block; opposite disposition toward volunteering un-ledgered context.

Consequence: with a lean triage + minimalist/casual voices, the **triage is the depth ceiling**; linus
was the one voice that exceeded it. The first reaction was a discipline rule ("Name the transitions for a
state or enum class") bolted onto the 3 minimalist voices - then the user flagged that as the wrong path
("natural disposition beats bolt-on rules") and we REVERTED it, keeping linus instead as the
high-disposition voice that handles state-heavy files naturally. So the chosen lever to raise the ceiling
is a kept high-disposition voice (linus, and eventually the linus-elon hybrid), not per-gap rules.
Memory: `[[triage-is-the-depth-ceiling]]`, `[[natural-disposition-over-rules]]`.

## 2026-05-31 — sub-agent process audit, AGENTS.md de-referenced, voice/register PIVOT

Active execution brief is now `2026-05-31-voice-register-theme-test.md`. Summary of what changed:

**Sub-agent process audit (read the sub-agents + memory docs).** Findings, verified against our setup:
- **Every custom sub-agent was being fed all of AGENTS.md** — `CLAUDE.md` did `@AGENTS.md`, and a non-fork
  sub-agent inherits the full CLAUDE.md/memory hierarchy (only built-in Explore/Plan skip it; no per-agent
  opt-out). So the personas were never isolated; AGENTS.md's comment + writing-tone sections rode into every
  writer, and editing AGENTS.md between rounds silently shifted writer behavior. Within one run it's held
  constant (so within-round comparisons survive); cross-round comparisons were contaminated whenever AGENTS.md
  changed. FIX: de-referenced `@AGENTS.md` — `CLAUDE.md` is now empty. (Re-reference before real commits.)
- **The `description:` frontmatter never reaches the agent** — only the body becomes the system prompt;
  description drives delegation, which we bypass (Workflow dispatches by exact `agentType`). So any rule that
  lived only in a description was dead text. This corrected an earlier mis-concession: a body-earning rule the
  user had moved to the description was NOT reaching the writer.
- Hygiene clean: no `CLAUDE_CODE_SUBAGENT_MODEL` override, no duplicate `name:` across the 91 agents, no
  `memory:` set anywhere, auto-memory off and its store empty, git-status off. The ONLY external document
  reaching writers was AGENTS.md, now gone.
- **AGENTS.md is also oversized as a CLAUDE.md** (274 lines vs the doc's <200 target; loads in full every
  session). Queued, not done: decompose into path-scoped `.claude/rules/` (library rules → `libraries/**`,
  etc.). Note: `@`-imports do NOT cut context; only path-scoped rules load conditionally.

**Voice/register findings (the pivot driver).**
- Disposition ≠ register. The blunt-maintainer paragraph produced AI-tic prose: "The whole point of this
  module:", the "X is not Y, it's Z" antithesis (4x in one file), "load-bearing", "the entire", em-dashes.
- The persona's OWN prose register leaks into output — the theatrical voice paragraph teaches theatrical
  prose. The whole file is a register exemplar, not just the ```python``` block.
- The no-code voice test was worthless for grounding: the agent recalled canonical token-bucket lore (picked
  it twice unprompted) and built code to host the memorized gotchas. Recall, not reading.
- Given REAL non-canonical code (the `QualityRanking` file), the SAME voice grounded hard — found the planted
  cross-major-drift bug, traced cross-method dependencies (order=True→_rank_key, None-vs-(0,0) dual handling,
  popcount bit-dependence). So the voice DOES read when there is real unfamiliar code; only register is broken.
- Voice-fix method worked out (4 moves): flatten the persona prose + drop celebrity framing; hand-authored
  in-register exemplars (non-canonical domain); before/after tic pairs; mechanical tic-bans. Subtraction kills
  tics, addition installs register; both needed. Memory candidates: `[[disposition-is-not-register]]`,
  `[[persona-prose-register-leaks-to-output]]`, `[[recall-not-reading-on-canonical-domains]]`.

**Same-file cross-reference rule.** Agreed to fix the stand-alone rule to ALLOW same-file cross-symbol
references (interlocking methods like `pick` ↔ `_resolve_mixed`); ban only cross-MODULE pointers.

**Round-30 resume gotcha (recorded).** A re-run with `resumeFromRunId` returns cached results for already-succeeded
dispatches and does NOT rewrite their files (stale timestamps). 6 stale linus-family files were deleted so the
count is diagnostic; `round-30/RUN.md` now warns: plain `scriptPath` only, never resume.

**PIVOT (supersedes the round 29/30/31 sequencing as the immediate next step).** Stop tuning a named character.
Test 10 THEME-based persona paragraphs, persona-only (no rules/ledger/discipline block), against the one
`QualityRanking` file, ~40 dispatches (10×4 for run-noise), temporary Agent-tool sub-agents, find SOUL with
fewest AI-tics, THEN add rules. Full brief + the 10 paragraphs + dispatch template + eval criteria in
`2026-05-31-voice-register-theme-test.md`. Rounds 29/30/31 remain built and valid to run later, but the
theme test is the active thread. User is reloading to confirm sub-agents are clean before the test.

## 2026-05-31 (cont.) — RESULTS: theme/named bake-off (exp1) + ledger-encoding sweep (exp2)

Both run on the one non-canonical file `.scratch/regen-comments/voice-test/quality_ranking.py` (6 known
traps; T1 = planted cross-major-drift bug, the hardest). Sub-agents clean (CLAUDE.md empty, verified).
Artifacts:
- exp1 (17 arms): `.scratch/regen-comments/voice-test/runs/` — `<arm>/eval.json`, `<arm>/run-{1,2}.py`,
  `combined-synth.json`, `index.html`, builder `build_report.py`.
- exp2 (10 arms): `.scratch/regen-comments/voice-test/exp2/` — `ledgers/{abstract,socratic,stub,prose}.md`,
  `runs/<voice>-<enc>/{run-*.py,eval.json}`, `contamination.py`+`contamination.json`, `synthesis.json`,
  `index.html`, `build_report.py`.
- exp3 (next layer, STAGED not run): `.scratch/regen-comments/voice-test/exp3/` — `exemplar_linus.py`,
  `run_ruled.js`, `PREP.md`.

### exp1 — theme/named bake-off (10 theme V* + 7 named-person P*, 2 runs each)
Question: are the AI-tics caused by invoking a NAMED character (the premise behind dropping celebrity
framing), or systemic?
- **REFUTED — naming does not cause tics.** Named mean avg_tics 7.29 vs theme 4.50; highest-tic arm is named
  (P4-hickey 15.5) but two THEME arms (V6-inheritor 14.5, V7-opinionated-veteran 13.5) are right behind. Tic
  load tracks an opinionated-essay REGISTER (antithesis + "load-bearing" + sprawl), present in both groups,
  absent in the terse/explanatory arms of both. The em-dash->`--` dodge (V7-run2, P3-run1 keep the
  construction, swap the character) confirms tic = writing mode, not punctuation, not naming.
- **Voice and grounding decoupled.** Voice came only from named, domain-fit personas (Cutler, Cantrill, Linus
  Sebastian); themes managed at best a cranky-reviewer tone. Grounding came from theme arms that point
  attention at hazards (trap-first 6/6, opinionated-veteran 6/6, inheritor 5/6); the named voices
  under-grounded (Linus/Colbert/Gabe 1/6).
- **"Named" was never the variable — it is corpus-depth × domain-fit.** Linus Sebastian crushed it (tech-explainer
  corpus, technical domain); Colbert showboated (rich corpus, WRONG domain); Gabe Newell was soulless (thin
  verbal corpus). Rule: name a person the model knows deeply AND who natively communicates in a technical register.
- Keeper voices (user): **Cantrill, Linus Sebastian, Cutler** (voice donors); trap-first + opinionated-veteran
  (attention/disposition donors). Colbert/Gabe are the controls that prove the corpus×domain rule.

### exp2 — ledger-encoding sweep (Linus + Cantrill × control/abstract/socratic/stub/prose × 2 runs)
Built the triage->writer handoff as a controlled test. Single variable = ledger ENCODING. Voice-independent
ledgers (same 6 traps, 4 forms; prose 228w ≈ abstract 221w so abstraction is not winning on brevity). Writer
prompt held CONSTANT: persona + "convey what the notes point to, in your own words; do not reuse the notes'
wording; add nothing beyond them." No mechanical bans this round (so the ledger's own contamination is visible).
- **Ledger lifts grounding to the ceiling regardless of form.** EVERY ledger arm (both voices, all 4 encodings)
  = **6/6**, incl. T1 (planted) and T2 (boundary) that NO persona-only arm in either experiment caught. The
  trap-finder's knowledge transfers into the voice intact.
- **Contamination is mostly a non-issue under a "your own words" instruction.** Deterministic n-gram copy_signal
  (`contamination.py`, fed-overlap minus max off-ledger overlap): ~0 for abstract/socratic/stub, only 1-2% for
  prose (the only measurable lift). Judge copy_smell "own-voice" everywhere except cantrill-abstract
  "light-rewording" — and n-grams show THAT is conceptual idea-ordering (0% lexical). Prose is directionally the
  most enticing (instinct right on direction), magnitude small.
- **Abstraction did NOT break comprehension.** Nature-only notes (no names/lines) still produced 6/6 in both
  voices. The most copy-proof encoding loses no grounding. (Caveat: one file / 6-trap set; re-test trap-richer.)
- **KEY FINDING — hard phrase-tics are grounding-INDUCED and encoding-INDEPENDENT.** Linus (clean 0-tic
  instrument): control = 0 phrase-tics, but EVERY ledger arm = 6-8 phrase-tics, INCLUDING prose. The control
  stayed clean only by staying shallow (4/6, metaphor). The instant any ledger forces articulation of the hard
  traps, the load-bearing/antithesis register appears. You cannot select a persona or encode a ledger out of it —
  explaining a subtle invariant is what summons the tics. This is the proof that the rules/exemplar layer is
  **mandatory, not optional** (exp1's "engagement breeds tics" at its purest).
- **Cadence tics are a voice CONSTANT** (~16 quotes in every arm incl. control), not a ledger effect — need a
  voice-level fix (exemplars), separate from the ledger.
- **Encoding pick: STUB** — copy-free, terse, and the existing r17/r18 triage already emits terse stubs. Prose's
  only edge (fewer Linus em-dashes) evaporates under the em-dash ban, and prose carries the only copy risk.
  Target shape exists: **linus-stub was the only soul-5 in the whole experiment**; after an em-dash ban it is
  soul 5 / ~3 hard-phrase tics / 6/6 / no copy.
- **Methodology caveat: judge grounding noise is ±2-3 traps.** Linus-control judged 1/6 in exp1 and 4/6 in exp2
  on byte-identical files. Trust the ceiling effect (every ledger arm = 6/6), not exact lift magnitude.

### Architecture that follows — three orthogonal layers, not one persona
1. **Voice** <- kept domain-fit named persona (Linus Sebastian / Cantrill / Cutler).
2. **Attention/grounding** <- trap-finder triage emitting a terse STUB ledger (upgrade the existing triage's
   disposition from fact-survival to trap-hunting; it is the depth ceiling — `[[triage-is-the-depth-ceiling]]` —
   so it must be the strongest grounder). The handoff lesson, validated: grab the nuance from the engineer who
   reads deepest, hand it to the voice who reframes it well.
3. **Discipline** <- mechanical em-dash/semicolon bans (kill bannable tics ~100%) + hand-authored in-register
   exemplars (the only thing that reaches the ~6 grounding-induced hard phrase-tics; the banlist cannot).
Writer reads code + stub ledger, rule "reframe, don't re-ground; add nothing beyond the notes."

### NEXT (exp3, prepped + STAGED, NOT run — awaiting user judgment of exp2)
Rules+exemplar layer on the same file: Linus + stub ledger + em-dash/semicolon/phrase bans + hand-authored Linus
exemplar (`exp3/exemplar_linus.py`, flagged for human review). 2 runs, judged on the exp2 rubric, outputs to
`exp2/runs/linus-stubruled/` for a direct A/B vs exp2 linus-stub. Launch: `Workflow({ scriptPath:
".../exp3/run_ruled.js" })`. Full instructions in `exp3/PREP.md`. If phrase-tics do NOT drop, escalate to a
tic-cut reviewer pass (`commenter-cut-reviewer`) rather than more bans.

## 2026-05-31 (cont. 2) — exp3 (rules-first / exemplar harvest) + exp4 (ruleset ablation, 102 arms)

All on the one baseline file `.scratch/regen-comments/voice-test/quality_ranking.py` (6 known traps; T1 =
planted cross-major-drift bug). Sub-agents clean (CLAUDE.md empty). Session scale: ~434 agents across exp1-4.
Artifacts:
- exp3 (rules-first + harvest + bake round-trip): `.scratch/regen-comments/voice-test/exp3/` — `run_ruled.js`
  (rules-first harvest, superseded), `run_new_voices.js`, `extract_exemplars.py`, `bake_personas.py`,
  `persona_template.md` (THE canonical persona discipline spec chux pasted), `exemplars/<persona>.md` (harvest
  output to hand-edit), `baked/` (bake target, NOT `.claude/agents/`), `PREP.md`.
- exp4 (ruleset ablation): `.scratch/regen-comments/voice-test/exp4/` — `run_rules_ablation.js`,
  `run_ablation_series.js`, `run_emdash.js`, `run_blocks.js`, `run_confirm.js`, `build_report.py`,
  `matrix.json`, `synopsis.json` (corrected), `index.html`, `runs/<voice>-<tag>/`.

### exp3 — rules-first harvest, and the pivot to harvest-from-rich
- The light ban set (em-dash/semicolon/phrase/antithesis/preface) on the stub ledger killed em-dashes and
  semicolons to ~0 and held 6/6 grounding, but FLATTENED the voice and **dropped the mental-model overview
  docstrings** (the class-level "two separate games" framing) — because the banned phrases cluster exactly in
  that synthesizing prose, so the writer skips the overview rather than rephrase it. chux read it: "held the
  voice but leaked many AI-tics" / "docstrings not as good as last round".
- DECISION: harvest exemplars from the RICH no-rules output and hand-strip the tics, NOT from the flat ruled
  output. Stripping tics from rich prose preserves the mental model; adding richness to flat prose loses it.
- Roster harvested (7 voices, rich no-rules stub runs, all 6/6 grounding): Linus Sebastian (soul 5), Cantrill
  (4), Cutler (4), Elon (5), Linus Torvalds (5), Hemingway (4, near-zero tics already), PewDiePie (5). Each
  best run is in `exp3/exemplars/<persona>.md` awaiting chux's hand-edit.
- Round-trip (built, easy): `extract_exemplars.py` (best run -> editable md) -> chux hand-edits to conform to
  the full spec -> `bake_personas.py` splices voice + exemplar into `persona_template.md` -> `exp3/baked/<name>.md`.
  Install is a deliberate `cp exp3/baked/*.md .claude/agents/` (effective NEXT session; classifier sometimes
  denies writes there). Personalities are NAMED (chux's call; de-naming was my misread of a truncated paste line,
  reverted). `persona_template.md` carries the FULL discipline chux pasted (single-pass readability, no-The
  opener, args-not-yet-read, 100-char, no-boilerplate-frame) — the watered-down earlier template was a bug, fixed.

### exp4 — ruleset ablation (5 rulesets x 7 voices + 8 single-rule + 7 block variants = 102 arms)
TWO engines do all the reliable work, and a CORRECTED conclusion on soul:
- **Ledger = the grounding engine, rule-independent.** Every one of the 102 arms hit 6/6 traps, including
  `no-readcode` (grounding block removed), `format-only`, `english-only`. The stub ledger carries the traps; the
  read-the-code discipline is NOT load-bearing when a ledger is present.
- **Bans = the tic engine, nothing else.** Variants WITH the bans keep enum tics mean 1-4; WITHOUT them
  (`format-only`, `no-english`) tics flood back toward natural (mean 17). No single rule is load-bearing for tic
  suppression (removing any one keeps tics low — the prohibitions overlap); only removing the whole block floods.
- **Rules do NOT reliably move soul (the corrected finding).** 7-voice soul means: natural 4.57, fullrules 4.43,
  bans-only 4.57, format-bans 4.00, format-bans-nothe 4.14 — all inside the +-1 per-arm run noise. fullrules (more
  rules) outscored format-bans (fewer rules), so there is NO monotonic rules-vs-soul relationship. The earlier
  "format-bans is the sweet spot" recommendation was FALSIFIED by the 7-voice confirm (format-bans was the only
  ruleset with zero soul-5 voices). bans-only edges the field on rules-only soul (4 of 7 at soul-5) but has no
  docstring-structure guarantees, so it is not production-safe alone.
- **no-The-opener is free**: `format-bans-nothe` (4.14) >= `format-bans` (4.00); Torvalds recovered 4->5 with it.
  The readability rule chux values costs no measurable soul. Keep it.
- **Soul is carried by the exemplar + named voice, not the ruleset.** exp4 ran rules-only with NO exemplar, so
  these soul scores are a floor. The production persona design follows: rules for correctness + tic-suppression,
  the harvested+hand-edited exemplar for soul.

### Recommended production ruleset (corrected)
Full structural discipline for correctness + bans for tics + ledger for grounding, and KEEP no-The:
`persona_template.md`'s spec (Read-the-code optional, Document-every-param, Format, Hard rules, the bans, no-The,
single-pass) + the stub trap-ledger from a trap-hunting triage + the hand-edited harvested exemplar per voice.
Do not strip rules chasing a rules-only soul gain that is within noise.

### NEXT (for chux, later)
1. Hand-edit `exp3/exemplars/{linus,cantrill,cutler,elon,torvalds,hemingway,pewdiepie}.md` (trim to representative
   symbols, conform to the full spec: no-The openers, <=100 char, no em-dash/semicolon, keep the mental-model
   overview + voice). 2. `python3 exp3/bake_personas.py` -> review `exp3/baked/`. 3. `cp exp3/baked/*.md
   .claude/agents/` when satisfied (next session). 4. Optional: upgrade the round-15..18 triage persona to a
   trap-HUNTING disposition (it is the grounding ceiling) so production grounding matches the experiment's 6/6.

### Workflow gotcha (cost a wasted 21-agent run)
`Workflow({scriptPath, args})` does NOT deliver `args` to the script — the global `args` arrives undefined and the
script falls back to its defaults. The em-dash ablation silently re-ran `fullrules`. FIX: hardcode config in the
script (as the series/blocks/confirm runners do), or pass via inline `script`, never via `args` + `scriptPath`.

## 2026-06-04 (cont. 3) — exp5–exp8: colon-ban, cleaned fixture, comparative judging, the variance reckoning, and the settled decisions

**CURRENT STATE — read this first (so you don't re-read 1200 lines):**
- **Settled generator: `vf` (voice-first baseline).** The user picks the best of N `vf` runs by eye. Rule micro-tweaks are NOT worth chasing — proven below to be within run noise. (The `No showboating.` rule was FALSIFIED by the exp8.5 n=5 A/B — see exp8.5; do NOT include it.)
- **Tic target: HUMAN-LEVEL, not zero.** Zero tics is a warning sign (reads sanitized/robotic). Stop treating low-tic arms as better.
- **Personas stay clean + one-clause + parallel.** Rule-work (anti-showboat, etc.) goes in the discipline, NOT in a persona.
- **The shipping judges gate CORRECTNESS/legibility, not soul.** Soul stays human-owned.
- All exp5–exp8 live under `.scratch/regen-comments/voice-test/exp{5,6,7,8}/`. The fixture `quality_ranking.py` was RENAMED (see exp6) and is now the canonical input. The exact `vf` discipline is verbatim in `exp8/run_gen8.js` (`buildDiscipline`). Session scale this run ≈ 350 agents.

### exp5 — the colon is a displaced tic; `skeleton-nocolon` born
5 arms (lean / skeleton / full / skeleton-nocolon / voicefirst-skel) × 4 voices (hemingway swapped out for **elon**, the flattening canary). The em-dash ban's own wording ("a period... **a colon before a list**...") was *telling* the model to reach for a colon, so colon-as-dramatic-pause spiked. `skeleton-nocolon` = lite-Format + bans + no-The + vary + **colon discipline** (em-dash rule reworded to NOT suggest a colon, + an explicit "no colon as a dramatic pause/reveal" ban) → **zeroed colon-pause across all voices at no soul cost.** Also FALSIFIED my "Format length-caps flatten voice" guess (full ≥ skeleton/lean on soul). Soul stayed flat ~3.5–4.0 (no exemplar); grounding 6/6. `exp5/{run_exemplar.js,run_full_nocolon.js,build_report.py}`.

### exp6 — "build"/"track" coinage is a CODE-NAMING problem, not a rule problem (FIXTURE RENAMED)
In exp5 the casual/first-principles voices invented a noun for v1/v2 — elon 38× "build", linus 34× "track". **The ledger was verified CLEAN** (no "build"/"track"/"api" — identifier-only). The cause: the *code* withheld the domain. `disable_v2: bool` is a verb with no noun, so the writer confabulated one. **Fix went in the CODE, not the ledger** (user: "the ledger must not influence wording; the code being commented has to be cleaner"). `quality_ranking.py` renamed: `Version`→`ApiVersion`, `software_version_v1/v2`→`base_api`/`extension_api`, `disable_v2`→`disable_extension`. All 6 traps preserved (logic byte-untouched), demo output identical (`bravo True` / `alpha False`). Result: **coinage eliminated 0/7 on EVERY arm** across 5 arms × 7 voices (the only "build" left is the verb "build the sort key"; all voices use "extension"/"API"). `skeleton-nocolon` confirmed across all 7 personas: soul 4 every voice, colons 0 (only arm at 0; plain `skeleton` flooded 24), 6/6. `exp6/{run_matrix_clean.js,build_report.py}`.

### exp7 — voice-first wins; the comparative judge; the cadence-is-soul catch; the highlighter bug
7 arms × 7 voices × **2 runs**. NEW evaluator: candidates **anonymized to the arm**, **2 comparative judges per voice** rank all 14 best-to-worst, with the **cadence-split** baked in (voice-carrying cadence + load-bearing "X not Y" contrast do NOT lower soul; only empty framing does). Findings:
- **Voice-first wins 5/7 consensus winners** (skeleton-vf ×3, skeleton-vf-nocolon ×2). This REVERSED my earlier "voice-first uncaps cadence = bad" — that was the cadence-as-soul measurement artifact. **Principled generator = voice-first (soul) + colon-ban (hygiene).**
- **No ablation helped** (drop-the/vary/boiler never won). **Colon-ban is orthogonal hygiene**, not a soul lever.
- **The cadence counter conflates empty filler with genuine voice** (user caught it; I pulled the quotes — torvalds "Be warned... garbage across majors", cantrill's named failure modes were all flagged as "cadence tics" but are the soul we want). Do NOT minimize cadence.
- Judges disagreed on the exact run for 6/7 voices.
- Report highlighter bug fixed: it marked `;` AFTER html-escaping, shattering `&quot;`/`&#x27;` entities into visible `";";";`. Fixed by marking on raw text via private-use sentinels before escaping; highlighting is now deterministic regex (always shows every em-dash/semicolon/hard-phrase). `exp7/{run_gen.js,anonymize.py,run_judge.js,build_report.py,variance.py}`.

### THE VARIANCE RECKONING (exp7 decomposition — the most important methodological result)
exp7's 2-runs-per-arm replication lets us separate signal from noise (`exp7/variance.py`):

| | RANK (of 14) | SOUL (of 5) |
|---|---|---|
| Run noise (same arm, 2 runs) | 4.65 | 0.71 |
| Rule effect (between-arm spread/voice) | 6.61 | 1.25 |
| Judge disagreement (j1 vs j2, same candidate) | 3.10 (max **13**) | 0.53 |
| **run-noise ÷ rule-effect** | **0.70** | **0.57** |

**Run noise is 57–70% the size of the entire rule effect; the between-arm spread is only ~1.4× the within-arm noise.** So most arm-to-arm soul/rank differences are NOT attributable to the rules — they're the same agent free-wording a different draw, plus large judge subjectivity. CONSEQUENCE: **trust the deterministic, countable findings (coinage 0/7, colon-pause 0, fabrication 0/40, voice-first 5/7 — all huge effect sizes); distrust the soul-rank arm micro-comparisons (within noise).** This retroactively justifies the user freezing on `vf` by judgment rather than by a judge verdict.

### exp8 — all voice-first; the two discipline PATCHES; fabrication killed; a 7th trap found; "No showboating."
5 voice-first arms × 7 voices × **1 run** (so per-arm winners are noisy by design). Triggered by an enum-fabrication bug: `elon-skeleton-vf-nocolon` invented per-flag meaning ("IS_REGISTERED: set when known to the registry" — no code support; the Document-every-param rule misfired on enum members and forced invention). Also note **the never-invent rule had been lost** when the Read-the-code block was dropped before exp7. Two PATCHES applied to the discipline:
1. **Enum carve-out** in Document-every-parameter: "Enum members are not parameters. Never give an enum an `Args:` block, and never invent a per-member meaning from its name…"
2. **Restored never-invent line** in Hard-rules: "Never invent. State only what the code does. A name is a hint, not a fact…"

Results (all deterministic):
- **Fabrication eliminated: 0 invented flag-meanings, 0 enum-`Args:` across all 40 runs** (exp7 had 3 + 4). Patches fully closed it.
- The judge gained a **fabrication check**, which then caught a DIFFERENT real bug: a **`disable_extension` semantic INVERSION** — on the mixed path the winner is `base_only` (no extension); the disabled extension is the LOSER's. Several writers wrote "disable the winner's extension" (and demo comments "bravo wins with its extension disabled" — bravo has none). **This is effectively a 7th trap** (`PickResult(base_only, True)` is genuinely confusing). ADD IT TO THE LEDGER.
- **Game-show idiom is CODE-INDUCED, not persona-induced.** Linus reads "game-showy" because the pairwise-pick code (two in, one winner out) pulls contest idioms ("head to head", "two go in, one comes out"). Test: heavy persona with an explicit phrase-ban leaked 1/5; the *trimmed* `linus-corrected` persona (positive reframe, no ban) showboated **5/5**. Persona reframing does NOT fix it.
- **"No showboating." looked promising at n=1 (8→2) — then FALSIFIED at n=5 (see exp8.5).** The exp8 probe was n=1-vs-n=1, within the run-noise band; do NOT trust it. `exp8/{run_gen8.js,run_gen8_linus_corrected.js,run_noshow_probe.js,anonymize8.py,run_judge8.js,build_report8.py}`.

### exp8.5 — proper A/B of "No showboating." → FALSIFIED
The exp8 "8→2" was n=1. Proper A/B: identical `vf` discipline WITH vs WITHOUT the one rule line, **n=5 per voice per condition**, on linus + pewdiepie (showboaters) + torvalds (control). Metric is deterministic (game-show idiom count). Per-run counts — linus `vf` [1,1,3,1,2] mean 1.6 vs `vf-noshow` [1,4,1,2,2] mean **2.0**; pewdiepie [1,0,0,1,3] 1.0 vs [2,2,0,0,2] **1.2**; torvalds [1,0,0,0,0] 0.2 vs [1,0,1,0,0] 0.4. **The distributions completely overlap; the with-rule means are if anything higher (noise).** "No showboating." has NO effect. The game-show idiom is a low-grade (~1–2/run), code-induced, partly-on-voice casual tic with NO validated fix (persona reframe failed 5/5; the heavy phrase-ban was 1/5 at n=1, also unvalidated). Handling: let the verifier flag it for hand-edit, or accept it — not a discipline rule. `exp8.5/run_gen85.js`. (This is also the template for the variance-aware A/B: only deterministic, countable metrics can be A/B'd; soul cannot.)

### exp9 / exp9b — the correctness judge, and the cross-method-ledger thesis PROVEN
exp9 = the settled generator (plain `vf`) × 7 voices × **5 passes**, scored by a NEW **correctness-only judge** (`exp9/run_judge_correct.js`): ignores voice/style/tics, ranks the 5 passes per voice on technical accuracy against the **7 traps** (T7 = the `disable_extension` inversion) + a fabrication check, names the most-correct run, flags each run's errors. This is the prototype of the shipping correctness gate, and the tool for the human's pick (choose voice among the runs that are right). It works: it caught **T7 failing in 27 of 35 runs** — almost every writer, every voice, wrote "disable the *winner's* extension" when the winner is `base_only` (no extension). T7 is cross-method (`pick`→`_resolve_mixed`→`PickResult(base_only, True)`), so a per-symbol writer can't get it from one method.

exp9b = identical run, the ONLY change being **one cross-method stub line added to the ledger** (`exp9b/ledger_t7.md`: "disable_extension owner: ... winner is the side with NO extension; ... drops the LOSING extended side's extension"). Result, same correctness judge:

| | exp9 (T7 NOT in ledger) | exp9b (T7 IN ledger) |
|---|---|---|
| T7 failures | **27/35** | **0/35** |
| mean correctness | 3.66/5 | **4.94/5** |
| 5/5 runs (per voice) | mostly 1/5 | **5/5** for 5 voices, 4/5 for the rest |

**One ledger line took a 77% cross-method failure to 0%.** This is the hard proof of `[[library-aware-ledger-not-fat-writer]]`: a fact the writer cannot derive from a single method belongs in the ledger, and putting it there fixes it completely — not the persona, not more passes, not a rule. After exp9b nearly every run is fully correct, so the human can harvest on VOICE alone. The cross-method triage (`commenter-r29-triage-trace`) is the production mechanism for finding these. `exp9/{run_gen9.js,run_judge_correct.js,build_report9.py}`, `exp9b/{ledger_t7.md,run_gen9b.js,run_judge_correct_b.js}`. Memory: `[[cross-method-fact-in-ledger-fixes-it]]` (exp9 27/35 -> exp9b 0/35 from one stub line).

### Decisions (user, authoritative) + the production-judge spec
- **Generator = `vf`** (full `vf` discipline verbatim in `exp8/run_gen8.js` / `exp9/run_gen9.js`; the latter's `No showboating.` line must be REMOVED — it was falsified in exp8.5). Harvest best-of-N by **human** pick.
- **Tic target = human-level, not zero.** Future judges flag *abundance* AND suspicious *zero*.
- **Personas: clean, one-clause, parallel.** No rule-work inside a persona (Linus over-description was a confound; trimmed version is the model).
- **NO EXEMPLAR — ship without one (user decision).** This DEMOTES the earlier `[[exemplar-carries-soul-rules-carry-correctness]]` claim: this session showed soul is carried by **voice-first + the named/disposition voice** (not the exemplar), correctness by the **ledger** (exp9b), and the exemplar's only unique job is de-naming the celebrity — which we don't need. Against a no-exemplar baseline that's already 5/5-correct and voiced, an exemplar is a downside-heavy bet (this project has burned on example contamination: copying, content-bleed, round-25 depth-erosion, `[[agent-examples-must-be-neutral]]`). If de-naming is ever needed, use a NEUTRAL exemplar (a different file, never the target) + "own words" rule + a copy/voice-drift A/B before trusting it. The exp3 harvest→bake→install round-trip is RETIRED.
- **Two kinds of judge:** the experiment *ranker* does NOT ship and isn't worth improving (fine-soul ranking is irreducibly noisy; human owns taste). The **shipping** consolidation judge + verifier (in `regen-comments`, agent `commenter-verifier`) must gate the *checkable, high-effect-size* things: **per-symbol correctness/grounding** (must reject the `disable_extension` inversion and pick the grounded candidate, not the eloquent-but-wrong one), **fabrication catch**, **cold-reader legibility**, **tic-density sanity (human-level)**, **cadence-split**. Soul stays advisory + human-owned.
- **Persona-diversity open question:** the 7 personas collapse to ~3 archetypes — casual-explainer (linus, pewdiepie — they literally shared the "head to head" idiom), blunt-engineer (torvalds, cantrill), terse-minimalist (cutler, elon, hemingway). To test whether persona matters past a baseline, run genuinely different registers (Feynman/pedagogue, warm-mentor, deadpan, clinical-clarity, Attenborough/storyteller, a non-tech voice) + a *distinctiveness* judge.

### Architecture direction (user's forward plan, my concurrence)
- **best-of-N passes → merge best-per-symbol** = already the `regen-comments` pattern (N writers → per-symbol judge). Our exemplar/discipline work raises each pass. Two riders: the consolidation judge must verify **correctness** per symbol (not pick richest voice); N-pass-merge doubles as a **fabrication filter** (dilutes single-pass hallucinations); merge within ONE persona's passes for voice coherence.
- **Trap-finder fix** = a **cross-method-tracing triage** (the existing `commenter-r29-triage-trace` is the seed) that catches relationships like the `disable_extension` inversion AND carries **domain identity** (so the writer says "API", not "build").
- **Whole-library vs one-file:** do NOT fatten the writer (kills depth, cost, parallelism, invites banned cross-refs). Make the **grounding layer library-aware**: one broad triage reads the library once → per-file ledger carrying domain identity + cross-file relationships + shared terminology; focused per-file multi-pass writers consume file + ledger; triage traces outward on demand. **The ledger is how a narrow writer gets broad awareness cheaply** — and it fixes the "build/track→API" context gap (an isolation artifact) without giving up depth.
- **`--with-comment-triage` flag (user decision, 2026-06-06; renamed from the misleading `--dont-strip`).** Naming matters here: **the writers are clean-room ALWAYS** — original comments never reach a writer in any mode — so there is no "strip vs don't-strip" axis. The real axis is whether an isolated comment-mining lens runs in the *grounding* stage. **Default (off):** the only inputs are the code (3 code lenses) → ledger → clean-room writers; existing comments are ignored entirely. **`--with-comment-triage` (on):** adds ONE dedicated comment-archaeologist lens — the *only* agent that ever sees the original comments — whose findings feed the ledger like any other lens. The flag widens what the *triage* may mine; it never changes what the writer sees. (Generalizes the existing `commenter-r29-triage-trace` contract: "code is the only source of truth; comments are suspect hints, never lifted.")
- **The comment lens itself = isolated + THREE lanes, not keep-vs-trash (user corrected this 2026-06-06).** Do NOT hand the old comments to the three code lenses (pollutes their clean-room read) — only this one lens reads them (both `#` comments AND docstrings). It triages every existing comment into exactly one of three lanes: **(1) LEDGER** — paraphrase a genuinely valuable *behavioral/domain* fact the code can't reveal (a domain constraint, author intent, a *why*); hard cap **1–2/file, often zero**; never lift wording; if it contradicts the code it is NOT a ledger fact, it's discard. **(2) PRESERVE** — verbatim, kept in the file, never reworded and never fed to a writer to paraphrase: copyright, license, author, and *live* TODO / tracker story refs (e.g. `TODO(PMA-124)`). These are valuable provenance, just not behavioral facts — a preserve-and-reattach lane (in production the obvious header/directive lines preserve mechanically; the lens handles judgment cases). **(3) DISCARD** (with reason): stale archaeology ("used to be a tuple"), redundant-with-code restatements, and *wrong/contradicts-code* comments. The earlier framing that lumped copyright/author/story into "discard" was wrong — those are PRESERVE. Test needs a *commented* fixture (exp12: pure fixture + planted copyright/author/PMA-124 = preserve, a Cep25 domain note BURIED in the wrong method = ledger, a "used to be a tuple"/redundant/`strictly exceeds`-but-code-is-`>=` = discard). **The DISCARD lane is TEST instrumentation only (user, 2026-06-06):** in production the lens emits just LEDGER + PRESERVE — you discard by omission; the discard list has no downstream consumer and does not help the merge. But the lens must still EXAMINE every comment (the coverage discipline aids recall of a buried fact and guards against promoting a confident-but-wrong one).
- **Questionable ledger facts → a human multi-select picker, not auto-include/auto-drop (user, 2026-06-06).** When a lens emits a fact it cannot verify from the code (low/med confidence, external-consumer context, intent it can't ground — e.g. exp12's "ranking feeds an external dashboard"), the skill surfaces those borderline facts to the user via a multi-select `AskUserQuestion` so the human keeps/drops each BEFORE they reach the writers. High-confidence grounded facts (e.g. the Cep25 constraint) flow through automatically; only the questionable ones gate on a human pick. This is the human-in-the-loop checkpoint for the ledger, the same way the writer output is human-picked — judgment the model shouldn't silently make either way.

### NEXT (pending)
1. **(user)** Hand-pick the best `vf` run per voice from exp7/exp8 → I run a judge pass that says what's strong/weak per symbol and where to tweak the persona. (This supersedes the parked exp3 exemplar→bake→install round-trip; the generator is now `vf`, not the baked personas.)
2. Add the `disable_extension` inversion to the trap ledger as a known cross-method gotcha.
3. (forward) Build the library-aware grounding + the correctness-gating production judge into the skill side.
4. **exp10 (2026-06-06) — T7 SURFACED UNAIDED. ✅** Multi-lens autonomous triage probe (3 blind lenses: trap / cross-method trace / naming+domain + a ledger-writer) on the PURE fixture, no hint, no comments. The merged `exp10/ledger_auto.md` carries ALL 7 traps + domain identity; **T7 stated correctly** ("disable_extension=True implies chosen is the extensionless component; flag signals dropping the rejected side's extension, not the chosen's" [trace, naming]). The **trace lens** found T7 (at *med* confidence); **naming lens** gave clean domain identity (API/version, no build/track coinage). Caveats: ledger is over-long (kept derivable single-method facts — told it to bias-keep; prune later), trace's T7 self-confidence is med. New pointer `[[multi-lens-triage-not-one-trap-finder]]`. **LEDGER-WRITER FIX LANDED + VALIDATED (2026-06-06):** after the verbatim-echo finding, edited the lens preamble (record telegraphic FRAGMENTS not sentences) + the ledger-writer (STUB STYLE rule w/ GOOD/BAD example + NO-INVENTED-EXAMPLES rule), re-ran, and an independent validator confirmed the v3 `ledger_auto.md`: **7/7 traps present & correct, T7 no inversion, domain intact, copyable_sentences=[], factual_errors=[]**. The earlier echoed sentence ("dropping the rejected side's extension, not the chosen's") is gone (0 hits); coverage rose 17→21 facts; a fabricated T1 example ("2.1 vs 1.9 -> -8") that the v2 ledger-writer invented was killed by the no-invented-examples rule (v1/v2 backed up in `exp10/_v1_backup/`).
5. **exp11 (2026-06-06) — LOOP CLOSED. ✅✅** Fed the AUTONOMOUS `ledger_auto.md` (no hand-fed hint) to the settled vf writers (7 voices × 5) + correctness judge. Result: **0 T7 failures across all 35 runs**; 6/7 voices a perfect 5/5 (linus, cantrill, cutler, elon, torvalds, pewdiepie); hemingway 4,4,4,4,3 — and its loss is **T1-depth, not T7** (tersest voice states "majors ignored" but not the "cross-major drift meaningless" consequence). MATCHES/beats the hand-fed exp9b (which got 5/5 for 5 voices; pewdiepie improved to 5/5 here). So correctness is **end-to-end autonomous** — the triage found T7 + domain itself and the writers reproduced hand-fed correctness. Subtle lever for hemingway: the auto-ledger's T1 line said "major ignored (99 vs 2 irrelevant)" vs hand-fed "cross-major drift meaningless" — richer voices inferred the consequence, hemingway didn't; **sharpen the ledger line, not the persona**. New pointer `[[autonomous-ledger-closes-the-loop]]`.
6. **exp12 (2026-06-06) — COMMENT LENS PASSED. ✅** The `--with-comment-triage` lens on a deliberately messy fixture (buried + misplaced Cep25 fact, copyright/author/PMA-124, 24 noise/wrong/redundant comments). It **found the buried Cep25 fact** (inside `_higher_ranked`, the wrong method, past an "I never found a tidier place" misdirection), **paraphrased not lifted** (`why_non_derivable` correct); **preserved** copyright/author/PMA-124 verbatim; **discarded** all 24 noise items with right categories — critically flagging the 3 *wrong* comments (incl. "strictly exceeds" vs code's `>=`) as `wrong-contradicts-code` and NOT lifting them. One judgment call: it also mined a *med-confidence* 2nd fact ("ranking feeds an external dashboard") from a line planted as noise — defensible recall but unverifiable; lean DROP from the writer ledger. **Still pending: bake the merged ledger (`ledger_auto.md` + Cep25 [± dashboard]) and run a subset of writers to confirm Cep25 flows in + no cruft leaks** (awaiting user's dashboard in/out call). New pointer `[[comment-lens-three-lane-triage-works]]`.
7. **Skill requirement:** `regen-comments` takes `--with-comment-triage` (off by default; on = add an isolated comment-mining lens to grounding. Writers are clean-room either way). See Architecture direction bullet.
CLAUDE.MD CLEAN-ROOM (researched 2026-06-06, claude-code-guide + local + reasoning):
   - **Subagents DO inherit project `CLAUDE.md`** — general-purpose and custom both; only built-in Explore/Plan skip it (and those are read-only, so writers can't be them). Source: code.claude.com/docs/en/memory, /sub-agents, /agent-sdk/subagents.
   - **Load order:** managed-policy(org) -> `~/.claude/CLAUDE.md`(global) -> project ancestry (walked UP from cwd, parent-before-child, `CLAUDE.local.md` appended) -> subdir CLAUDE.md (on-demand when a file in that dir is read) -> `MEMORY.md` auto-memory. All concatenated.
   - **KEY: project memory loads by the AGENT'S CWD ancestry, not by where the read file lives.** So copying the target into `/tmp` is NOT enough; the agent's cwd must be OUTSIDE the repo. The in-session **Workflow tool can't do this** (`agent()` has no cwd arg; `isolation:'worktree'` is still a worktree OF the repo, CLAUDE.md present).
   - **Clean-room levers:** no `--no-memory` CLI flag; `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`/`autoMemoryEnabled:false` only kills MEMORY.md not CLAUDE.md; **Agent SDK `setting_sources=[]` loads ZERO CLAUDE.md/settings/rules (the clean mechanism)**; OR headless `claude -p` launched with `cwd=/tmp/cleanroom` (skips project memory; user-global still loads). Verify the exact env/settings keys before relying on them.
   - **USER DECISION (2026-06-06): scope the engineering to PROJECT CLAUDE.md (neutralize it); USER-GLOBAL CLAUDE.md is out of scope -> a skill WARNING ("your personal CLAUDE.md may influence comments") suffices. Managed-policy likewise warn.**
   - **IMPLICATION: the production writer stage probably is NOT the in-session Workflow tool — it shells out** (SDK `setting_sources=[]`, or headless `claude` from a clean cwd). This matches the user's "code the agents into the workflow/JSON, not `.claude/agents` files" hunch and also solves the voice-multiplication (voices = data, one templated writer). New pointer `[[project-claudemd-needs-clean-cwd-shellout]]`.
   - Probe staged (`clauderoom_probe.js` + sentinel) but must run in a FRESH session (this session had `.claude/agents` access disabled by the user to kill variables, so it is not representative).
   - **PROVEN 2026-06-06 via `claude -p` subprocess (the chosen production mechanism):** staged `/tmp/regen-cleanroom/` (stripped code + ledger), ran headless `claude -p` from there. Knowledge-injection test (secret planted in a CLAUDE.md): (A) cwd CLAUDE.md present -> model returns the secret = `claude -p` DOES load cwd-ancestry CLAUDE.md; (B) `/tmp` clean room (no CLAUDE.md ancestry) -> `NONE`, zero awareness. Then tested the REAL project file: planted a secret in the repo `./CLAUDE.md`, ran `claude -p` from the project dir (control: model SAW it, called it an injection probe -> loading confirmed) vs from `/tmp/regen-cleanroom` (clean room: `NONE`, no awareness). **`/tmp` clean room is isolated from project memory. CONFIRMED.**
   - **IMPORTANT: the committed `./CLAUDE.md` in chumicro is literally `@AGENTS.md`** (an include) — so on a real checkout, project memory = the whole AGENTS.md by reference, a large poison surface; the `/tmp` clean room avoids it. (The user keeps their local working copy emptied to 1 byte to disable that include; a `git checkout` re-enables it — do NOT `git checkout CLAUDE.md`.)
   - **PRODUCTION WRITER STAGE = headless `claude -p` launched with `cwd=/tmp/regen-cleanroom`** (copy stripped code + ledger in; voices are data passed per-invocation), NOT the in-session Workflow tool. `macOS has no \`timeout\`; don't wrap claude calls in it.` Open engineering: tool-permission flags for `claude -p` to Write the output file (or have it print to stdout and capture), model selection, and fanning out N voices x M passes as parallel subprocesses. New pointer `[[claude-p-from-tmp-is-the-clean-room]]`.
   - **LAYERED CLEAN ROOM (user, 2026-06-06) — clean room is for EVERY code-reading/judging agent, not just writers.** A triage lens poisoned by AGENTS.md mis-describes the code as badly as a poisoned writer. Architecture: **ORCHESTRATOR stays in-session** (project CLAUDE.md poison is harmless — it never judges code; it only copies the file in, MECHANICALLY STRIPS it (deterministic, no LLM, no room needed), provisions rooms, launches `claude -p` per layer, runs the AskUserQuestion picker between triage and writing, assembles the final ledger, MECHANICALLY REATTACHES preserve, presents). **CLEAN ROOMS (`claude -p` from /tmp): Room C** holds the COMMENTED file = comment lens ONLY; **Room S** holds the STRIPPED code (ledger added post-picker) = code lenses + ledger-writer + writers + consolidation/verify judges. "Writers can't see the comments" is enforced BY CONSTRUCTION (the commented file isn't in Room S), not by instruction. The split may fan into more rooms per layer; fine, as long as each room contains only what that layer may see. New pointer `[[clean-room-every-code-reading-layer-not-just-writers]]`.
   - **CONFOUNDED TEST (2026-06-06) — do Workflow agents inherit project CLAUDE.md? STILL OPEN.** Same-session knowledge-injection test: sentinel planted MID-SESSION in `./CLAUDE.md`; `claude -p` from the project dir returned the secret (it is a fresh process, re-reads CLAUDE.md from disk), but the Workflow `general-purpose` agent returned `NONE`. The `NONE` is INCONCLUSIVE: this session STARTED with an empty CLAUDE.md, so it cannot distinguish (a) Workflow agents skip CLAUDE.md from (b) Workflow agents inherit the PARENT session's startup-loaded memory (empty at my startup) and never see a mid-session edit. **Valid test = a FRESH session with the sentinel pre-planted BEFORE launch, then run the Workflow probe (`clauderoom_probe.js`); secret -> Workflow inherits (claude -p needed), NONE -> genuinely isolated.** (user to run; user caught the confound.) Decision does NOT hinge on it: the Workflow tool gives NO file-access isolation (an agent in session cwd can Read any project file incl. the commented original), whereas `claude -p` + /tmp rooms enforce "writers see only stripped code" by construction. **Decision stands: `claude -p` from /tmp is the production clean room** (documented CLAUDE.md isolation via cwd-ancestry + file-access isolation via room contents). Note: exp10-13 cleanliness is assured by the empty CLAUDE.md regardless of which hypothesis holds.
   - **PROGRESS (2026-06-06): clean-room `claude -p` trace lens WORKS.** Ran the validated trace-lens prompt via `claude -p` from `/tmp/regen-cr/roomS` (stripped code only): found T7 correctly ("disable_extension=True refers to extension of the LOSING extended comp, NOT chosen") among 9 telegraphic findings. Working invocation: `claude -p "$PROMPT" --allowedTools Read Write --permission-mode acceptEdits --model opus` (bypassPermissions is unnecessary + classifier-blocked; acceptEdits + an explicit allowlist runs non-interactively and lets it write its findings JSON into the room). Quality holds headless. Next: a `claude -p` WRITER, then wire the in-session orchestrator (strip -> rooms -> claude -p lenses/ledger/writers/judges -> picker -> reattach).
   - **`claude -p` WRITER also PROVEN (2026-06-06):** cantrill writer via `claude -p` from Room S (stripped code + ledger) produced correct output (`bravo True/alpha False`), executable code AST-identical, Cep25 carried, T7 right ("disable_extension True only when the extension-bearing candidate was rejected"), voice intact. Both clean-room layers (triage lens + writer) now validated headless.
   - **A SINGLE `claude -p` CANNOT run the whole pipeline — the mid-flight AskUserQuestion gate rules it out (user, 2026-06-06).** Headless `-p` is non-interactive: no channel to surface the picker back to the user and wait. So the architecture is PHASED: the **in-session orchestrator is the only interactive layer** (owns the picker, presentation, mechanical strip/reattach) and runs the clean-room `claude -p` phases AROUND the gate (Phase 1 triage -> picker -> Phase 2 writers+judges). Clean-room agents are non-interactive BY DESIGN: a lens that is unsure emits `confidence: low/med`, which flows up to the orchestrator's picker — uncertainty becomes gate-able DATA, never an interactive question. New pointer `[[headless-cant-ask-so-orchestrator-owns-the-gate]]`.
   - **PICKER PLACEMENT (user Q, 2026-06-06): AFTER the ledger-writer, SUBTRACTIVE on clean stubs.** Order: lenses -> ledger-writer writes the FULL provisional ledger (all facts, questionable ones flagged low/med/comment-derived) -> picker -> orchestrator DROPS the rejected questionable facts -> final ledger. Subtractive ("drop rejected") == additive ("high-confidence auto-kept + kept-questionable") -> same final ledger; mechanically it deletes the rejected `- ` lines (exactly the exp13 `__main__`-drop). Ledger-writer FIRST is deliberate: the human judges polished/deduped/telegraphic stubs, not raw pre-merge lens fragments. High-confidence facts never reach the picker (auto-kept); only low/med/comment-derived do. The PRESERVE lane has its own small keep/drop pick (e.g. the FIXME) and is reattached mechanically at the very end. The ledger-writer is the LAST step of the triage `claude -p` (phase 1); the picker is in-session between phases; the writer `claude -p` (phase 2) reads the FINAL ledger.
   - **exp14 `cr_triage.py` BUILT + VALIDATED (2026-06-06):** Python orchestrator for the whole grounding phase — per-lens `/tmp` rooms (parallel `claude -p` must not share a cwd/output file), comment lens in Room C, ledger-writer in a ledger room reading staged findings. RAN clean-room end-to-end: 15-fact provisional ledger, ALL 7 traps correct (T7 right), Cep25 carried + tagged comment-derived, 2 questionable auto-routed to picker, 4 preserve, no lens errors. The full grounding phase works clean-room + parallel via `claude -p`. (`cr_write.py` writer+judge fan-out also built.)
   - **DECISION (2026-06-06): production substrate = ~2 `claude -p` runs, each running a VALIDATED WORKFLOW internally — NOT N subprocesses.** TESTED + CONFIRMED: a headless `claude -p` CAN invoke the Workflow tool and run it to completion (workflow's agent wrote its file, `claude -p` reported success before exiting — no orphaning). So: in-session orchestrator copies files to `/tmp`, launches **one `claude -p` from `/tmp` running the triage workflow** -> provisional ledger -> **picker (in-session)** -> assemble final ledger -> **one `claude -p` from `/tmp` running the writer+judge workflow** -> reattach -> present. Reuses the exp10-13 workflow scripts (native parallel/schema/journal). **This MOOTS the Workflow-`CLAUDE.md` confound**: the workflow's agents run under a `/tmp`-launched parent, so they are clean under BOTH inheritance hypotheses (fresh-from-cwd = /tmp = none; inherit-parent = /tmp parent = none). `cr_triage.py`/`cr_write.py` (N-subprocess) demote to FALLBACK. Working `claude -p` flags: `--allowedTools Workflow Task Read Write --permission-mode acceptEdits --model opus`. New pointer `[[claude-p-runs-workflows-so-two-runs-suffice]]`.
   - **CAPSTONE (2026-06-06): full triage WORKFLOW ran inside ONE `claude -p` from `/tmp` — substrate validated end-to-end.** Repathed `run_triageA.js` to `/tmp/regen-cr/cap`, launched one `claude -p` from there to run it (5 nested agents, ~118s, completed cleanly): 17-fact ledger, all 7 traps present, Cep25 carried (med), 4 preserve + 22 discard, 2 questionable. So: in-session orchestrator -> one `claude -p` from /tmp -> Workflow -> lenses+ledger-writer -> correct clean ledger WORKS. **CAVEAT (honest): this run's T7 line stated the trigger ("disable_extension=True when base_only wins") but NOT the explicit inversion ("dropped ext = LOSER/extended side, never winner") that exp10/exp13/`cr_triage.py` runs had — run-to-run VARIANCE on the hardest fact, not a substrate defect.** Mitigation already built: put **`run_validate.js`** (the independent 7-trap ledger validator) INSIDE the triage phase after the ledger-writer (flag/re-run if T7 under-specified), plus the downstream correctness/consolidation judge catches T7 inversions in writer output. Two nets for T7. New pointer `[[ledger-quality-varies-validate-T7-in-phase]]`.
   - **ALL STAGES VALIDATED + SKILL WRITTEN UP (2026-06-06).** Under `exp14_cleanroom/`: **`strip.py`** (mechanical comment/docstring stripper, line-surgery not ast.unparse; tested -> AST-identical to canonical stripped, runs `bravo True/alpha False`); **`reattach.py`** (preserve-and-reattach, tested); **`voices.json`** (voice registry — voices are DATA, one templated writer, add entries not agent files); **`SKILL.md`** (full validated pipeline). Stages all green: triage-workflow-in-`claude -p` (capstone 7/7 traps + Cep25), ledger validator (catches weak T7: 7/7 correct but `t7_explicit:false`), writer-workflow-in-`claude -p` (capstone: cantrill r2 / linus r1 / hemingway r2, ALL passes 5/5), and **PER-SYMBOL CONSOLIDATION** (merge best docstring+comments per method/class across passes -> mixed `Component`+`__init__` from run3, rest run2; code AST-identical, Cep25 carried, 10 symbols). New pointer `[[per-symbol-consolidation-merges-across-passes]]`.
   - **REMAINING WIRING (not blocking — components validated, just assembly):** (a) PARAMETERIZE the workflow scripts (`triage_wf.js`/`writers_wf.js` are repathed copies of exp13 `run_triageA.js`/`run_writersB.js` with hardcoded `/tmp` paths -> make paths args/relative); (b) FOLD per-symbol consolidation INTO `writers_wf.js` (it currently uses the exp13 per-PASS judge; swap to the validated per-symbol consolidation prompt); (c) make the judge prompt PASSES-aware (hardcoded `run-3` ref); (d) build the TOP-LEVEL orchestrator that chains strip -> triage `claude -p` -> validate -> picker (AskUserQuestion) -> assemble final ledger -> writer `claude -p` -> reattach -> present; (e) a real tokenize edge: strip.py handles docstring-only bodies via `pass`-insertion but verify on real chumicro files.
   - **CONTAMINATION DISCIPLINE — the SKILL must be FIXTURE-AGNOSTIC (user caught a leak, 2026-06-06).** `t7_explicit` and "the 7 traps" are TEST INSTRUMENTS (we know `quality_ranking.py`'s ground-truth traps, so the test validator/judge can grade whether the GENERIC pipeline captured them — same as the exp9 correctness judge). They must NEVER appear in the production skill. The production **ledger validator is fixture-agnostic**: per-fact correctness against the code + explicitness of correctness-critical *classes* (returned-flag referent, inversion, dual-role, boundary) — NO trap list, NO `t7_explicit`, NO file-specific knowledge. Leaks found + fixed: SKILL.md Step 2 said "every known trap" / "`t7_explicit`" (rewritten generic); `reattach.py` HARDCODED the fixture's preserve lines (`Acme Robotics`/`J. Tanaka`/`TODO(PMA-124)`) -> rewritten to read a `preserve.json` (the comment lens's actual preserve lane). New pointer `[[skill-must-be-fixture-agnostic-no-trap-list]]`.
   - **SCAN (2026-06-06): production artifacts CLEAN, workflow scripts still TEST-CONTAMINATED.** `SKILL.md`/`voices.json`/`strip.py`/`reattach.py` = 0 fixture-token hits. But the WORKFLOW scripts (`triage_wf.js`/`writers_wf.js` = repathed exp13 `run_triageA.js`/`run_writersB.js`, and the `cr_*.py` twins) carry baked test knowledge: (1) the ledger-writer STUB-STYLE GOOD/BAD example uses the fixture's own symbols (`disable_extension`/`base_only`) -> violates `[[agent-examples-must-be-neutral]]`; production needs a NEUTRAL invented example teaching the FORM of a telegraphic inversion stub; (2) the consolidation/verify JUDGE hardcodes the 7 fixture traps (`JUDGE_TRAPS`/`TRAPS` incl. disable_extension/Cep25/popcount/drift) -> production judge must be GENERIC (verify each claim against the code + confirm must-carry facts FROM THE LEDGER survived + flag cruft-leak/ledger-lift; NO trap list). These worked on the fixture partly BECAUSE example/traps matched it (fine for measuring, would bias/break on real code). The exp13 scripts are EXPERIMENT versions; production workflow scripts must be genericized to match the (clean) SKILL.md descriptions, then validated on the real-file finale.
   - **SKILL FULLY DEFINED (2026-06-06).** Package in `exp14_cleanroom/`: `SKILL.md` (full pipeline), `PLAN.md` (build & rollout — status table, genericization checklist §2, orchestrator §3, `--create-voice` §4, verifier §5, library-aware finale §6, multi-file §7, install §8, OPEN QUESTIONS §9, anti-contamination invariant §10), `voices.json`, `strip.py`, `reattach.py`. **Decisions locked (user):** ONE voice per run; a 4-voice pick menu (`cutler` default, `elon`/`cantrill`/`hemingway`) with `--voice <key>` for any other; a `--create-voice` registry-add mode (no generation); `--with-comment-triage` (default off); **4 passes**; **all opus**; **finalize as a package, DON'T install yet**. Remaining build = PLAN §2 (genericize the 2 workflow-script leaks) + §3 (top-level orchestrator) → then §6 finale on a real chumicro lib (validates genericized scripts + library-awareness). **Finale targets CHOSEN (user): `timing/ticks.py` (single-file sanity for the genericized scripts) then `kvstore/` (8-file library-aware finale: core + 4 backends sharing a contract). Other PLAN §9 items have defaults, decided when reached.** New pointer `[[regen-comments-skill-defined-in-exp14]]`.
   - **GENERICIZED + §6a REAL-FILE RUN DONE (2026-06-06). ✅✅✅** Built the fixture-agnostic production workflow scripts (`exp14_cleanroom/`): `triage_wf.js` (neutral stub example, RUNDIR-parameterized), `writers_wf.js` (ONE voice, 4 passes, GENERIC per-symbol consolidation, no trap list, RUNDIR+VOICE_PARA), `ledger_validate.js` (fixture-agnostic gate). All grep-clean of fixture/example tokens. Ran the WHOLE pipeline on real `libraries/timing/.../ticks.py` (53 LOC stripped): triage -> clean 19-fact ledger w/ sharp domain id ("wrapping 29-bit MicroPython tick counter") + real subtle facts (both-ends-exclusive ticks_add guard, asymmetric ticks_diff range, tie-toward-past sign-fold, misleading OverflowError msg, `-> object` returns a callable); **the GENERIC validator (no trap list) caught 2 real over-claims** (over-broad "ONLY" on masking + TICKS_PERIOD use) -> fix-loop corrected them; writers (cutler, 4 passes) -> **per-symbol consolidation MIXED across passes** (module/ticks_ms/ticks_add run4, TICKS_MAX/HALF/_raw/ticks_diff run3, TICKS_PERIOD run1) -> `merged.py` code AST-identical, all hard facts in cutler voice. Preserve lane empty (ticks.py has no headers) so reattach = no-op. Saved `exp14_cleanroom/ticks_regenerated.py`. **Proves the fully-genericized clean-room pipeline produces production-quality docstrings on REAL chumicro code it has never seen.** New pointer `[[genericized-pipeline-validated-on-real-ticks-py]]`. NEXT: §6b `kvstore` library-aware finale (broad triage -> library ledger -> per-file across 8 files; the library-ledger shape needs design/sign-off per PLAN §6).
   - **HUMAN-SCALE-CONSTANT GAP found + fixed (user caught, 2026-06-06).** The regenerated `ticks.py` dropped the original's "~6.2 days" (the full 2^29 ms wrap period in human terms) — kept "~3.1 days" for `ticks_diff` but lost the wrap-period-in-days. Root cause: a human-scale reading of a raw constant is "computable but not glanceable" — fell between the comment lens (dropped it as derivable) and the writer (did not compute it). The `[[human-scale-sizes-of-raw-constants]]` class. FIX: added to `triage_wf.js` PREAMBLE a directive to capture the human-scale reading of any raw real-world constant (duration/size/count), NEUTRAL example (no 2^29/6.2-days baked in). (User separately verified the `2^28` references in ticks docstrings are CORRECT: `TICKS_HALFPERIOD = PERIOD//2 = 2^28` is the operative bound in `ticks_add` (±2^28 delta) and `ticks_diff` (fold + range), faithful to code + original.) §6a finale earned its keep: only real code (with a human-scale constant) surfaced this; the synthetic fixture had none.
   - **§6b LIBRARY LEDGER VALIDATED (2026-06-06). ✅** Built a broad-library-triage `claude -p` over the 8 kvstore files -> excellent `LIBRARY_FACTS.md`: DOMAIN (KV store for reboot-surviving runtime state, not config/db), CONTRACTS (the `Backend` ABC in core.py — load/save/capacity + exceptions + the capacity invariant — implemented by all 4 backends, consumed by KVStore via `_resolve_backend`; the exception hierarchy + "corruption only from explicit reload" invariant; the msgpack payload contract; FakeKVStore subclassing), GLOSSARY (substrate/slab/CKVS-framing/capacity-defaults/commit-vs-persist/wear/atomicity/is_corrupt/runtime-selection). Made `triage_wf.js`+`writers_wf.js` library-aware (conditional: consult `LIBRARY_FACTS.md` for cross-file context, per-file code still source of truth). Running the `cp_nvm.py` per-file library-aware pipeline to prove the cross-file context lands in a backend's docstrings (Backend contract + glossary). New pointer `[[library-ledger-carries-the-cross-file-spine]]`.
   - **§6b LIBRARY-AWARENESS PROVEN END-TO-END (2026-06-06). ✅✅✅** Ran the FULL library-aware pipeline on `cp_nvm.py` (a kvstore backend, the hardest case): broad library triage -> `LIBRARY_FACTS.md` -> per-file [strip -> triage WITH library ledger in room -> keep-all picker -> cutler writers WITH library ledger -> per-symbol consolidation] -> `cpnvm_regenerated.py`. The output is library-aware in ways NOT derivable from cp_nvm.py alone: declared/framed as a `Backend` subclass, carries the cross-file exception contract (`load`->`KVStoreCorrupt`, `save`->`KVStoreFull`, WITH the why), uses the library glossary (slab/CKVS-framing/blank-slab/capacity invariant), AND captures real cp_nvm subtleties (the `_acquire_runtime_nvm` no-copy/no-lock misnomer, two-slice-write atomicity + partial-frame-on-power-loss, the uncaught OverflowError when payload>65535 still fits capacity). Code AST-identical, cutler voice, every param documented. Saved `exp14_cleanroom/cpnvm_regenerated.py`. **The ENTIRE skill is now validated end-to-end on real chumicro library code with library-awareness.** New pointer `[[library-awareness-lands-in-the-output]]`. Remaining 7 kvstore files: **user chose STOP — validation complete (2026-06-06).** The other files would be mechanical deliverable production, no new validation. **The regen-comments skill is now BUILT + VALIDATED END-TO-END on real chumicro code (single-file ticks.py + library-aware cp_nvm.py).** Only remaining work is the eventual INSTALL (PLAN §8, deferred by user: "finalize as a package, don't install yet") + the wiring polish in PLAN §3 (the in-session orchestrator was exercised manually this session; a thin driver could formalize it). Package complete in `exp14_cleanroom/`: SKILL.md, PLAN.md, voices.json, strip.py, reattach.py, triage_wf.js (human-scale + library-aware + neutral example), writers_wf.js (per-symbol consolidation, library-aware), ledger_validate.js (generic), + the broad-library-triage approach, + 2 finished example outputs (ticks_regenerated.py, cpnvm_regenerated.py).
   - **INSTALLED + COMMITTED (2026-06-06).** Skill installed at `.github/skills/regen-comments/` (9 files: SKILL.md [replaced the old 26KB one], PLAN.md, voices.json, strip.py, reattach.py, triage_wf.js, writers_wf.js, ledger_validate.js, library_triage.md) — commit `3daf6981`. The 4 handoffs committed `f51f8b52`. The 86 experiment `commenter-*` agents were UNTRACKED scratch in `.claude/agents/`; backed up to `.scratch/agents-backup-2026-06-06/` (gitignored, out of git) — NOT deleted; restore any from there (the production agents commenter-verifier/judge/casual-friendly stay committed). `CLAUDE.md` (user keeps it emptied to disable the `@AGENTS.md` include) and `.idea/chumicro.iml` left as LOCAL working state, intentionally uncommitted — do NOT commit or `git checkout` them. Repo clean otherwise. (Bash safety classifier flickered during this; the install was completed once it stabilized.) **NEXT: fresh-session TEST RUNS of `/regen-comments` (single-file first, then `--with-comment-triage`, then library-aware on kvstore) -> user-led BUG HUNT.** New pointer `[[regen-comments-installed-2026-06-06]]`.
   - **POST-INSTALL WIRING + AUDIT (2026-06-06, autonomous hour).** Closed the orchestration-wiring gaps: triage now persists `ledger.json` (structured facts+confidence for the picker); built `regen_phase1.py` (strip->triage `claude -p`->validator->emit questionable+preserve) + `regen_phase2.py` (writers->per-symbol consolidation->reattach), each launching ONE `claude -p` that runs a workflow JS; added a literal **Runbook** to SKILL.md (the picker is the one in-session pause between phases). BOTH drivers validated end-to-end on real `heartbeat.py` (commits `fd43f72f`/`bc003af3`). Spot-tested reattach (real preserve lane) + strip (`pass`-insertion). Ran **`audit-skill`** (5 readers, NO CRITICAL -> inline-fix not re-author). FIXED + committed: `voices.json` default cantrill->cutler (load-bearing), dead `validate_wf.js` probe, exp10/12/13 provenance in shipped `triage_wf.js`. **OPEN audit findings for user sign-off (next session):** (1) library-aware mode HALF-WIRED — Runbook has no library step, `--lib` consumes but nothing produces `LIBRARY_FACTS.md`, and the consolidation judge is BLIND to it; (2) validator convergence loop unimplemented (no ledger-writer-only re-run path); (3) preserve lane silent in default mode (headers dropped without `--with-comment-triage`); (4) `PLAN.md` stale (says EXPERIMENT/deferred, contradicts installed state); (5) polish: description impl-leak, voice-menu no preview, no SendUserFile, --create-voice plain-prompt. IDEAS: idempotency check, parallel-voices-off-one-ledger (goal change), SendUserFile diff+apply, carve --create-voice. New pointer `[[regen-comments-audit-open-findings]]`.
8. **PRESERVE-AND-REATTACH — BUILT + verified in exp13 (2026-06-06).** `exp13/reattach.py`: deterministic, no LLM. Headers (copyright/author) → top; live `TODO(PMA-124)` → after the module docstring (its original spot); FIXME omitted (picker dropped it). A writer never rewords these. Verified: all 3 finished files carry copyright+author+PMA-124, none carry FIXME.
9. **exp13 (2026-06-06) — FULL SINGLE-FILE SKILL, END TO END. ✅✅✅** Ran the whole `regen-comments` pipeline on the commented fixture with `--with-comment-triage`: strip → 3 code lenses + comment lens → ledger-writer → **live human picker** (AskUserQuestion multi-select: kept Cep25 + flags-never-enforced, dropped __main__ note + the FIXME) → 9 writers (cantrill/linus/hemingway ×3) → per-voice consolidation+verify judge → reattach → 3 finished files (`exp13/final/`). **Every finished file: runs to `bravo True/alpha False`, executable code AST-identical to the original, all 7 traps correct, Cep25 carried, copyright/author/PMA-124 reattached, no cruft leak.** Two findings: (a) the end-to-end run CAUGHT A MERGE BUG isolated tests couldn't — the ledger-writer tried to "ground" the comment-derived Cep25 fact in the stripped code, failed, and wrote "cannot ground" noise; fixed with a "comment-derived facts are non-code-derivable by design, carry clean" rule, re-ran, clean. New pointer `[[comment-facts-arent-code-verifiable]]`. (b) **must-carry consolidation RECOVERS the soft fact:** run-1 of every voice dropped Cep25 (incl. hemingway, exp12's failure mode), but the judge's must-carry gate picked a Cep25-carrying pass (cantrill r2, linus r3, hemingway r3) every time — best-of-N + must-carry fixes the terse-voice drop. New pointer `[[must-carry-gate-recovers-soft-facts]]`. Residual: linus's "head to head" idiom (known `[[game-show-idiom-is-code-induced]]`, verifier-flag).

## Memory pointers (do not duplicate)

`[[cold-write-loses-facts]]` (now carries the round-20 verdict), `[[no-docstring-bodies]]`
(provisional; body-rule is its retirement path), `[[read-prose-before-judging]]` (read every line as
prose before any quality verdict), `[[agent-examples-must-be-neutral]]`, `[[ai-tic-actual-list]]`,
`[[specific-persona-resists-aitic-drift]]`, `[[docstring-body-placement]]`,
`[[triage-is-the-depth-ceiling]]`, `[[natural-disposition-over-rules]]`.

New from 2026-05-31 exp1/exp2: `[[tics-are-systemic-not-naming]]`,
`[[voice-needs-corpus-depth-and-domain-fit]]`, `[[hard-tics-are-grounding-induced]]`
(explaining a subtle invariant summons load-bearing/antithesis regardless of persona or ledger form,
so the bans+exemplar layer is mandatory), `[[ledger-transfers-grounding-without-copy]]`
(stub/abstract ledger -> 6/6 incl. the hardest traps, n-gram copy ~0 under a "your own words" rule),
`[[abstraction-doesnt-break-comprehension]]`, `[[cadence-tics-are-a-voice-constant]]`.

New from 2026-05-31 exp3/exp4: `[[ledger-is-the-grounding-engine]]` (6/6 on all 102 arms regardless of
ruleset, even with the read-code block removed), `[[bans-are-the-tic-engine]]` (only the prohibitions
control tics; no single rule load-bearing, the whole block is), `[[rules-dont-reliably-move-soul]]`
(disciplined-ruleset soul flat at 4.0-4.6 within run noise; format-bans soul-win FALSIFIED by the 7-voice
confirm), `[[exemplar-carries-soul-rules-carry-correctness]]` (production design: rules for correctness/tics,
harvested+hand-edited exemplar for voice), `[[harvest-from-rich-not-flat]]` (bans flatten prose and drop the
mental-model overview; harvest the rich no-rules output and hand-strip tics), `[[no-the-opener-is-free]]`,
`[[workflow-args-dont-reach-scriptpath]]` (hardcode config or use inline script, not args+scriptPath).

New from 2026-06-04 exp5–exp8: `[[colon-is-a-displaced-tic]]` (banning em-dash while suggesting a colon
pushes the tic to colons; reword the em-dash rule + ban colon-as-pause), `[[coinage-is-a-code-naming-problem]]`
(invented nouns like build/track come from the code withholding domain identity, e.g. a `disable_v2` verb with
no noun; fix the CODE's identifiers or carry identity in the ledger, NOT a rule — and keep the ledger
identifier-only), `[[voice-first-is-the-soul-lever]]` (won 5/7; reversed the cadence-as-downside misread),
`[[cadence-counter-measures-soul]]` (the cadence-tic count conflates empty filler with genuine voice; only
empty framing is a tic; don't minimize cadence), `[[run-noise-swamps-rule-effect]]` (run-noise = 57–70% of
rule-effect, judge disagreement up to 13/14 ranks; trust deterministic mechanical metrics, distrust soul-rank
arm comparisons), `[[no-tics-is-a-warning-sign]]` (target human-level tic density, not zero),
`[[enum-members-are-not-parameters]]` (document-every-param misfires on enums and forces fabrication; carve
enums out + keep a never-invent rule), `[[game-show-idiom-is-code-induced]]` (a pairwise-pick pulls contest
idioms from casual voices ~1-2/run regardless of persona reframe; NO validated fix — persona reframe
failed 5/5, terse "No showboating." rule FALSIFIED at n=5 exp8.5; handle via verifier-flag/hand-edit),
`[[only-deterministic-metrics-can-be-ab-tested]]` (run noise swamps n=1; A/B only countable things like
idiom/tic/fabrication counts with replication, never soul; exp8.5 killed a rule the exp8 n=1 probe "passed"), `[[production-judge-gates-correctness-not-soul]]` (ship judges that gate per-symbol
correctness/fabrication/legibility/tic-sanity; soul stays human-owned), `[[library-aware-ledger-not-fat-writer]]`
(give a narrow writer breadth via a library-aware grounding ledger; never feed the whole library to the writer),
`[[disable-extension-inversion-7th-trap]]` (`PickResult(base_only, True)` — winner has no extension, the
disabled one is the loser's; writers invert it), `[[cross-method-fact-in-ledger-fixes-it]]` (exp9->exp9b:
adding ONE cross-method stub line to the ledger took the T7 inversion from 27/35 failures to 0/35, mean
correctness 3.66->4.94 — the hard proof that cross-method facts belong in the ledger, not the persona).

New from 2026-06-06 exp10 (triage build): `[[comment-triage-is-an-opt-in-lens]]` (writers are clean-room
ALWAYS — comments never reach a writer — so the flag is not "strip vs don't-strip"; it is `--with-comment-triage`,
which adds ONE isolated comment-archaeologist lens to the GROUNDING stage. That lens is the only agent to read
the old comments, has a hard cap of 1–2 non-derivable facts/file (often zero), pulls intent/domain/why, never
lifts wording, discards "phase 2"/"code used to exist"/dead-code/stale-TODO cruft; its findings feed the ledger
like any other lens), `[[multi-lens-triage-not-one-trap-finder]]` (T7 is NOT a trap — it is a cross-method
referential fact; a single gotcha-hunting triage structurally can't see it. Run DIFFERENT LENSES not the
same prompt N times: trap/gotcha + cross-method value-tracer ("what does each crossing value REFER TO at
consumption") + naming-vs-behavior/domain → a ledger-writer merges. Anti-overfit: add a general lens, never
a "look for inversions"/"check disable_extension" rule), `[[autonomous-ledger-closes-the-loop]]` (exp11:
feeding the multi-lens triage's OWN ledger to the writers reproduced the hand-fed correctness — 0/35 T7
failures, 6/7 voices 5/5 — so correctness is end-to-end autonomous, no human hand-feeding the trap; the one
laggard voice (hemingway, terse) was fixable by sharpening the LEDGER's T1 consequence line, not the persona),
`[[comment-lens-three-lane-triage-works]]` (exp12: the opt-in comment lens found a buried+misplaced domain
fact and paraphrased it, preserved copyright/author/tracker-ref verbatim, and discarded 24 noise items incl.
flagging 3 wrong comments as contradicts-code without lifting them — three lanes ledger/preserve/discard, the
last being test-only instrumentation), `[[precise-stub-gets-echoed-verbatim]]` (exp11/12 leakage scan:
writers reword soft facts freely but ECHO the correctness-critical stub near-verbatim — "the rejected
side's extension" leaked into 16/35 exp11 runs, longer T7 fragments in ~6. Rewording the inversion risks
breaking it, so writers quote the ledger's tight phrasing. NOT plagiarism — the ledger is our own
paraphrase, original-comment lift stayed zero — but it COLLAPSES VOICE on the load-bearing sentence. Fix:
write correctness-critical ledger stubs telegraphically/fragmentary, NOT as a fluent copyable sentence —
e.g. `disable_extension -> drops LOSER's ext; winner=base_only has none`, not "flag signals dropping the
rejected side's extension, not the chosen's". The exp10 ledger-writer let the T7 line get too sentence-like;
the "terse stub, never copyable prose" rule needs harder enforcement on the hard facts specifically),
`[[comment-facts-arent-code-verifiable]]` (exp13: the ledger-writer must NOT try to ground a
comment-derived fact in the stripped code — it isn't there by design; doing so produced "cannot ground"
noise + a wrong line ref. Rule: carry comment-lens facts clean at their given confidence, never annotate
verification failure. Only the full end-to-end run exposed this; isolated lens/ledger tests couldn't),
`[[must-carry-gate-recovers-soft-facts]]` (exp13: terse + even casual voices drop a soft non-derivable
fact like Cep25 in ~1/3 of passes, but a consolidation judge that treats non-derivable ledger facts as
MUST-CARRY picks a surviving pass every time — best-of-N + must-carry is the production fix for the
terse-voice drop, NOT a persona change), `[[project-claudemd-needs-clean-cwd-shellout]]` (project CLAUDE.md
is inherited by general-purpose subagents and loads from the AGENT'S CWD ancestry, not the read file's
location, so copying the target to /tmp is not enough and the in-session Workflow tool — no cwd arg,
worktree is still in-repo — cannot isolate writers; production writers must shell out to a cwd outside the
repo via the Agent SDK `setting_sources=[]` or headless `claude -p`; user-global CLAUDE.md stays out of
scope as a skill warning per user), `[[claude-p-from-tmp-is-the-clean-room]]` (PROVEN: headless `claude -p`
launched with cwd=/tmp/regen-cleanroom loads NO project CLAUDE.md — knowledge-injection test returned NONE
from the clean room while the project-dir control saw the planted secret. chumicro's committed CLAUDE.md is
`@AGENTS.md`, a big poison surface the clean room avoids. This is the production writer mechanism, not the
in-session Workflow tool. macOS has no `timeout` cmd; never `git checkout CLAUDE.md` — the user keeps it
emptied to disable the @AGENTS.md include).

## Gotchas

- `.claude/agents/` is not git-tracked; agents load only at session start. Dispatch is a fresh session.
- Classifier intermittently denies edits/writes under `.claude/agents/`; retry passes.
- Em-dashes banned in agent files; `grep -c '—'` must return 0.
- Round 21 reuses round-18 `fixing/` + `stripped/` read-only; writers read `stripped/`, triage reads
  `fixing/.../input/`.

## How to rebuild context fast

Read this handoff, then `round-21/RUN.md`, then any two persona files side by side (e.g.
`commenter-r21-elon.md` vs `commenter-r21-attenborough.md`) to see the shared discipline and the
voice-only difference.

---

## SESSION 2026-06-07 — full skill build (steps 1–5), all committed

The skill at `.github/skills/regen-comments/` was completed end-to-end this session. Seven user-driven
design decisions + four mid-build catches, each validated on real code (heartbeat.py, kvstore/cp_nvm.py)
and committed as its own bisectable commit.

**Commits (newest first):**
- `0748651b` voices.json fixture-agnostic hygiene (drop exp13/round-21 tokens)
- `f667bfe2` step 5: create-voice (gen persona -> edit -> test on user target -> save + preview)
- `38612d60` preflight checks the claude CLI's logged-in ACCOUNT (not OS user) — app-login vs CLI-login mismatch
- `4071956d` step 4: refinement loop + preflight + library parallelization
- `ed7f1f43` Step 5 verify wired (tics.py + polish.py) — fixes the "The"-opener leak at generation + backstop
- `b24deded` report polish (collapse ledger, show signatures)
- `908ebfaf` step 3: HTML report + independent summarizer + voice previews
- `b8127a88` step 2: library-aware mode (phase 0 cross-file ledger ride-in)
- `83d19128` step 1: comment-triage default-ON (--without-comment-triage), always-on header preserve,
  validator folded into triage_wf.js with ledger-writer retry loop, NOTE(<initials>): attributed notes

**Decisions locked this session:** comment-triage default ON; mechanical copyright/header preserve always
on; validator re-run loop (≤4) then needs_user escalation; library mode = dir input (no --lib for user),
LIBRARY_FACTS.md is a cross-file ledger, lenses DEFER to it, writer/judge emit only where touched; one voice
per run; report = independent summary + ledger + per-symbol before/after + rationale, write-back to working
tree on confirm (never commit); refinement loop off the report (roll-dice cheap-cycle -> fresh, drop/edit/add
fact, write-it-myself, drift offers); user additions split correction (silent ledger) vs NOTE(<initials>):
attributed verbatim note (greppable for re-harvest); 4 passes hardcoded; create-voice = name -> AI persona
-> edit -> test on user target -> save.

**File inventory (all compile, fixture-agnostic, tree clean):** SKILL.md, strip.py, reattach.py,
triage_wf.js (3 lenses + comment lens + ledger-writer + validator loop), ledger validator (folded in),
writers_wf.js (4 passes + per-symbol consolidation + independent summarizer), tics.py + polish.py (Step 5
verify), render_report.py, gen_voice_previews.py + voice_preview_wf.js, voices.json (7 voices + previews),
splice_symbol.py + regen_symbol.py + stubify_fact.py + drift_check.py (refine loop), preflight.py,
regen_batch.py (library parallelism), regen_phase0/1/2.py drivers, create_voice.py, library_triage.md.
Deleted: PLAN.md, ledger_validate.js (folded into triage_wf.js).

**Deferred (the "voice/style later" track — DO NOT touch without the user):**
- Header/fact repetition: same fact (e.g. 10-byte header layout) re-explained in module + class + methods.
  Root tension: no-cross-reference discipline vs avoid-repetition. Candidate fix: state once, reference
  tersely elsewhere; or judge-level cross-symbol fact dedup.
- Writer clarity: the INDEPENDENT summarizer (summary.json) reads CLEARER than the generated docstrings —
  it has one job + zero constraints while the writer juggles ~15. Lever: flip the dependency so the
  summarizer's plain sentence is the BACKBONE the writer voices (voice as overlay), and/or trim the
  discipline. User has their own ideas; hear them first.

**NEXT: fresh-session bug hunt.** User runs `/regen-comments <file>` (single-file first, then a dir for
library mode, then --create-voice) in a NEW session (cold orchestrator = unbiased test of SKILL.md
walkability; also loads the project CLAUDE.md to exercise clean-room isolation), and reports failures back to
THIS builder/debugger session. preflight is Runbook step 0; pass --expect-email <session account>.

---

## SESSION 2026-06-07 (cont.) — fresh-session cold tests + writer-quality findings

Picks up after the build record above. The user ran the skill COLD in fresh sessions (unbiased SKILL.md
walk) and reported back to the builder session for debugging.

### Fresh-session cold tests — machinery PASSED both
- **Single-file:** `/regen-comments libraries/timing/src/chumicro_timing/heartbeat.py` (voice elon). Whole
  flow ran cold: preflight account-match, voice pick, phase 1 converged, picker (it surfaced the period_ms-
  units fact; user dropped it), phase 2, code AST-identical, report. User did NOT apply — found comment
  QUALITY issues to chase (see below).
- **Library:** `/regen-comments libraries/kvstore/src/chumicro_kvstore/_backends` (voice cutler). FULL
  library-aware flow end to end: preflight, voice pick, user-global CLAUDE.md check (empty), a smart
  `__init__.py` skip, phase 0 `LIBRARY_FACTS.md`, batched phase 1 (conc 3, all 4 converged), per-file
  pickers incl. an **empty-selection re-confirm**, batched phase 2, code byte-identical on all 4, per-file
  report + apply loop, refine loop (dice-roll + a file-wide body-drop on memory.py), real Apply on cp_nvm,
  apply-all-remaining in test mode, revert. Library-awareness confirmed by reading `/tmp/regen-cr/*`
  artifacts (LIBRARY_FACTS.md rode into all 4 rooms; vocab heavily used).

### Fresh-test-driven skill refinements (committed)
- `f7229bc1` report auto-opens (webbrowser) + orchestrator must point the human at it; refine+apply is now
  ONE **persistent AskUserQuestion loop** (exits only on Apply/Discard; nested menus for the 4-option limit;
  library Apply-all-remaining).
- `5ee5660b` **removed the sentence-opener ("The/That/This…") ban** — user: it flattened voice, was never a
  real defect; the earlier "The"-enforcement (tics/polish banned-opener) was solving a non-problem.
- `3a5105a1` brevity gate in the judge (correct → carries non-derivable must-carry → SHORTEST that does so),
  must-carry = non-derivable only, dedup "state each fact once".
- `4f0a3a99` `tighten_symbol.py` (fact-preserving shorten, prints KEPT/DROPPED) + **invariant 7** (push back
  on lossy / bad-data / risky / out-of-directive requests — name the consequence, offer options, comply only
  on explicit confirm).
- `c79cae13` lean picker (low/med only; high-confidence incl. comment-derived auto-kept) + `stubify` `concern`
  field (clearly-wrong / water-cooler noise) + push-back wired at the gates (picker / add-fact / apply-all /
  refine).

### Writer-quality findings — the OPEN work (full plan: `2026-06-07-regen-comments-writer-quality-next-phase.md`)
- Writer is correct but **over-long / over-fact-bounded** (#8); the **independent summarizer reads cleaner**
  than the generated docstrings (#7); same fact repeats across symbols (#6, mostly mitigated by dedup).
- **Research:** the clean target style = the committed `heartbeat.py` docstrings, generated by the registered
  agent `commenter-casual-friendly` (`.claude/agents/commenter-casual-friendly.md`) at `d139e882`
  (`13a4a927` restored 2 facts it dropped). It is NO-BODY + behavior-first.
- **Conclusion (do not relitigate):** no-body is INCOMPATIBLE with our ledger (force it → cram=comma-soup OR
  drop=lose must-carry facts; the body is the release valve). The clean target was clean because of LOW FACT
  COUNT per symbol (cull + altitude), not a banned body. Want a **CONTROLLED body**: kept, tight, voice may
  use more words but should aim tight. Levers: **cull low-vitality facts (#8) + altitude (#6) + controlled
  body**. Harvest `commenter-casual-friendly` ONLY cautiously (behavior-first verb-led summaries, fold a
  contract detail into Returns/Raises when it fits, the anti-pattern ban-lists + failure-mode few-shots) —
  NOT its no-body rule, and do not over-port (the new approach is a different idea on purpose).
- **Plan:** dedicated WRITER exp rounds + a before/after test harness (heartbeat, kvstore backends), OFF the
  skill (skill is built + working — don't churn it). Fold a proven improvement back into `writers_wf.js` only
  after an exp round validates it.

---

## SESSION 2026-06-07 (cont. 2) — WRITER-QUALITY EXPERIMENT (rounds 1–3)

**STATUS: IN PROGRESS.** Production design converging fast; nothing folded into the skill yet (validate
first, then a branch — do NOT churn the working skill). Round 3 running at time of writing.

**Harness** (`.scratch/regen-comments/writer-quality/`, OFF the skill): clean-room `claude -p` from /tmp —
**CLAUDE.md is 127 bytes / NON-empty this session (carries the project-secret canary), so in-session Agent/
Workflow agents WOULD be contaminated; shelling out to /tmp is mandatory.** Files: `harness.py` (round-1
8-arm matrix), `round2.py` (minimal-vs-cull + reroll), `round3.py` (no-body), `prompts.py` (all disciplines,
every example FOREIGN to heartbeat per `[[agent-examples-must-be-neutral]]`), `render*.py` → `report*.html`.
Fixture = `heartbeat.py`; frozen 14-fact ledger reused from `/tmp/regen-cr/heartbeat-1/ledger_final.md`. The
JUDGE is fixture-aware INSTRUMENTATION (knows the must-carry list), never shipped (exp9 pattern). Metrics:
deterministic anno-chars + a structured judge (behavior-first, restatement, noise, must-carry present+correct);
n=5; only countable metrics get A/B'd (`[[run-noise-swamps-rule-effect]]`).

**The 4 heartbeat must-carry (all user-confirmed vital):** mc1 timebase (caller `now_ms` must share clock+unit
with the provider `ticks_ms` construction samples, else first interval garbage), mc2 wrap-safe diff (not plain
subtraction), mc3 drift/no-catch-up (fire re-anchors to poll instant), mc4 inclusive boundary (elapsed == period
fires). **Reference band:** clean target (committed, `commenter-casual-friendly`) = **729 anno chars but only
2/4 must-carry** (tight BECAUSE incomplete — it dropped timebase + inclusive); over-long (the elon complaint) =
**3619 / 4-of-4**.

**ROUND 1** (8-arm factorial: baseline / ledger-cull / cut-pass / controlled-body / no-voice-first /
behavior-backbone + combos):
- All arms land 2000–2800 chars, all 4/4 (except F backbone×full = 3.8). KEY: a tightness FLOOR exists, set by
  FACT-COUNT — carrying 4/4 + document-every-param ≈ 2000 chars; the clean target's 729 only carries 2/4.
  "Tight AND complete at 729" does not exist; the lever for tightness is fact-count.
- Overturned: behavior-first was already HIGH in single-pass (baseline 84%). The mechanism-first summaries in
  `FINAL_elon.py` were the CONSOLIDATED output → framing damage may be partly the CONSOLIDATION step, not
  generation. (Open: check the consolidation judge for mechanism-first picks.)
- Overturned: controlled-body (D) did NOT leak — tightest arm (2017), 0 noise, lowest restatement. Disposition
  holds where prohibition leaks (the may30 "rules leak" prior was about PROHIBITIONS). `[[controlled-body-disposition-doesnt-leak]]`.
- backbone → 100% behavior-first (G/H); cull held 4/4 (8-fact cull not too aggressive).

**ROUND 2** (minimal-4 vs cull-8 ledger, both backbone + controlled-body + reroll, reroll held constant):
- M minimal = 1558 chars, C cull = 1892, both 100% bf, both **4/4 present AND correct**. Reroll never fired
  (attempts 1.0) — net validated as cheap insurance but NOT stress-tested (no real drop to recover yet).
- **THE FINDING (user's eye caught it, metrics missed it — `[[metrics-are-surface]]`): C (cull) READS BETTER
  than M (minimal).** Mechanism, quantified across 5 runs each: the writer RE-DERIVES *positive* facts from the
  code (ticks duck-type 4/5, default-clock 5/5) but NOT *absence* facts (reset-no-validation **0/5** vs C 4/5;
  gate-sends-nothing **0/5** vs C 3/5). Absence is invisible to a reader scanning what the code DOES; only the
  ledger can carry it. Minimal silently deleted the two most useful contracts → tighter but THINNER. So
  "minimal is tighter" was partly "minimal is less complete," and the chars metric rewarded the loss.
- **REFINED LEDGER-WRITER POLICY (sharper than round-29's "cross-method only"):** keep (a) cross-method facts,
  (b) non-derivable contracts, (c) ABSENCE / negative facts (no-validation, sends-nothing, not-enforced); drop
  ONLY derivable-POSITIVE single-method facts (the `period_ms<=0` guard, write-site tracing). The cull already
  does ~this; **minimal overshot. The CULL (8) is the production ledger level, not minimal (4).**

**ROUND 3** (DONE — NEGATIVE RESULT, no-body REJECTED): arm B = long-summary, NO separate body section, cull
ledger + backbone + reroll; comparator = round-2 C. On CHARS it looked like a wash (B = 1952 vs C = 1892, both
4/4, both 100% bf) — but **the user's eye caught a VOICE REGRESSION the chars metric hid** (`[[metrics-are-surface]]`
again): with no body as a release valve, the writer CRAMS multiple facts into one dense, comma-heavy, comma-
SPLICED run-on (B run-5: "...Despite the name there is no beat and no signal sent, it only answers... Drive it
with one clock: the constructor takes its first reading..., so every now_ms... or the first interval is
meaningless."). Round-2 C (body allowed) breaks the same facts into clean separate sentences. **This reproduces
`[[no-body-incompatible]]` experimentally — exactly the user's long-standing call ("no-body forces drop or
comma-heavy"). The body is the release valve; REJECT no-body.** Arm A (two-phase convert) stays PARKED.
BONUS: the verify→reroll net FIRED and RECOVERED (run-5: 2 attempts, dropped a must-carry on draft 1, judge
caught it, re-roll → missing=[]). Net validated end-to-end.

**PRODUCTION DESIGN — CONVERGED (validated over 3 rounds; next = a BRANCH fold, do NOT churn the working skill):**
- **Ledger-writer → cull level:** keep cross-method + non-derivable + ABSENCE facts; drop derivable-POSITIVE
  single-method facts. (Minimal-4 overshot — loses absence facts the writer can't re-derive.)
- **Writer → behavior-backbone + controlled-body:** summary from the code first, ledger as a thin must-carry
  overlay, "say it once in its tightest form", an earned body is fine (round 3: removing it does not help).
- **verify→reroll net:** judge must-carry present+correct, re-flag the missing one and re-roll (max 3). FIRED+
  recovered in round 3.
- **Target shape:** ~1900 anno chars carrying 4/4 must-carry at 100% behavior-first and COMPLETE — vs the 3619
  over-long complaint (fixed) and the 729 clean target (tight only because it carries 2/4). ~1900 is the real
  floor for "tight AND complete"; it keeps the timebase contract the clean target dropped. Addresses #6/#7/#8.

**NEXT:** fold the converged design into the skill on a BRANCH — `triage_wf.js` ledger-writer prompt (cull
policy: + absence facts, drop derivable-positive), `writers_wf.js` (backbone two-step + controlled-body "say
it once" + no-body-vs-body is a wash so keep the existing body), and a writer-side verify→reroll loop in
`regen_phase2.py` (judge must-carry present+correct, re-roll with the missing fact re-flagged). Validate on
heartbeat + a kvstore backend before merge. Experiment artifacts: `.scratch/regen-comments/writer-quality/`
(harness.py / round2.py / round3.py / prompts.py / render*.py, report*.html, rooms*/).

**New pointers:** `[[writer-rederives-positive-not-absence-facts]]` (writer recovers what the code DOES, never
what it DOESN'T — so the ledger MUST carry absence facts), `[[clean-target-is-tight-because-incomplete]]`
(729-char target carries only 2/4; tightness floor is set by fact-count), `[[ledger-stub-inflates-writer-treatment]]`
(a fact handed as a stub gets fuller treatment than the same fact self-derived; minimal ledger → terser → tighter),
`[[controlled-body-disposition-doesnt-leak]]`, `[[summarizer-beats-writer-because-free-and-code-only]]` (the
independent summarizer reads cleaner because it has code-only input + one job + no docstring format; the backbone
writer ports that framing).

**FOLD LANDED IN THE SKILL (2026-06-07), direct to `main` working tree, self-test validated.** triage_wf.js
(cull policy + descriptive-stub + conceptual-dedup + no-coinage + class-name capability-trap nudge),
writers_wf.js (backbone two-step + controlled-body "say it once" + class-docstring rule + no-coinage; removed
the voice-first EXCEPTION clause), reroll dropped (4-pass+consolidation gate already covers it). Conceptual
dedup checked for NEGATION (none -- nuances + sites preserved) and WRONG-SPOT (none). GOVERNING PRINCIPLE
recorded: **a docstring must be BOTH clean AND informative** -- clean voice from backbone+controlled-body+
no-echo+no-coinage, informative from the cull KEEPING cross-method+non-derivable+ABSENCE facts (the
"not-an-emitter" trap is the informative half earning its keep). Detail in the focused doc
`2026-06-07-regen-comments-writer-quality-next-phase.md`. NEXT: user runs `/regen-comments` cold (heartbeat +
a kvstore backend). `[[docstring-must-be-both-clean-and-informative]]`.

**2026-06-08 update (see the focused doc's "2026-06-08 SESSION" section for full detail):** the recurring
"comments worse than the summary" was largely **the wrong default voice** -- the good experiments ran `elon`,
the skill had defaulted to `cutler` (clinical, enumerates). **Default changed cutler->elon.** A subtractive
redesign landed UNCOMMITTED (ledger->traps-only, discipline "Say it once"->"Say it plainly" 1-2 sentences,
dropped "Write correct English", genPrompt->summarizer-mode+correct-the-read, judge simplified, prompt tics
cleaned). Production run on `quality_ranking.py` fixed the T7 inversion and flows. KEY findings: the
summarizer reads clean because it carries FEWER burdens, not more rules (`[[summarizer-key-is-fewer-burdens
-not-more-rules]]`); the consolidation judge REWRITES some symbols and its picks.json lies
(`[[consolidation-judge-rewrites-and-its-picks-json-lies]]`); the coinage metric is n=3-noisy and the writer
coins regardless of the ledger. NOT CONVERGED -- open: judge should pick-only (maybe best-of-4-whole-files),
summary must be a proper summary not deferred to body/Args, test writers even closer to the summarizer,
maybe summarizer+ledger->docstring.
