# Handoff 2026-05-29 — comment-generation experiment: round 15 (separate triage pass + blind writers) built, not yet run

Supersedes `2026-05-28-comment-generation-round14-personality-discipline.md` (deleted in this commit). Its distilled prose-craft theory was already lifted to memory `comment-voice-target`; its round-14 outputs stay on disk at `round-14/fixing/runs/` for the round-14-vs-15 comparison this handoff calls for.

## My role this session (do not lose this)

I am the **orchestrator / analysis seat**. I read round-14 outputs, decided the round-15 spec, and **edited the agent files + built the round-15 package**. The `RUN.md` is for a **separate dispatch session** the user runs. I do **not** run the workflow myself. The user was explicit: "you are the orchestrator that edits agents files… i will run round 15 in another session."

## What this session did

1. Confirmed round 14 **completed** (all 162 files; the round-14 handoff was written mid-run and wrongly said run-2/3 were partial).
2. Ran the round-14 analysis the prior handoff left open (3 opus readers, one per library, verbatim-quote / read-don't-grep). Findings below.
3. Designed + built round 15 from the user's three decisions.

## Round-14 analysis findings `[VERIFIED: 3 opus readers quoted verbatim across all 6 slugs, run-1 + run-2/3 spot-checks]`

- **timing control passed cleanly.** Every vital non-derivable fact survived in all 6: `2**29`/`~6.2 days` wrap, `~3.1 days` `ticks_add` OverflowError (character-identical in all 6), `[0, TICKS_MAX]`, `ticks_diff` half-period accuracy + wrong-sign aliasing. One cosmetic blemish: `engineer-free` run-2 dropped "heap-" from "heap-allocate". Several arms *added* the documented `False` branch to `Heartbeat.poll` (improvement, code-accurate).
- **`detailed` (7-point) structure arm earns nothing.** Reads the same as light across all three libraries, occasionally thinner (dropped "record error" in `_fail`) or stiffer (formulaic "Returns…" openers). → dropped for round 15.
- **Fact triage is the real failure, and it is INVERTED.** All 6 kept rule-discouraged content and some cut the gold:
  - sockets `UnsupportedSSLConfigError`: all 6 kept the "today's only firing site is…" present-state + the speculative "so a future adapter…" rationale; 5/6 kept literal "today".
  - sockets `__init__`: cross-library consumer list ("Substrate for `chumicro-mqtt`, `chumicro-requests`…") kept by warm/warm-free, dropped by all engineer + all detailed — inconsistent, and warm-free even loses it in run-3.
  - mqtt module: private packet-id essay (`_in_flight`/`_allocate_packet_id`/1-65535) kept by 5/6; only `warm-free` reliably cut it.
  - Over-cut: `warm-free` dropped the `UnsupportedQoSError` `Raises` entry on `publish` (a vital fact).
- **CORRECTION to a round-14 handoff `[VERIFIED]` claim:** it said "all 6 personas keep the ProtocolState ASCII diagram." Not true. Every `free` and `detailed` arm keeps it; plain **`engineer` (light) drops it in run-1 and run-2, keeps it in run-3** (non-deterministic). So the regression was 5/6, and the lone dropper is unstable. Cause: the writer reads a docstring's ASCII as "code lines it must not drop" (the round-14 anti-truncation guard).
- **warm vs engineer:** small, register-level. engineer is leaner and better at scrubbing editorial fat ("honest compromise"), private `_connector` pointers, "see the MP adapter" cross-file refs. warm is friendlier but keeps more discouraged framing. Both legible. One colloquialism each leaked ("blows up" in engineer-detailed; "Heads up:" in warm-free).

## The user's three round-15 decisions

1. Structure roster: **free + light** (drop `detailed`).
2. Personality roster: **keep both** warm + engineer.
3. Triage approach: **cut-list + separate triage pass** (the heavier option — restructure to two steps, not a single-agent cut-list).

## What I built (the round-15 package) — all in place, verified

Synthesis: round-11 fed **stripped** code (anti-anchoring) but lost facts; rounds 12–14 fed existing comments ("fixing") but anchored + inverted triage. Round 15 = stripped code (kills anchoring) **+ a fact ledger** (cures fact loss).

- **Triage agent** `.claude/agents/commenter-r15-triage.md` — personality-blind; reads the full input (code + original comments), emits a per-symbol **fact ledger** (KEEP / RAISES / RENDER-AS-PROSE / CUT / NO-COMMENT). Carries the explicit **cut-list** (navigational meta, cross-component refs, "today" present-state, speculative rationale, private internals in public summaries, ASCII diagrams→RENDER-AS-PROSE, history, editorial self-justification, audit narration) AND a **guard against over-cut** (every Raises/bound/unit/wrap-point/branch-meaning must survive; "a raise/bound/wrap is never derivable").
- **4 writer agents** `.claude/agents/commenter-r15-{warm,warm-free,engineer,engineer-free}.md` — read **stripped code + the ledger only**, blind to original comments. Code for behavior, ledger for non-derivable contracts. Anti-truncation guard reworded to CODE-only; explicit "no ASCII diagrams/tables in a docstring; RENDER-AS-PROSE → one sentence." Personalities + light/free structure block carried from round-14 (proven exemplars: form-validation / token-bucket, zero test-vocab collision).
- **Inputs**: `round-15/fixing/<lib>/input/*.py` (copied from round-14, the 9 files).
- **Stripped**: `round-15/stripped/<lib>/*.py` — `[VERIFIED]` 9 files parse, AST shows 0 residual docstrings, symbol sets match input exactly, 29/29 tooling directives preserved, 0 prose comments leaked. Built with the **canonical** `python scripts/run.py strip-comments <src_dir> <dst_dir>` (one src/dst pair per call; it inserts `pass` into emptied bodies — my hand-rolled tokenizer stripper did NOT and broke on docstring-only bodies; discarded).
- **Workflow** `round-15/round-15-workflow.js` — `pipeline()` over 9 library-runs; stage1 triage → stage2 `parallel()` of the 4 writers on that run's ledger. 45 agents (9 triage + 36 writers). Uses `export const meta` exactly like round-14's working workflow (`node --check` flags `export` as a CJS-vs-ESM false alarm; ignore it).
- **RUN.md** `round-15/RUN.md` — dispatch-session runbook (restart, 5 agentTypes to resolve, run workflow, verify **27 ledgers + 108 written .py**, do-not list, analysis notes incl. the riskiest-assumption watch).

## Next concrete step

Hand `round-15/RUN.md` to a fresh dispatch session (agent files load only at its session start). It restarts, runs the workflow, verifies 27 + 108, reports. Then a new analysis seat reads ledgers-first.

## Riskiest assumption (the round's bet)

Feeding writers **stripped** code bets the ledger fully replaces the lost facts. Round 11 cold-wrote from stripped code and lost facts (memory `cold-write-loses-facts`); here the ledger is the cure. **A ledger gap now shows up as a writer fact-loss** — the writer can't recover what the ledger missed. Watch for facts present in round-14 outputs but absent in round-15: that is a *triage* miss, not a writer miss; the fix is the triage agent's guard, not the writers.

Secondary fork the user did not explicitly rule on: writers are **blind** (read stripped code, not the full input). This is the faithful reading of "separate triage pass" — a separate pass only breaks anchoring if the writer can't see the prose. If the user wanted writers to still see the full input, flip the writer prompts to read `fixing/<lib>/input/<file>` instead of `stripped/<lib>/<file>` and drop the strip step. I judged blind = faithful; flag it for veto before dispatch.

## Dead ends (don't re-walk)

- `detailed` 7-point structure arm — no legibility gain over light; dropped.
- Single-agent cut-list without a separate pass — user chose the separate pass over it.
- Hand-rolled tokenize stripper (`strip_keep_directives.py`, deleted) — leaves empty bodies → `IndentationError`. Use `scripts/run.py strip-comments`.
- `.scratch/strip_docstrings_and_comments.py` — works for single files but no `pass` insertion either; the canonical `run.py strip-comments` is the right tool.
- All round-12 "fixing" mechanisms (factledger/reconcile/translate) and the mental-model context-reading arm — abandoned in round 14.
- Any "fidelity"/code-line-count analysis — agents only touch comments; irrelevant.
- Grep as a comment-quality judge — failed the round-14 author 3×; READ.

## How to rebuild context fast

- **Read first:** `round-15/RUN.md` (full framing), then the 5 `commenter-r15-*.md` agent files.
- **The build is entirely in `.scratch/` (gitignored) + `.claude/agents/` (untracked).** Only this handoff + the `next-up.md` pointer are tracked — nothing else to commit.
- **Memory:** `comment-voice-target` (prose craft + legibility bar), `cold-write-loses-facts` (updated this session with the round-15 ledger synthesis), `run-first-read-all-results`, `understand-harness-before-editing`.
- **Round-14 outputs** at `round-14/fixing/runs/` (162 files) for the round-14-vs-15 fact-loss comparison.

## Gotchas

- **`.claude/agents/` is NOT git-tracked**; `commenter-r15-*` files load into the agentType registry **only at session start**. The orchestrator that wrote them cannot dispatch them — dispatch is a separate reloaded session handed RUN.md.
- **`scripts/run.py strip-comments` takes ONE src/dst pair**, not many — call it once per library (3 calls). Batching all three pairs in one call errors with "unrecognized arguments."
- **Don't over-batch dependent tool calls.** This session I fired a big parallel block where a mid-batch Bash error cancelled every following Write — lost ~7 file writes and had to redo. Sequential for anything where a later call depends on an earlier one landing.
- **`.idea/chumicro.iml`** shows modified all session (IDE/parallel-session dirt) — not mine, left unstaged.
- **Token-bucket / form-validation exemplar domains** chosen to not collide with timing/sockets/mqtt vocab — re-check if a third test library is added.
