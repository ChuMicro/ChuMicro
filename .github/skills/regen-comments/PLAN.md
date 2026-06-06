# regen-comments — build & rollout plan

Companion to `SKILL.md`. Decisions locked 2026-06-06: one voice per run (4-voice menu, default `cutler`;
`--voice <key>` for any; `--create-voice` mode); **4 passes**; **all opus**; **finalize as a package,
don't install yet**.

## 1. Status: validated vs remaining

| stage | validated? | artifact |
|---|---|---|
| mechanical strip | ✅ tested (AST-identical, runs) | `strip.py` |
| clean-room isolation (`claude -p` from `/tmp`) | ✅ proven vs real project `CLAUDE.md` | — |
| triage workflow in one `claude -p` | ✅ capstone (all traps, domain fact) | `triage_wf.js` (EXPERIMENT) |
| ledger validator (generic gate) | ✅ test-instrument caught weak fact | validator prompt (must genericize) |
| picker (AskUserQuestion, after ledger-writer, subtractive) | ✅ exp13 | orchestrator |
| writer workflow in one `claude -p` | ✅ capstone (5/5, all traps) | `writers_wf.js` (EXPERIMENT) |
| per-symbol consolidation merge | ✅ mixed per method/class, code-identical | consolidation prompt |
| reattach (preserve lane) | ✅ tested, parameterized | `reattach.py` |
| voices-as-data registry | ✅ | `voices.json` |

**Clean (no fixture knowledge):** `SKILL.md`, `voices.json`, `strip.py`, `reattach.py`.
**Still EXPERIMENT (carry baked fixture knowledge — must genericize, §2):** `triage_wf.js`, `writers_wf.js`.

## 2. Genericize the workflow scripts (REQUIRED before any real-file run)

The exp13/exp14 workflow scripts worked partly because their examples/traps matched `quality_ranking.py`.
Production must be fixture-agnostic:

- **`triage_wf.js` — ledger-writer STUB-STYLE example → NEUTRAL.** Replace the `disable_extension/base_only`
  GOOD/BAD example with an invented, off-target one that teaches the *form* of a telegraphic inversion stub.
  e.g. `GOOD: flag X=True -> chosen=side_A (lacks Y); the dropped Y is side_B's (the rejected side), never the chosen's`
  with invented identifiers, no real-file symbols. (Per `[[agent-examples-must-be-neutral]]`.)
- **`writers_wf.js` — judge → GENERIC + per-symbol.** (a) Delete the hardcoded `JUDGE_TRAPS`/`TRAPS`
  (the 7 fixture traps). (b) Swap the per-PASS judge for the validated **per-symbol consolidation** prompt.
  The generic judge: *for each symbol, verify every docstring/comment claim against the code; confirm each
  must-carry fact FROM THE LEDGER that pertains to the symbol is present; flag cruft-leak / verbatim
  ledger-lift; pick the best candidate per symbol and assemble.* No trap list, no `Cep25`.
- **Paths → args/relative** so the orchestrator points them at the run's `/tmp` rooms (not hardcoded).
- **Judge prompt PASSES-aware** (no hardcoded `run-3`).
- **Ledger validator → generic** (per-fact correctness + explicitness of correctness-critical *classes*;
  no trap list, no `t7_explicit`).

## 3. The orchestrator (top-level driver — the main build left)

In-session procedure (SKILL.md, made concrete). A thin driver handles the mechanical + launch steps; the
orchestrator (you) handles the two `AskUserQuestion` gates (headless `claude -p` can't ask).

1. Parse flags: `--voice`, `--with-comment-triage`, `--create-voice`.
2. `--create-voice` → §4 and stop.
3. Voice gate: `--voice` or the 4-voice menu (default cutler).
4. `strip.py` → stripped code; set up `/tmp/regen-cr/<run>/` rooms (per-lens, comment-lens, ledger,
   writer×4, judge).
5. Launch **triage `claude -p`** (`triage_wf.js`) → provisional ledger + preserve.json + questionable list.
6. Launch **validator `claude -p`** on the ledger; if a correctness-critical fact is wrong/under-specified,
   re-run the ledger-writer (or feed the note back); escalate to human if it won't converge.
7. **Picker** (AskUserQuestion, multi-select) on the questionable facts + borderline preserve items →
   assemble the final ledger (drop rejected).
8. Launch **writer `claude -p`** (`writers_wf.js`: chosen voice, 4 passes, per-symbol consolidation) →
   merged candidate.
9. Launch **verifier `claude -p`** (§5) → flags.
10. `reattach.py <merged> <preserve.json> <out>` → finished file.
11. Present; human reviews + applies. **Never auto-commit.**

## 4. `--create-voice` flow
Prompt for a voice key + a one-line persona paragraph. Validate: a named person OR a disposition, a SINGLE
clause, NO rule-work inside it (`[[personas-clean-one-clause]]`, `[[natural-disposition-over-rules]]`).
Append to `voices.json`. Exit without commenting any file.

## 5. The verifier (Step 5) spec
A clean-room `claude -p` cold-reader on the merged candidate (generic, no trap list): fabrication check;
tic-density at **human level, not zero** (`[[no-tics-is-a-warning-sign]]`); cruft-leak (no copyright/author/
tracker-ref/stale-wrong claim); no phrase lifted verbatim from the ledger; cadence-split (load-bearing
contrast ≠ tic). Emits a flag list for the human; does not edit. (Open: separate `claude -p` vs folded into
the consolidation judge — default separate for a fresh-eyes pass; revisit.)

## 6. Real-file finale (generalization + library-awareness) — TARGETS CHOSEN (user, 2026-06-06)

Two real chumicro libraries, run in this order (small single-file first, then library-aware):

**6a. Single-file sanity — `libraries/timing/src/chumicro_timing/ticks.py`** (69 LOC, real, already used in
prior comment work). Validates the GENERICIZED scripts on real code: a real file has its own non-derivable
facts and ZERO T7/Cep25, so only the neutral example + generic judge can work — the clean test that §2 is
truly fixture-agnostic. Run the single-file pipeline (with `--with-comment-triage`, since it has real
comments to mine). Fast, no library context yet.

**6b. Library-aware finale — `libraries/kvstore/` (`src/chumicro_kvstore/`, 8 files, 798 LOC).** Structure:
`core.py` (277, the KVStore + backend contract) + 4 backends (`cp_nvm`, `mp_littlefs`, `mp_nvs`, `memory`)
+ `__init__.py` + `testing.py`. Genuine cross-file coupling (backends implement a `core` protocol; shared
terms `namespace`/`key`/`backend`) → the real test of library-awareness.
- **Broad triage** reads the kvstore subtree once (copied into `/tmp`) → a **library ledger**: domain
  identity ("key-value store with pluggable backends"), the **core↔backend contract**, cross-file
  relationships, shared terminology.
- **Per file** (loop): strip → triage (the library ledger rides into the room as extra context) → validate →
  picker → writers → consolidate → verify → reattach. One voice across the batch.
- **The library ledger is how a narrow per-file writer gets broad awareness cheaply** — don't fatten the
  writer.
- Open design (sign-off when we reach 6b): library-ledger shape + exactly how it rides into each per-file
  room; how the broad triage scopes which files to read first (core before backends); cross-file
  `--with-comment-triage`.

## 7. Multi-file
Loop the single-file procedure per file, sharing the library ledger. One voice across the batch.

## 8. Install (deferred — package for now)
After §2 (genericize) and §6 (real-file validation): move `SKILL.md` + scripts + `voices.json` to the skill
directory. Decide replace-vs-new for the existing `regen-comments` skill at that time (the current one
predates the clean-room/claude-p design).

## 9. Open design questions (still pending user input)
- ~~Which chumicro library for the §6 finale?~~ ANSWERED (user): `timing/ticks.py` single-file sanity, then `kvstore/` library-aware finale.
- **Library-ledger shape/scope** — proposal in §6; needs sign-off when we get there.
- **Verifier: separate `claude -p` vs folded into the consolidation judge** (default: separate).
- **Existing `regen-comments` relationship at install** (deferred to install time).
- **Cost ceiling** — all-opus × 4 passes × (lenses + ledger + writers + judges) is real spend per file;
  revisit a cheaper tier only if it bites on large files.

## 10. Anti-contamination invariant (carry forward)
Test instruments (the 7-trap correctness judge, the `t7_explicit` validator, fixture-matched examples) are
for MEASURING the pipeline on `quality_ranking.py`. They must NEVER ship in the skill. Every production
layer is fixture-agnostic: it reasons from THIS file's code + THIS run's ledger, never a known trap list.
