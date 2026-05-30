# Handoff 2026-05-30 — comment-generation experiment: round 16 (stub-form ledger + per-param walk) built, not yet run

Supersedes `2026-05-29-comment-generation-round15-triage-pass.md` (deleted in this commit). Round 15 ran and was analyzed this session; this handoff carries those results forward plus the round-16 build.

## My role (do not lose this)

Orchestrator / analysis seat. I read outputs, decide the spec, edit the agent files, build the package, hand back. The `RUN.md` is for a **separate dispatch session** the user runs — I do **not** run the workflow myself (agent files load into the registry only at that session's start). User confirmed across sessions: "you are the orchestrator that edits agents files… i will run [the round] in another session."

## Round 15 ran clean — results (analyzed by 3 opus verbatim-quote readers this session)

Run: 45 agents (9 triage + 36 writers), 0 failures, 27 ledgers + 108 written files, ~7.8 min, ~2.04M subagent tokens.

**The triage architecture works.** `[VERIFIED: ledger reader + writer reader, verbatim quotes]`
- **Cut-list fired reliably**, all 3 runs: packet-id essay, ProtocolState ASCII diagram (→ RENDER-AS-PROSE), sockets cross-library consumer list, "today's only firing site" + future-adapter speculation — all cut, and **no writer re-added any** from the code.
- **Over-cut guard held the gold**, all 3 runs: every timing numeric fact (`2**29`/`~6.2 days`, `[0, TICKS_MAX]`, `~3.1 days` OverflowError, `ticks_diff` aliasing) and every public `Raises` survived. The two round-14 regressions did NOT recur (`UnsupportedQoSError` on publish kept everywhere; diagram is prose everywhere).
- timing control fact-perfect, even slightly richer; the dense sockets cert-format matrix survived intact.

**Two flaws found — both fixed in round 16:**
1. **Ledger came out as polished sentences, not stubs.** The prompt said "facts, not prose to copy" but the agent emitted copy-pasteable docstrings (the prompt's own bad example `"Returns the signed millisecond distance from start to end"` appeared nearly verbatim in a ledger). Consequence: on small high-fact files (ticks.py) all 4 personas **converged to near-identical text** — "one file in four costumes" — the **personality axis collapsed**. The ledger's register leans terse-engineer, so engineer transcribed it cleanly and "won," while warm had to fight the ledger's voice. The user's "engineer did best, warm only ok" read is **partly an artifact of this** — we were measuring who copied the engineer-voiced ledger most faithfully, not whose independent voice is best. `[VERIFIED: writer reader quoted ticks_diff near-identical across all 4]`
2. **Triage silently dropped constructor params.** `MQTTClient.__init__` lost descriptions for `username`, `password`, `will_message`, `will_retain` (gone entirely, not reworded) and `when_oversized` (partial) — identical across all 4 personas, so invisible unless diffed against round 14. Cause: triage under-indexed a 22-arg constructor — it never *walked* those params. This is the round's riskiest-assumption biting: a ledger gap is an unrecoverable writer loss. Also lost: `_fail` private-method contract, `OSError(32)`/CYW43 errno specificity. All high-value public contracts survived; losses cluster in constructor-arg descriptions + private/diagnostic detail. `[VERIFIED: r14-vs-r15 diff reader, verbatim r14 text quoted]`

## The user's round-16 decisions

1. Arg policy: **no silent drops, per-param decision** — triage walks every public param and tags each KEEP (non-derivable stub) or `derivable`; vital args never fall out, trivial ones can stay bare (avoids robotic "username: the username"). NOT "document every arg" (that reintroduces the banned signature-restatement).
2. Roster: **warm-free + engineer-free only** — smallest clean test of "did the stub ledger un-collapse the voice axis." Add other voices in round 17 once the ledger is proven. (User: "once we get the ledger right and working with warm we can try a couple other voices.")
3. Structure: free only (round 15: free ≈ light; detailed earned nothing — both dropped earlier).
4. User added: "use your judgement… youre the comment master."

## What I built (round-16 package) — all verified on disk

- **Triage agent** `.claude/agents/commenter-r16-triage.md` — adds (a) a hard **STUB discipline** (no leading capitalized verb, no subject-verb-object sentence, telegraphic fragments with `→`/`;`/math; good-vs-too-finished examples; a reread self-check that cuts any grammatical sentence back to a fragment); (b) a mandatory **per-public-parameter walk** — one `PARAM <name>:` line each (a stub, or `derivable`), none skipped; (c) a no-cross-symbol-pointer rule (fixes the r15 "documented on that class" leak). Cut-list + over-cut guard carried from r15 unchanged (they worked).
- **2 writer agents** `.claude/agents/commenter-r16-{warm-free,engineer-free}.md` — carry the r15 free personas, plus: "expand each stub into a sentence in your own voice; never paste a stub verbatim" and "document every PARAM the ledger kept; `derivable` ones may be omitted." Personalities/exemplars unchanged (form-validation / token-bucket, zero test-vocab collision).
- **Inputs**: `round-16/fixing/` + `round-16/stripped/` — copied byte-identical from round-15 (`diff -rq` clean), so the ONLY changed variable is the triage ledger form + the writer arg rule. 9 files each.
- **Workflow** `round-16/round-16-workflow.js` — `pipeline()` over 9 library-runs; stage1 triage → stage2 `parallel()` of the 2 writers. 27 agents (9 triage + 18 writers). Uses `export const meta` like the prior working workflows (`node --check` flags `export` — CJS-vs-ESM false alarm, ignore).
- **RUN.md** `round-16/RUN.md` — dispatch runbook: restart, 3 agentTypes, run workflow, verify **27 ledgers + 54 written .py**, do-not list, analysis notes (the two round-16 questions: did the ledger come out as stubs, did the voice axis un-collapse; + the arg-coverage check on `__init__`).

## Next concrete step

Hand `round-16/RUN.md` to a fresh dispatch session. It restarts, runs the workflow, verifies 27 + 54, reports. Then a new analysis seat reads ledgers-first: (1) are they stubs now? (2) do warm and engineer sound distinct again? (3) does `MQTTClient.__init__` document username/password/will_*/when_oversized?

## Riskiest assumption (round 16's bet)

That forcing stub form actually un-collapses the voice axis without costing fact fidelity. Risk both ways: (a) if triage *still* writes sentences despite the hardened discipline, we're back to round-15 convergence — check the ledgers first, that's the gate; (b) if stubs are *too* terse, a writer may mis-expand a fragment and introduce an error the prose-ledger wouldn't have. The per-param walk is the other bet — it should close the arg gap, but verify `__init__` coverage explicitly (the loss was invisible persona-to-persona; only the r14/r15/input diff caught it).

## If round 16 succeeds → round 17

Add the "couple other voices" the user wants, on top of the proven stub ledger + free structure. Candidate voices to consider (from the round-11 history): the round-8/11 imitate-adafruit warmth, a terse-Hemingway, a teaching/mental-model voice. Keep warm + engineer as the reference pair.

## Dead ends (don't re-walk)

- Prose-form ledgers — caused r15 voice-collapse + verbatim lift. Stubs are the fix.
- `detailed` 7-point structure arm, and "document every arg" — both rejected (no gain / reintroduces banned signature-restatement).
- Hand-rolled tokenize stripper — leaves empty bodies → IndentationError. Use `python scripts/run.py strip-comments <src> <dst>` (one src/dst pair per call; inserts `pass`).
- All round-12 "fixing" mechanisms + the mental-model context-reading arm — abandoned round 14.
- Any "fidelity"/code-line-count analysis — agents only touch comments; irrelevant.
- Grep as a comment-quality judge — READ.

## How to rebuild context fast

- **Read first:** `round-16/RUN.md`, then the 3 `commenter-r16-*.md` agents.
- **The build is entirely in `.scratch/` (gitignored) + `.claude/agents/` (untracked).** Only this handoff + the `next-up.md` pointer are tracked — nothing else to commit.
- **Round-15 outputs** at `round-15/runs/` (108 files) + ledgers at `round-15/triage/` stay on disk for the round-15-vs-16 comparison.
- **Memory:** `comment-voice-target`, `cold-write-loses-facts` (updated this session with r15 results + r16 stub-ledger direction), `run-first-read-all-results`, `understand-harness-before-editing`.

## Gotchas

- **`.claude/agents/` is NOT git-tracked**; `commenter-r16-*` load into the agentType registry only at session start. The orchestrator that wrote them cannot dispatch them — dispatch is a separate reloaded session handed RUN.md.
- **`scripts/run.py strip-comments` takes ONE src/dst pair** — call once per library. (round 16 reused round-15's stripped, so no strip needed this round.)
- **Don't over-batch dependent tool calls.** A mid-batch Bash error cancels all following calls in the block, including Writes — cost redos twice this experiment. Sequential for anything where a later call depends on an earlier one landing.
- **Tool-output rendering glitches this session** (doubled lines in Read/Bash output, garbled `ls`). Substance verified fine via clean single-purpose checks (`grep -c '^name:'` = 1 per agent; `find -maxdepth 1`). Re-check with a clean targeted command rather than trusting a garbled glance; read the artifact.
- **`.idea/chumicro.iml`** shows modified all session (IDE dirt) — not mine, left unstaged.
