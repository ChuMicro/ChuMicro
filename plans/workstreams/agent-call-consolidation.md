# Workstream: clean-room agent-call consolidation — cut per-pipeline `claude -p` / agent dispatches

Status: **proposed.**  From the 2026-06-12 next-up bullet: the clean-room pipelines accrete one agent
per concern (writers, selector, summarizer, polish, legibility, speaker, drift checks) and the count
needs cutting back or merging into same-run tasks.  This file is the inventory half — call counts per
pipeline and a merge-candidate table.  Line numbers were read from code on 2026-06-12; re-derive before
editing a dispatch.

## Problem

Each pipeline gained agents one concern at a time, and a concern that could ride an existing agent's
single read instead got its own `claude -p`.  A regen-comments run on one file fires 11 base dispatches
across three clean rooms; audit-code fires 10-16; audit-branch 11-17; audit-skill 7.  Several are
genuine blind readers whose independence is the point and must stay separate.  Others — a one-shot
legibility scan, a fact-drift eye, a page-prose pass — read the same finished file an adjacent agent
already has open and could fold into it.  The inventory below names every dispatch site so a merge can
be judged per pair, not waved at.

## Per-pipeline call inventory

Counts are per single-target run, plain voice.  "Singleton" fires once regardless of target size;
"×N" multiplies on the named list.  Retry pairs fire only when the validator does not converge.

| Pipeline | Site (file:line) | Concern | Singleton / multiplier |
|---|---|---|---|
| regen-comments P1 | `regen_phase1.py:82` (hosts `triage_wf.js`) | 3 code lenses + comment lens + ledger-writer + validator loop, one room | 1 host `claude -p` (≥6 agents inside) |
| regen-comments P2 | `writers_wf.js:344` | writer pass | ×PASSES (=4) |
| regen-comments P2 | `writers_wf.js:345` | independent summarizer | singleton |
| regen-comments P2 | `writers_wf.js:348` | best-of-N selector | singleton |
| regen-comments P2 | `polish.py:51` (via `regen_phase2.py:84`) | mechanical-ban rewriter | singleton (≤1 round, conditional on a tic surviving autoroute) |
| regen-comments P2 | `flag_legibility.py:52` (via `regen_phase2.py:95`) | legibility flagger (flag-only) | singleton |
| regen-comments P0 | `regen_phase0.py:77` | library-facts triage | singleton, **library/dir scope only** |
| regen-comments refine | `drift_check.py:38` | post-edit fact-drift scan | on-demand, per ledger edit |
| regen-comments refine | `stubify_fact.py:47` | add-fact validator | on-demand |
| regen-comments refine | `tighten_symbol.py:63` | fact-preserving shorten | on-demand |
| audit-code eval | `audit_wf.js:417` | summarizer (independent what-it-does) | singleton |
| audit-code eval | `audit_wf.js:418-422` | 5 lenses: trap / hazard / drift / coverage / clarity | singleton each |
| audit-code eval | `audit_wf.js:438` | merger → fact ledger | singleton |
| audit-code eval | `audit_wf.js:442` | validator | singleton |
| audit-code eval | `audit_wf.js:447-448` | merger + validator re-run | ×0-3 pairs (`MAX_ATTEMPTS=4`) |
| audit-code eval | `audit_wf.js:460` | writer (reader prose in voice) | singleton |
| audit-code eval | `audit_wf.js:461` | patcher (apply-ready before/after) | singleton |
| audit-code P0 | `audit_phase0.py:61` | library-facts context | singleton, **library/folder scope only** |
| audit-code usage-path | `usage_path_wf.js:84` | feature mapper | singleton, opt-in |
| audit-code usage-path | `usage_path_wf.js:119` | seed judge | ×SEEDS, opt-in |
| audit-code usage-path | `usage_path_wf.js:133` | path-prose writer | singleton, opt-in |
| audit-code usage-path | `usage_trace.py:198` | blind cross-check | singleton, opt-in |
| audit-branch eval | `branch_wf.js:479` | summarizer | singleton |
| audit-branch eval | `branch_wf.js:480-485` | 6 lenses: trap / integration / usage / intent / coverage / craft | singleton each |
| audit-branch eval | `branch_wf.js:501` | merger | singleton |
| audit-branch eval | `branch_wf.js:505` | validator | singleton |
| audit-branch eval | `branch_wf.js:510-511` | merger + validator re-run | ×0-3 pairs (`MAX_ATTEMPTS=4`) |
| audit-branch eval | `branch_wf.js:523` | writer | singleton |
| audit-branch eval | `branch_wf.js:524` | patcher | singleton |
| audit-branch P0 | `branch_phase0.py:125` | feature-facts context | singleton, default on multi-file change-sets |
| audit-skill | `_shared/audit_wf.js:113-222` | 7 lenses: loader / cold-walk / craft / orchestration / surprise / ideas / research | singleton each |
| audit-skill report | `_shared/speak_wf.js:123` | speaker render pass | ×PASSES(=2) per chunk (CHUNK=12) |
| audit-skill report | `_shared/speak_wf.js:127` | per-chunk selector | ×chunks (when >1 pass) |
| audit-skill report | `_shared/speak_wf.js:143` | page-prose speaker | singleton |
| audit-skill report | `_shared/speak_wf.js:157` | unrendered-id retry | conditional singleton |

Base totals (no opt-in usage-path, no validator retries, small report):

- **regen-comments:** 1 P1 host + (4 writers + 1 summarizer + 1 selector) + 1 polish + 1 legibility = **8 base dispatches** (P0 +1 in dir scope; refine scripts on demand).
- **audit-code:** 1 summarizer + 5 lenses + 1 merger + 1 validator + 1 writer + 1 patcher = **10** (up to 16 with 3 retry pairs; usage-path +2+SEEDS; P0 +1 in library scope).
- **audit-branch:** 1 summarizer + 6 lenses + 1 merger + 1 validator + 1 writer + 1 patcher = **11** (up to 17 with retries; P0 +1 default multi-file).
- **audit-skill:** 7 lenses + speaker (≈2 render + 1 select per 12-id chunk + 1 page) ≈ **11** for a one-chunk report.

## Merge candidates

Each row: what the pair shares, what a merge loses, and the saving.  A merge that folds a blind reader
into the agent it judges is **not** a candidate — blindness is a harness-enforced invariant
(clean-room-pipeline.md invariants 1-2, 9), and the rows below leave every blind reader standing.

| # | Merge | Shares | Lost by merging | Saving / run |
|---|---|---|---|---|
| 1 | regen-comments **legibility flag → speaker pass** (when the report speaker exists) | both read the one finished file's prose | nothing structural — the speaker already reads every prose bit; a fact-drift + legibility eye is a few lines of its prompt, not a second read | -1 (vs adding a new fact-drift agent); this is the user's worked example, see below |
| 2 | regen-comments **independent summarizer (`writers_wf.js:345`) ← P1 triage** | both derive a plain-English what-it-does from stripped code | the summarizer is deliberately blind to the generated comments so the human checks the comments against a read they did not write; the P1 triage feeds the writers.  Folding them would let triage facts color the summary | none — keep separate (blindness candidate, rejected) |
| 3 | audit-code/branch **writer + patcher** (`audit_wf.js:460-461` / `branch_wf.js:523-524`) | both read the converged `eval.json` by id, already parallel in one phase | the writer composes prose, the patcher reads code for before/after — different outputs, different inputs (prose vs code); one agent doing both dilutes each.  They run concurrently already, so no latency saving and the split is deliberate | none — keep separate |
| 4 | audit-skill **per-chunk selector → render pass** (`speak_wf.js:127` ← `:123`) | the selector picks among passes the same agent could rank | the selector's whole value is judging passes it did not write; self-selection reintroduces the tic-heavy roll best-of-N exists to escape (`speak_wf.js:120` comment) | none — keep separate (blindness candidate, rejected) |
| 5 | audit-skill **page-prose speaker → a chunk speaker** (`speak_wf.js:143`) | both are the same speaker persona on the same ledger, already in one `parallel` | the page carries intro / gate wording, not finding cards; folding it into a chunk agent couples coverage-barrier logic to page text and the page's single-pass regime (`:142` comment) to the chunks' best-of-N.  Marginal saving, real coupling | -1 nominal, not worth the coupling — keep separate |
| 6 | **drop the regen-comments report speaker's would-be fact-drift agent** | the fact-drift eye and `flag_legibility` both judge the one finished file as English | nothing — `flag_legibility` already opens the finished file; a drift clause is prompt text, not a read | -1 (a new agent avoided); same as #1, stated from the speaker side |

The honest read: the **only** safe structural merges are #1 / #6 — and both are *avoided additions*, not removals of an existing pair.  The blind readers (summarizer, lenses, selector, validator) each carry an independence the pipelines were built around; merging any of them trades a deliberate property for one fewer call and is rejected above.  The writer/patcher pair already runs concurrently in one phase, so splitting them costs no extra round and merging them dilutes two distinct outputs.

### The user's worked example, checked against code

> a voiced-report speaker's fact-drift check folds into the existing `flag_legibility` call instead of becoming a new agent.

**It holds — but only for regen-comments, and only forward.**  Three facts from the code:

- `flag_legibility` exists **only in regen-comments** (`flag_legibility.py`, wired at `regen_phase2.py:95`).  No audit pipeline has it.
- The **speaker** (`speak_wf.js`) runs **only in audit-skill** today (`audit-skill/SKILL.md:199`); audit-code and audit-branch voice findings with their in-workflow **writer** (`audit_wf.js:460` / `branch_wf.js:523`), not the speaker.
- The audit-skill speaker has **no fact-drift agent** — its "ledger facts only, never add / drop / soften" is a prompt line (`audit-skill/SKILL.md:345`), not a dispatch.

So no two existing agents match the example.  Its real referent is the **not-yet-built regen-comments report speaker** (workstream `regen-report-voiced-speaker.md`, item 4): when that speaker lands, the temptation is to give it a new fact-drift agent to confirm it did not invent facts.  The example's call is to instead fold that fact-drift eye (plus the legibility eye) into the **existing `flag_legibility` call**, which already reads the finished file.  Net effect: the report speaker ships with **zero** new judging agents.  The example is sound as a design rule; it just describes an addition-to-avoid, not a merge of two live agents.

## Implementation phases

Ordered safe merges first.  Each phase is one pipeline and one coherent commit.  The two safe phases are
both addition-avoidance — they constrain how the report speaker gets built rather than removing a live
call — so they land alongside the speaker work, not before it.

1. **regen-comments report speaker — no new fact-drift agent.**  When the `regen-report-voiced-speaker.md`
   speaker is implemented, extend `flag_legibility.py`'s prompt to also flag a sentence whose facts drift
   from the ledger / stripped code, instead of dispatching a separate drift agent for the voiced bits.
   One pipeline, one commit, in lockstep with the speaker landing.  (User's worked example.)
2. **audit-skill report speaker — fold page-prose only if a measured saving appears.**  Re-measure
   chunk counts on real reports; if most reports are one chunk, the page-prose singleton (`speak_wf.js:143`)
   is one call and the coupling cost (candidate #5) outweighs the saving — leave it.  This phase is a
   measurement gate, not a guaranteed change; close it with the count and the verdict.
3. **No further merges without a blindness review.**  The summarizer / lens / selector / validator
   dispatches each encode an independence invariant; any future proposal to merge one rewrites a
   clean-room invariant and routes through `new-decision`, not this workstream.

## Validation history

- (none yet)
