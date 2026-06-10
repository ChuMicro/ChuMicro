# regen-comments bench35 + tight mode — RESULTS (2026-06-10)

## Outcome (bench complete; same file/voice as the stuffed live run)
| arm | docstring lines | inline # | Args/Ret sections | max sentences | bare symbols |
|---|---|---|---|---|---|
| baseline (live cutler) | 120 | 7 | 6 | 14 | 0 |
| default (anti-stuffing) | 77 | 5 | 5 | 7 | 0 |
| tight (--tight) | 2 (module only) | 17 | 0 | 1 | 7 |

Both CODE IDENTICAL. Phase-1 parsimony: 11 -> 5 facts, glosses present. Default-arm autoroute fired
for real (3 symbols routed to pass 1), bans.json = 0. Selector whys cite altitude/no-docstrings-on-evident.
CALIBRATION QUESTION for the user: tight arm put the caller contract in #-comments ABOVE defs and zero
symbol docstrings; possibly want 1-sentence docstrings (help()-visible) + # comments for line facts instead.

## What's running (background, this machine)
- Bench of the anti-stuffing prompt changes (commit e49295dd) + new --tight mode, on
  libraries/timing/src/chumicro_timing/testing.py (the file the live run stuffed 4x).
- Phase 1 DONE: room $(cat /tmp/bench35-room) = /tmp/regen-cr/bench35-testing-9cfp30fs
  - RESULT: 5 facts kept (baseline live run: 11) — parsimony rule working; all facts carry plain-English glosses.
- Phase 2 arm A (default prompts, cutler): same room. Arm B (--tight, cutler): /tmp/regen-cr/bench35-testing-9cfp30fs-tight
  - Both launched ~00:01; all 4 writer passes landed per arm; awaiting selector/polish/FINAL.

## To finish the bench (next session / post-compaction)
1. When FINAL_cutler.py exists in both rooms, measure each:
   docstring lines vs baseline 120 / code 32 (ast walk, count docstring node lines), inline-comment count,
   verify_code.py vs the original target, pick.json why (should cite proportion not richness),
   autoroute/bans.json behavior.
2. Tight arm checks (TESTPLAN A12c): every docstring ≤2 sentences, NO Args/Returns/Raises, bare
   self-documenting symbols, ledger facts present (summary or inline #).
3. Baseline rooms for comparison: /tmp/regen-cr/code-testing-x8hp8aym/v/{cutler,torvalds,bourdain}
   (live run, 3.4–3.8x doc/code ratio).
4. Report 3-way comparison to the user; if tight arm passes, the --tight commit (already landed) is validated;
   note bench result on the next-up round-35 bullet.

## Live user run (their other session)
Their library comparison run continues under pre-fix prompts; remedy offered: prune ledger_final.md per room
+ re-run regen_phase2.py in-room to pick up new prompts.
