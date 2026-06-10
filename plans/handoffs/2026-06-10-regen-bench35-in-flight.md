# regen-comments bench35 + tight mode — in-flight state (2026-06-10)

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
