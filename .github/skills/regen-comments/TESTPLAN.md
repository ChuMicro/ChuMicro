# regen-comments — test plan

Two layers:

- **A + B (here):** an agent validates the machinery with mechanical checks and **read-only** clean-room runs
  (auto-keep the ledger, no human picker, never apply). These prove the engine without touching the repo.
- **C (cold session):** the human invokes the skill end-to-end in a fresh session and drives the real gates
  (voice menu, picker, refine/apply/discard). Only layer C exercises the human gates and the apply path.

`SKILL=.github/skills/regen-comments`. **Never modify or commit** `libraries/timing/src/chumicro_timing/heartbeat.py`, `CLAUDE.md`, or `.idea/` (reading is fine). Read-only runs land under `/tmp/regen-cr`.

## Handy targets in this repo
| Genre / scope | Target |
|---|---|
| code (source) | `libraries/kvstore/src/chumicro_kvstore/_mp_nvm.py` (not `heartbeat.py` — protected) |
| test | `libraries/timing/tests/test_ticks.py` |
| functional_test | `libraries/timing/functional_tests/test_ticks_arithmetic.py` |
| example | `libraries/msgpack/examples/packb_basic.py` |
| library (folder / --all) | `libraries/msgpack` (source + tests + functional_tests + examples, no protected files) |
| multi-method (method scope) | `.scratch/regen-comments/voice-test/quality_ranking.py` → `QualityRanking.pick` |

## A. Mechanical checks (fast, no `claude -p`)
| # | Command | Expected |
|---|---|---|
| A1 | `python3 -m py_compile $SKILL/*.py` | no output (all compile) |
| A2 | wrap each `.js` in an async IIFE with stub `phase/agent/parallel/log`, rename `export const meta`→`const meta`, `node --check` | `triage_wf.js` + `writers_wf.js` OK |
| A3 | `python3 $SKILL/genre.py detect <path>` for a `tests/`, `functional_tests/`, `examples/`, and a source path | `test`, `functional_test`, `example`, `code` |
| A4 | `python3 $SKILL/rooms.py new demo` twice | two **different** `/tmp/regen-cr/demo-*` paths |
| A5 | `touch $ROOM/FINAL_plain.py`, then `python3 $SKILL/regen_phase1.py x.py $ROOM` | refused: "already holds a prior run's artifacts" |
| A6 | `python3 $SKILL/verify_code.py <orig.py> <commented-version.py>` | `CODE IDENTICAL` (exit 0); a code-changed file prints `CHANGED` |
| A7 | `python3 $SKILL/splice_symbol.py <orig> <code-drifted-src> <sym> /tmp/o.py` | `REJECTED: ... changed executable code` |
| A8 | fabricate a run room (target + `runs/run-1..4.py` + `pick.json` + flags JSONs + `FINAL_plain.py`), `render_report.py` it | report has a `pickwrap` per symbol, suggested pre-checked, only **differing** passes listed, edit box seeded, sticky Copy-selection bar; extracted `<script>` passes `node --check` |
| A9 | `apply_selection.py parse` a blob with `sym=run-N`, `sym=edit` + fenced `#edit` block, and `#note` lines | JSON carries picks/edits/notes exactly; a `voice` blob parses with `kind: voice` and is **refused** by `apply` |
| A10 | `apply_selection.py apply` that blob, then `verify_code.py <orig> FINAL_plain.py` | splices land (incl. inline comments), a **class** pick takes the class docstring only (methods untouched), multi-line edit re-indented under the symbol, header preserved, `CODE IDENTICAL`; an all-suggested blob is a stated no-op |
| A11 | plant a TIC_PATTERNS phrase in the winner pass's docstring for one symbol, `cp` it to `merged.py`, run `autoroute_tics.py <rundir> plain merged.py` | that symbol spliced from the first clean pass, `pick.json` gains `autoroute`, re-scan shows 0 flags, `CODE IDENTICAL`; report's suggested label reads "auto-routed to writer pass N" |
| A12 | `render_library.py <outdir> plain <roomA>=<origA> <roomB>=<origB>`, then parse a 2-section blob and `apply ... <fileB>` | tabs per file with flag chips; radio names namespaced `pick-f0-*` / `pick-f1-*`; `parse` returns a 2-element array; `apply` without the basename filter is refused, with it only that file's section lands; `CODE IDENTICAL` |
| A12b | give the winner pass an em-dash on one symbol with a clean alternative in another pass, run `autoroute_tics.py` | the symbol routes mechanically (no LLM), `tics.py` reports 0 violations; with NO clean alternative, `polish.py` runs ONE round and writes leftovers to `bans.json`, which report.html shows as a flag card + picker badge |
| A12c | `regen_phase2.py <room> plain --tight` on a room with a kept ledger | every docstring ≤ 2 sentences, zero Args/Returns/Raises sections, self-documenting symbols bare; every ledger fact present (summary or inline `#`); `CODE IDENTICAL`; `<room>/phase2.json` records `{"voice": "plain", "genre": ..., "tight": true, "less": false}` |
| A12d | `regen_phase2.py <room> plain --less` on a room with a kept ledger | summaries ≤ 2 sentences WITH short Args/Returns/Raises where they apply, zero body paragraphs, no entry padded into prose; `phase2.json` records `"less": true`; passing `--tight --less` together is **refused**; `CODE IDENTICAL` |
| A13 | open report.html, pick a non-suggested take, reload (picks restored), then change FINAL and re-render | saved state keys on the FINAL content hash: same content restores picks, changed content starts clean; theme toggle persists across pages and defaults to the OS scheme |
| A14 | `python3 $SKILL/preflight.py --expect-email nobody@example.com` (CLI logged in as anyone else) | **exit 1** + an `ACCOUNT MISMATCH` warning naming both accounts — a mismatch is a hard failure, not advisory; with the CLI's real email it exits 0 |

## B. Clean-room end-to-end (read-only; `claude -p`)
Pattern (no human picker — auto-keep every ledger fact): `regen_phase1.py <target> $RUN --kind <genre>` →
`cp $RUN/ledger_provisional.md $RUN/ledger_final.md` → `regen_phase2.py $RUN plain` → `verify_code.py <target> $RUN/FINAL_plain.py`. (`/tmp/regen-cr/gvalidate.sh <target> <genre> <rundir>` runs the whole pattern.)

| # | Genre / scope | Check |
|---|---|---|
| B1 | code | docstrings state behavior + caller contract, line-mechanics as inline `#`, Args/Returns present; `CODE IDENTICAL` |
| B2 | test | each test docstring = one-sentence claim (subject acting, domain terms), NO Args/Returns/body; above-line comments only on non-obvious setup; `CODE IDENTICAL` |
| B3 | functional_test | claims at end-to-end / scenario altitude; otherwise like B2 |
| B4 | example | a short comment on nearly every meaningful line giving what + why; verb-led module summary + use-case + how-to-run (names no script file); imports preserved; `CODE IDENTICAL` |
| B5 | **method** | run B1 on the multi-method fixture, then `regen_method.py <orig> $RUN plain QualityRanking.pick` → `METHOD_plain.py`; `diff` vs original shows ONLY `pick`'s span changed (other docstrings byte-identical); `CODE IDENTICAL` |
| B6 | **folder** | `regen_batch.py phase1 2 --kind test <two tests/ files>` → two **distinct** `mkdtemp` rooms, a `batch_manifest.json`, each room's `phase1.json` records `genre: test` |
| B7 | **--all** | for each lane (`code` source / `test` / `functional_test` / `example`) of one library, run B6-style `regen_batch phase1 --kind <lane>` → fresh rooms per lane, **no collisions** across lanes (genre-prefixed room names) |
| B8 | **refine keeps the run shape** | on a finished `--tight` room, `regen_symbol.py $RUN plain <sym>` → that symbol is STILL ≤ 2 sentences with no sections (phase2.json honored — the old bug regenerated it in default code shape); same check on a `--less` room (sections stay, summary stays ≤ 2 sentences) and a `--kind test` room (stays a one-sentence claim); `CODE IDENTICAL` |

## C. Cold-session script (the human invokes the skill)
Run each in a fresh session. Confirm the resolution + gates, then Discard (or Apply on one to test the write).

| # | Invocation | Expect |
|---|---|---|
| C1 | `/regen-comments <a source file>` | voice = **numbered TEXT menu** (type a number, lists the whole registry, no `Invalid tool parameters`); genre `code`; phase 1 (3 lenses + validator); picker; report auto-opens; refine/apply/discard loop |
| C2 | `/regen-comments kvstore library` | resolves to the library **source**, genre `code`, **confirms** target+genre+scope; builds LIBRARY_FACTS once; per-file |
| C3 | `/regen-comments kvstore unit tests` (or `--tests`) | **verifies `tests/` exists**, genre `test`; claim docstrings, no Args/Returns |
| C4 | `/regen-comments <a functional_tests/ file>` | genre `functional_test`; scenario-altitude claims |
| C5 | `/regen-comments <an examples/ file>` | genre `example`; dense per-line annotation; how-to-run names no script file |
| C6 | `/regen-comments the <method> in <file>` | **method scope**: report shows only that one symbol; rest of file untouched |
| C7 | `/regen-comments <lib> --examples` | example lane over the `examples/` folder |
| C8 | `/regen-comments <lib> --all` | **push-back on cost** first; on confirm, four lanes (source/test/functional_test/example) |
| C9 | `/regen-comments --voice cantrill <file>` | **no voice menu** (voice preset); rest as C1 |
| C10 | `/regen-comments <a source file> --tight` | summary-only docstrings (1–2 sentences, no Args/Returns/body) on every non-bare symbol; in the refine loop, exhaust the 4 cached takes on one symbol so `regen_symbol.py` fires → the fresh take is **still tight**. Repeat with `--less` → same summaries but WITH short Args/Returns/Raises sections |
| C11 | on any C1 run, drive the refine loop deep: **tighten** a symbol, **edit the facts → add** a deliberately wrong fact, add a **NOTE(initials)**, then drop a ledger fact | tighten prints KEPT/DROPPED (push-back on DROPPED); the wrong fact comes back contradicted → push-back; the NOTE lands verbatim at the symbol; the ledger drop triggers `drift_check` offering stale symbols |
| C12 | `/regen-comments --create-voice` | name → clean-room draft → free-text edit → test run on a real target (report rendered, nothing applied) → save on accept; the new voice then appears in the menu with a preview |
| C13 | `/regen-comments <file> --without-comment-triage` | runs purely from code (no comment lens); existing header (copyright/license) still preserved mechanically |
| C14 | run preflight with a deliberately wrong `--expect-email` mid-C1 | the run **stops** at step 0 with the mismatch named; it proceeds only after you explicitly agree (never silently) |

Gate-fix confirmations (call these out during the above):
- **voice menu** lists every voice and never errors (the old 5-option `AskUserQuestion` is gone).
- **picker** with exactly 1 questionable fact → a 2-option **Keep / Drop** (not an error); with 5+ → a numbered text list to drop.
- **two parallel invocations** of the skill → **distinct** rooms (no shared dir, no stale-artifact poisoning).
- every run: `CODE IDENTICAL` reported before the report; the report auto-opens; **nothing is committed** automatically; apply writes to the working tree only on explicit confirm.
