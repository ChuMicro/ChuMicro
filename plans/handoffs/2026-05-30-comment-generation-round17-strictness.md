# Handoff 2026-05-30 — comment-generation experiment: round 17 (hardened triage + self-reviewing writers + document-every-arg) built, not yet run

Supersedes `2026-05-30-comment-generation-round16-stub-ledger.md` (deleted in this commit). Round 16 ran and was analyzed this session; this handoff carries those results forward plus the round-17 build.

## My role (do not lose this)

Orchestrator / analysis seat. I read outputs, decide the spec, edit the agent files, build the package, hand back. The `RUN.md` is for a **separate dispatch session** the user runs — I do **not** run the workflow myself (agent files load into the registry only at that session's start).

## Round 16 ran clean — results (analyzed by 3 opus verbatim-quote readers + a direct read this session)

Run: 45 agents (9 triage + 36 writers), 0 failures, 27 ledgers + 108 written files.

**What worked:** the stub-form ledger fixed round-15's voice-collapse on the *clean* files (the mqtt module docstring came out as 4 genuinely different sentences; no verbatim ledger-lift on ticks/heartbeat). The cut-list + over-cut guard held on those files. Per-param walk landed in triage (all 22 `__init__` params got PARAM lines).

**What FAILED (the user caught the big one by reading `_ca_bundle.py`, which my reader only skimmed):**
1. **Triage stubs drifted back to finished prose on the SOUPY files.** `sockets/_ca_bundle.py.md` had lines like `17 roots covering bulk of modern public HTTPS; strict subset of CP firmware bundle → chain validating here also validates...` — a full em-dash/arrow sentence, not a stub. The stub discipline held on short clean files and broke exactly where the input was a wall of prose.
2. **Writers copied those prose-y stubs near-verbatim.** warm-free + engineer-free `_ca_bundle.py` reproduced the ledger phrasing and the em-dash format — "not forming their own voice," AI-tics, copied em-dashes. The user's words: "you removed strictness, and the agents are not evaluating their own comments after writing them."
3. **Cross-symbol + cross-component leaks survived triage AND writers.** "override at runtime via `set_default_ca_bundle`" (cross-symbol pointer) and "CircuitPython firmware bundle" / "CPython OS trust store" (cross-component) were KEPT by triage and copied by both writers. Double failure: triage should have cut them, writer should have caught them.
4. **Writers skipped params, inconsistently.** `username`/`password` undocumented in some runs (engineer-free run-1 dropped them; but it DID document `username: Optional, paired with password` in at least one other mqtt run — so run-variable, not categorical; my earlier "engineer-free fixed nothing" was an overstatement the user corrected).

**Root-cause the user named, and I confirmed:** when I narrowed round 16 to `-free` (no structure rules), I *also* deleted the **self-review step** that the dropped `light`/`detailed` personas carried ("after each line, read it once; if your eye stops, rebuild it"). Round 14's finding was "structure-rule *enumeration* adds no legibility" — true. But I conflated that with "agents don't need to re-check their output" — false. `free` = write once, never self-check. That is why the leaks and copying survived.

## The user's round-17 decisions

1. **Self-review lives INSIDE each writer** (not a separate reviewer stage). A mandatory final pass.
2. **Fix triage AND writers together** this round (not isolate-variables).
3. **Document ALL args — the `derivable`-means-omit escape hatch is DEAD.** User: "it should comment ALL args. thats how you do doc string. you doc the args. you dont just skip some for no reason." This overrides the round-16 "no silent drops, per-param decision (derivable may omit)" choice.
4. Roster held constant (warm, engineer, linus, elon — all free) so the strictness fix is the only variable. (My call; flagged for veto in the build.)
5. User: be "very strict about this" — the agents are ignoring the reference-only instruction.

## What I built (round-17 package) — all verified on disk

- **Triage** `.claude/agents/commenter-r17-triage.md` — hardened: (a) STUB discipline now bans em-dash clauses, caps ~12 words, one-fact-per-line, and explicitly says it holds HARDEST on soupy files ("the more verbose the source, the more aggressively you fragment"); good/too-finished examples drawn from the actual `_ca_bundle.py` failure; (b) cross-symbol pointers ("see X", "override via Y") and cross-component refs (other package/runtime names, "CP firmware bundle", "CPython OS trust store") are a HARD CUT with a logged CUT line — called out as "the most-missed cut, scan for it explicitly"; (c) every public param gets a PARAM line as a non-derivable stub OR `plain — <gloss>` (never `derivable`, never blank — the writer documents all).
- **4 writers** `.claude/agents/commenter-r17-{warm-free,engineer-free,linus-free,elon-free}.md` — each adds: (a) a "**the ledger is reference, never text to paste**" section (rewrite every stub in own words, never carry its em-dash/arrow, don't staple stubs into one dash-joined line); (b) "**document every parameter**" (Args entry for every param, derivable-omit gone); (c) a **mandatory self-review pass** — re-read every comment as a cold reader and check 6-7 points (copied-the-ledger? em-dash/AI-tic? cross-symbol/component pointer? signature restatement? every param documented? one-pass read? + persona-specific: linus = still professional not rude; elon = terseness didn't drop a fact). Personalities + neutral exemplars (form-validation/token-bucket) carried from r16; exemplar `__init__`s now show a full multi-arg Args block.
- **Inputs**: `round-17/fixing/` + `round-17/stripped/` — copied byte-identical from round 16 (`diff -rq` clean). Only changed variable is the agents. 9 files each.
- **Workflow** `round-17/round-17-workflow.js` — `pipeline()` 9 library-runs; stage1 triage → stage2 `parallel()` 4 writers. 45 agents. ESM-parse-verified OK; references only r17 agents (grep-confirmed zero r16 refs). Triage + writer prompts restate the new rules (document every param, self-review, hard-cut pointers).
- **RUN.md** `round-17/RUN.md` — dispatch runbook: restart, 5 agentTypes, run workflow, verify **27 + 108**, do-not list, analysis notes that name the 3 round-16 faults to re-check AND tell the analysis seat to READ THE HARD FILES IN FULL ACROSS RUNS (the round-16 miss was skimming `_ca_bundle.py`).

## Backup made this session

All 39 `commenter-*.md` agent files backed up to `.scratch/regen-comments/agents-archive/backup-2026-05-30-pre-round17/` (r16 set verified byte-identical to live). `.claude/agents/` is untracked, so this is the only safety net.

## Next concrete step

Hand `round-17/RUN.md` to a fresh dispatch session. Verify 27 + 108. Then a new analysis seat reads ledgers-first and READS `_ca_bundle.py` + `client.py` IN FULL across all 3 runs (not skim): (1) stubs stay fragments on soupy files? (2) writers stopped copying + dropped the pointer/cross-component leaks? (3) every `__init__` param documented incl. username/password, every persona, every run? (4) did the self-review visibly clean things up?

## Riskiest assumption (round 17's bet)

That a self-review pass *inside* the writer actually catches what the writer just produced — an agent grading its own fresh output may rubber-stamp it. If round 17 still shows copying/leaks, the next move is the **separate reviewer stage** the user declined this round (a blind strict reviewer agent reading writer output against the rules). Second bet: hardening triage's anti-prose rules actually holds on soupy files — if `_ca_bundle.py.md` stubs are STILL sentences, the triage agent cannot resist mirroring verbose input and the fix may need a length cap enforced mechanically (post-process the ledger) rather than by instruction.

## Dead ends (don't re-walk)

- `-free` with NO self-review — caused the round-16 copying/leak failure. Self-review is back, inside every writer.
- `derivable`-means-omit param policy — DEAD; document every arg.
- Prose-form ledgers — caused r15 voice-collapse; stubs are the fix (now hardened for soupy files).
- `detailed` 7-point structure arm — no legibility gain (round 14); but note its self-review step was the baby thrown out with the bathwater — that's why r17 re-adds self-review without the structure rules.
- Hand-rolled tokenize stripper — use `python scripts/run.py strip-comments <src> <dst>` (one pair per call; inserts `pass`). (r17 reused r16 stripped; no strip needed.)
- Grep as a comment-quality judge, and skimming the hard files — both cost real misses; READ in full.

## How to rebuild context fast

- **Read first:** `round-17/RUN.md`, then the 5 `commenter-r17-*.md` agents (esp. triage's cut-list + each writer's self-review section).
- **The build is in `.scratch/` (gitignored) + `.claude/agents/` (untracked) + the backup dir.** Only this handoff + the next-up pointer are tracked.
- **Round-16 outputs** at `round-16/runs/` (108) + ledgers at `round-16/triage/` stay for the r16-vs-r17 comparison; `_ca_bundle.py` is the canonical failure exhibit.
- **Memory:** `comment-voice-target`, `cold-write-loses-facts` (update with the r16 result + r17 self-review direction), `run-first-read-all-results` (reinforced: read the hard files, don't skim).

## Gotchas

- **`.claude/agents/` is NOT git-tracked**; `commenter-r17-*` load only at session start. Dispatch is a separate reloaded session handed RUN.md.
- **Tool-output rendering glitches recurred hard this session** — `ls`/`grep`/`wc` output doubled lines and showed phantom files (a "commenter-r16-warm.md" that does not exist). Verify with exit-code probes (`test -f`) and write-to-file-then-Read, not glanced text dumps. The round-16 agent set is exactly 5 (triage + 4 -free); confirmed via per-file `test -f`.
- **`scripts/run.py strip-comments` takes ONE src/dst pair** — call once per library.
- **Don't over-batch dependent tool calls** — a mid-batch error cancels following calls incl. Writes.
- **Read the HARD files in full** (`_ca_bundle.py`, `client.py`) when analyzing — skimming them is how round 16's failure slipped past the first analysis.
- **`.idea/chumicro.iml`** shows modified all session (IDE dirt) — not mine, left unstaged.
