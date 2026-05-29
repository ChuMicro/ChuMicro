# Handoff 2026-05-28 — comment-generation experiment: round 14 (personality × structure factorial) + the full journey

This supersedes the handoff I picked up at session start (`2026-05-28-comment-regen-fixing-pivot.md`, deleted in this commit). Read this one end-to-end; it is long on purpose — the prior handoff was too thin and the next session paid for it.

## What this session was about

Long-running experiment: get an AI agent to write **good code comments** for ChuMicro libraries — a systemic AI failure mode. The bench strips/keeps a library's comments, dispatches many "commenter" persona variants in parallel (×3 runs each) against the source, and a human/analysis session judges which persona writes best. Entering this session I had a handoff that said "build the round-12 *fixing* bench (read existing comments for facts, rewrite prose fresh)." We did that — and then iterated hard through rounds 12 → 13 → 14, with major reframes from the user at each step. The session's real output is **round 14**: a clean persona design that mostly works, plus a precise diagnosis of the one thing still broken (fact triage).

## The experiment's north star (do not lose this)

Make an agent write comments that a human reads in **one forward pass** without having to stop, hold words, or jump back — in a warm, human **personality** — preserving only the **vital facts** and cutting everything else. Three orthogonal axes, learned this session to be separable:

1. **Personality / voice** (warm vs precise-engineer) — what wins long-term; taught by *imitation of exemplars*, not rules. `[VERIFIED: round-11 user ranking + round-14 reads]`
2. **Sentence structure / legibility** (one-pass, no left-loading, no backward pointers) — universal craft; turns out the model already does this well, explicit rules add little. `[VERIFIED: round-14 free ≈ detailed]`
3. **Fact triage** (which facts survive) — the *still-broken* axis. Agents are too generous: they inherit borderline facts from the input. `[VERIFIED: round-14 reads, below]`

## State of the runs (point-in-time — re-probe on resume)

All under `.scratch/regen-comments/experiment/` (gitignored). `[VERIFIED: find counts this session]`
- **round-14** (the current one): RUNNING, partial. All 6 personas have a complete **run-1** (9 files each); run-2/run-3 partial for the `engineer*` slugs. Output: `round-14/fixing/runs/<slug>/run-<N>/<lib>/<file>`. Expected total at completion: 162 files (6 × 3 × 9).
- **round-13** (per-library fan-out, 15 fixing personas): PARKED at 45/405. Doomed-paradigm personas (see below); fine to leave.
- **round-12** (all-9-files dispatch, 15 fixing personas): PARKED at 259/405. Same.
- Worker sessions for 12/13 may still be wedged/stopped — I never confirmed. The user can stop them; nothing depends on them.

## The journey this session (rounds 12 → 13 → 14), and what each taught

This is the load-bearing narrative — the *angles of approach* and why each gave way to the next.

### Round 12 — "fixing" paradigm, 15 personas (5 voices × 3 anti-anchoring mechanisms), all-9-files dispatch
- Voices = round-11 winners: imitate-adafruit, hemingway, lax-when, single-pass, mental-model.
- Mechanisms = factledger (lift facts, discard prose, write blind), reconcile (cold-write from code then add missing facts), translate (carry meaning, share no words). All three were attempts to stop the agent *anchoring* on the existing soupy prose.
- **Result: failed via anchoring.** `[VERIFIED: reads]` Agents *injected* the existing prose (spun a worse version) instead of writing fresh. All three mechanisms failed identically — each is a flavour of "ignore what you just read," which an LLM can't do when the prose is in its context. Personas built/named in `.claude/agents/commenter-fix-<voice>-<mechanism>.md` (15 files, still on disk).

### Round 13 — same 15 personas, **per-library** dispatch (one library per agent run)
- Hypothesis: an agent fatigues across 9 files, so giving it one library at a time helps. `[VERIFIED: it did help meta-dropping somewhat]`
- **Result: also anchored**, but per-library dispatch dropped the navigational meta more often. Also surfaced two fidelity artifacts (mental-model fabricated the 1569-line mqtt file — wrote a different 344-line file; one SPDX header). **CRUCIAL CORRECTION the user made:** the agents only edit *comments*; whether the code body changed is **irrelevant** to judging comment quality. I wasted ~5 turns on ast/line-count "fidelity" checks — a drift. Don't repeat.

### Round 14 — the reframe that worked: **personality × structure factorial, blind, disciplined**
The user's reframes that produced it (in order):
1. "Write the agents to NOT base comments on existing comments" → I proposed a two-stage blind extractor→writer. **User then corrected the whole frame again:** the agents only touch comments; code-change is moot.
2. **"voice = personality"** — adafruit kept winning earlier *because it had a personality* (warm, human, talks to the reader). Keep the personality; change everything else.
3. **"keep both"** personalities (warm + engineer) — it's an exploration, tournament-ish. Personality is the *variable*.
4. Add explicit **sentence-structure guidance** ("how to structure a sentence in the first place") — but try it at multiple depths.
5. Final roster: **6 personas = {warm, engineer} × {free, light, detailed}** structure-guidance levels. `effort: high` held constant ("minimize variable churn"; medium is a later token-saving pass).

## The round-14 personas (the current best design)

Files: `.claude/agents/commenter-r14-{warm,engineer,warm-detailed,engineer-detailed,warm-free,engineer-free}.md`. `[VERIFIED: all 6 resolve]`

**Shared spec (the "change everything else" — identical in all 6):**
- **Open on the behavior, never on orientation.** Lead with what the symbol *does*, not "X is the entry point / the helpers live in Y." This is the single biggest win — it killed the orientation meta that plagued 12/13. Stated with *neutral placeholder* examples only.
- **Sentence-structure block** (the axis that varies): `free` = none; `light` = 3 habits (subject+verb early, no left-loaded modifier stacks, no backward pointers); `detailed` = 7 points (adds main-clause-first, one-idea-per-sentence, ≤1 adjective before a noun, parallel `Args` shape, cut dead words).
- Keep a fact only if **vital AND non-derivable**; no SPDX/license/boilerplate; 1–2 line summary, no bodies; one-line `Args`/`Returns`/`Raises`; **no ecosystem naming** (no "Adafruit"/"CircuitPython" — portable to Kotlin by swapping only format mechanics); read **only the input file** (no siblings/ADRs).
- **Personality** (the keeper, shown via neutral exemplars, not described): `warm` = friendly experienced dev leaving notes ("Hand it a connected socket", "so you can reuse it"); `engineer` = precise senior-to-a-peer ("Speaks MQTT 3.1.1 over a caller-supplied socket… refuses ids already in flight"). Neutral exemplar domains: form-validation (warm), token-bucket rate-limiter (engineer) — `[VERIFIED: 0 collision with test-input vocab]`.

**The superseded `commenter-r14-conceptual.md` was deleted** (the engineer personality replaced the mental-model "conceptual" one).

## Round-14 deep-read findings `[VERIFIED: read run-1 across all 6, timing + mqtt module/class/methods + sockets]`

1. **"Open on behavior" works in every variant.** None opens with "MQTTClient is the entry point" — the orientation meta that half the round-12/13 agents kept is gone. No SPDX in any. **This is the big win.**
2. **Timing (clean-comment control): all 6 near-tied and excellent.** Every fact preserved; structure-level invisible on short clean docstrings.
3. **Structure axis is low-value, maybe negative.** `warm-free` (zero structure rules) produced the *cleanest* mqtt module docstring; method docstrings from `warm-free` read exactly as one-pass-clean as `engineer-detailed`. The model already writes parseable sentences; the 7-point block adds marginal formatting (a `Raises:` block, parallel `Args`) and **no legibility gain** — sometimes keeps *more* meta. → Lean `free`/`light`; the heavy block isn't earning its weight. (Vindicates the round-8 caution that rule-enumeration stiffens.)
4. **Both personalities work; the warm-vs-engineer gap is smaller than the free-vs-detailed noise.** Taste call.
5. **The one real remaining weakness = fact triage (the user's "picking bad facts to preserve").** Prose de-souping is excellent; *which facts survive* is too generous. Instances:
   - mqtt module: private-attr packet-id essay (`_in_flight`/`_allocate_packet_id`/"1-65535 wraparound") — 5/6 kept; only `warm-free` cut it.
   - sockets `__init__`: cross-library consumer list ("Substrate for `chumicro-mqtt`, `chumicro-requests`…"); on `UnsupportedSSLConfigError`, "The one firing site **today** is…" (stale present-state) + rationale ("so a future adapter surfaces…").
6. **REGRESSION (user-flagged, verified):** all 6 round-14 personas keep the `ProtocolState` **ASCII state-transition diagram**; round-13 `lax-when` dropped it for prose. `[HYPOTHESIS: cheapest test = soften/clarify the "never drop a line of code — comment all of it" anti-truncation guard so it clearly applies to CODE only, add an explicit "state-machines in prose, no ASCII diagrams/tables in docstrings" rule, re-run on mqtt, check ProtocolState.]` The anti-truncation guard (added in r14 to stop mental-model's code-fabrication) probably over-corrected into "preserve the diagram."

## What I know about the English language (the craft — spare no expense, per request)

This is the distilled, **domain-blind, portable** craft. It is the real deliverable of the whole experiment.

**The legibility bar (the user's primary test): one forward pass.** A comment fails the instant the reader stops, holds a pile of words, or jumps back. Good prose parses left-to-right, once. The two named enemies:
- **Left-loading** — modifiers stacked *before* the head noun, so the reader holds adjectives in suspense. "a caller-supplied retry-budget ceiling value" → "the retry budget the caller set." Subject and verb come early; detail trails to the right.
- **Backward-reference chains** — opening a sentence with "it" / "this" / "that" / a bare "the X" that means something from a previous sentence. One pointer is tolerable; stacked across sentences ("the pattern" → "the thing" → "that") the reader spends more effort chasing pointers than reading. Each sentence stands alone; repeat the noun or restructure.

**The four moves (domain-blind, safe to encode in any writer):**
1. **Use the domain's own noun; don't coin one.** `heartbeat`/`clock`/`tick`, not `window`/`reading`. Inventing a noun forces the reader to translate it back.
2. **Say what the caller GETS, not what the code does to itself (effect over mechanism).** "Prime the next beat to fire after `period_ms`" beats "Anchor the marker to `now_ms`." The mechanism framing also tends to *drop the effect* (the real fact). This is the spine. NB: noun-discipline *as an explicit rule* backfired in round 8 (produced "Pins the last-fire mark") — effect-over-mechanism is the lever; clean nouns are a *consequence* of it.
3. **Answer first, modifiers right, split before a noun-pile.** "Returns the current tick. Masked for wrap safety." beats "Returns the current tick masked into the wrap-safe range." Two short sentences beat one stacked one. "for wrap safety" (why) beats "into the wrap-safe range" (where) — the why is what a caller needs.
4. **Recurrence reads as "every X."** "fires every `period_ms`," not "once per `period_ms` window."

**Content rules (orthogonal to prose craft):**
- **Open on behavior, not orientation.** The biggest single win this round. "X is the entry point / the helpers live in Y / the main class" is *navigational meta* — it only appears when you open by *orienting* instead of *describing*. Open on the verb and it never appears. Note: grep cannot detect this — "is where you start" is the same meta reworded; you must *read*.
- **A literal that IS the contract stays; a token that substitutes for a named concept goes.** `[0, TICKS_MAX]` / `2**29` on a wrapping counter is *vital* (the wrap point a caller must respect). `MAX_RETRIES` → "retry budget" *is* a droppable substitution. Prefer the human-friendly magnitude ("about every 6 days") over a bare power-of-two when both state the same boundary — but keep the exact literal where a caller computes against it.
- **Fact triage (the open weakness): keep only vital AND non-derivable AND caller-facing.** Cut: navigational meta, cross-library/consumer references, "the one X *today*" present-state, private internals (`_foo`) in a public summary, ASCII diagrams/tables, rationale essays, history, session/workstream pointers. Default to saying less.
- **No bodies; 1–2 line summary; one-line section entries** — but **soft in practice**: every variant correctly overrides "no bodies" for a genuinely complex symbol (a state machine, a 25-param `__init__`). Judgment beats a hard cap.
- **Personality is shown by exemplars, never described.** "Don't *describe* the warmth; let it show." A generic adjective-list ("warm, friendly, direct") teaches nothing; worked one-line exemplars in a neutral domain teach the voice. Imitation > rule-enumeration for voice (round-8 imitation scored 0 on exact-gold-match but won on human voice judgment).

**Judge-blindness asymmetry (for when the judge gets built):** the future best-of-N judge MAY see gold (the round-8 `table.md` golds + the user's labeled righter/wrong pairs); the **writer personas must stay domain-blind** — feeding a writer a timing/mqtt gold pair is a leak.

## What worked / what didn't

**Worked:**
- Personality + capability-first opening + de-anchoring → killed the orientation-meta plague.
- Per-library dispatch (round 13+) > all-9-files (round 12) for focus.
- Neutral exemplar domains (form-validation, token-bucket) — zero test-vocab collision, unlike round-12/13 (message/payload/buffer overlapped mqtt/sockets).
- `effort: high` held constant while varying one axis.

**Didn't:**
- The "fixing" mechanisms (factledger/reconcile/translate) — all anchored; abandoned.
- The mental-model **context-reading** arm (ADRs + siblings) — fabricated the big mqtt file and produced the lone SPDX; dropped entirely in round 14.
- Heavy sentence-structure rules — no measurable legibility gain over `free`.
- Grep as a judgment proxy — failed me **three times** (line-count for code-loss; "entry point" literal missing reworded meta; SPDX "sibling-leak" theory that was actually a training-prior invention). On judgment tasks, READ. (Memory: `run-first-read-all-results`, `understand-harness-before-editing`.)

## Riskiest assumption

That **fact triage is fixable with a sharper "what survives" rule** without re-introducing the anchoring/over-preservation we just escaped. `[HYPOTHESIS: cheapest test = add to the shared spec an explicit cut-list (cross-refs, "today" present-state, private internals, ASCII diagrams) with neutral examples, re-run warm-free + engineer-free on mqtt+sockets ×3, read whether the packet-id essay / consumer list / diagram get cut without the prose degrading.]` If the explicit cut-list works, round 15 is essentially done. If it makes the agents over-cut vital facts, fact triage may need a different mechanism (e.g., a separate triage pass).

## To re-research / verify next session

- **Finish reading round 14** — I read run-1 (timing fully; mqtt module/class/methods; sockets `__init__`). Not read: run-2/run-3 (consistency), the other sockets files, mqtt's long method tail. Read, don't grep.
- **Pin the ASCII-diagram regression cause** (hypothesis above).
- **Decide the round-15 spec change**: add the explicit fact-triage cut-list; likely drop the `detailed` structure arm (low value) and keep `free`/`light`; possibly narrow to one personality if the user picks.
- `[VERIFY: web]` nothing version-specific outstanding.

## Dead ends (don't re-walk)

- Cold-writing from stripped code (rounds 1–11) — loses non-derivable facts (timing's 3.1-day limit, commit `d139e882`).
- The two-stage blind extractor→writer — proposed, then mooted when the user clarified code-change is irrelevant; the simpler "blind single-stage + discipline" (round 14) is the path.
- Context-reading (ADR/sibling) writer arm — fabricates on large files; leak vector.
- Git-archaeology / facts-database from history — user shut it down; true fact-loss is rare.
- Any "fidelity"/code-preservation analysis — irrelevant; the regen process preserves code, agents only touch comments.

## How to rebuild context fast

- **Read first:** the round-14 personas (`.claude/agents/commenter-r14-*.md`) and `round-14/RUN.md` — the RUN.md has the full factorial framing + the analysis lens + the session's hard-won "do not"s (run-first, read-don't-grep, out-of-order-results).
- **Memory (already lifted this session):** `comment-voice-target` (legibility bar + four moves), `cold-write-loses-facts` (the round-12→14 method notes + the evidence-read corrections), `understand-harness-before-editing`, `run-first-read-all-results`.
- **The runbook convention** for these benches lives in `round-11/RUN.md` (the template I drifted from and was corrected to match): dispatch-session-only, restart + agentType list, verbatim task prompt, file-count verify, do-not list, separate analysis seat.
- **Workflows:** `round-{12,13,14}/round-*-workflow.js` — `parallel()` fan-out, per-library in 13/14, `agentType: commenter-...`, `model: opus`.
- **Gold reference for the future judge:** `round-8/table.md` + the user's labeled pairs in this session's transcript (the "righter/wins/mostly-wrong" heartbeat/reset/ticks_ms examples).

## Gotchas

- **READ, don't grep, for any comment-quality judgment.** Cost me three wrong claims this session. "entry point" reworded as "is where you start" is invisible to grep; a comment-only line-drop looks like code loss to `wc -l`.
- **The user's reports are summaries too** — verify against the artifact before encoding. I encoded "every agent / all AI-tics / lax added SPDX" into memory before reading one output file; the evidence refuted parts (SPDX was mental-model, 1 file; AI-tics zero; entry-point 7/14 and anchored-from-input). The "read the artifact, not the summary" rule applies to the user, gently.
- **`.claude/agents/` is NOT git-tracked** — the personas (round-12 `commenter-fix-*` ×15, round-14 `commenter-r14-*` ×6) live there untracked; a `mv`/`rm` has no git footprint. They load into the agentType registry **only at session start** — a restart is required before any workflow can dispatch them. The orchestrator session that *creates* them cannot see them; dispatch runs in a **separate reloaded worker session** handed the RUN.md.
- **The experiment is entirely in `.scratch/` (gitignored)** except this handoff + the `next-up.md` pointer. Nothing to commit but those two.
- **`.idea/chumicro.iml`** has been showing as modified all session (parallel-session/IDE dirt) — left unstaged; not mine.
- **Token-bucket / form-validation exemplar domains** were chosen specifically because they don't collide with timing/sockets/mqtt vocab — if you add a third test library, re-check the exemplar domains for overlap.
