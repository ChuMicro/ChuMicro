# regen-comments — test plan

Three layers:

- **A + B (here):** an agent validates the machinery with mechanical checks and **read-only** clean-room runs
  (auto-keep the ledger, no human picker, never apply). These prove the engine without touching the repo.
- **C (cold session):** the human invokes the skill end-to-end in a fresh session and drives the real gates
  (voice menu, picker, refine/apply/discard). Only layer C exercises the human gates and the apply path.
- **D (routing):** trigger evals against the frontmatter — does the loader send the right requests here and
  the near-miss requests to the sibling skill they belong to. Queries live in `trigger-evals.json`.

`SKILL=.github/skills/regen-comments`. **Never modify or commit** `libraries/timing/src/chumicro_timing/heartbeat.py`, `CLAUDE.md`, or `.idea/` (reading is fine). Read-only runs land under `/tmp/regen-cr`.

## Handy targets in this repo
| Genre / scope | Target |
|---|---|
| code (source) | `libraries/kvstore/src/chumicro_kvstore/core.py`, or any trap-rich source file of similar size (not `heartbeat.py` — protected) |
| test | `libraries/timing/tests/test_ticks.py` |
| functional_test | `libraries/timing/functional_tests/test_ticks_arithmetic.py` |
| example | `libraries/msgpack/examples/packb_basic.py` |
| library (folder / --all) | `libraries/msgpack` (source + tests + functional_tests + examples, no protected files) |
| multi-method (method scope) | a small multi-method file under `.scratch/` (machine-local; fabricate one if absent — a function plus a class with two methods is enough), targeting one method, e.g. `Counter.bump` |

## A. Mechanical checks (fast, no `claude -p`)
| # | Command | Expected |
|---|---|---|
| A1 | `python3 -m py_compile $SKILL/*.py` | no output (all compile) |
| A2 | wrap each `.js` in an async IIFE with stub `phase/agent/parallel/log`, rename `export const meta`→`const meta`, `node --check` (needs `node` on PATH; absent → record the row as blocked, don't skip silently) | `triage_wf.js` + `writers_wf.js` OK |
| A3 | `python3 $SKILL/genre.py detect <path>` for a `tests/`, `functional_tests/`, `examples/`, and a source path | `test`, `functional_test`, `example`, `code` |
| A4 | `python3 $SKILL/rooms.py new demo` twice | two **different** `/tmp/regen-cr/demo-*` paths |
| A5 | `touch $ROOM/FINAL_plain.py`, then `python3 $SKILL/regen_phase1.py x.py $ROOM` | refused: "already holds a prior run's artifacts" |
| A6 | `python3 $SKILL/verify_code.py <orig.py> <commented-version.py>` | `CODE IDENTICAL` (exit 0); a code-changed file prints `CHANGED` |
| A7 | `python3 $SKILL/splice_symbol.py <orig> <code-drifted-src> <sym> /tmp/o.py` | `REJECTED: ... changed executable code` |
| A8 | fabricate a run room (target + `runs/run-1..4.py` + `pick.json` + flags JSONs + `FINAL_plain.py`), `render_report.py` it | report has a `pickwrap` per symbol, suggested pre-checked, only **differing** passes listed, edit box seeded, sticky Copy-selection bar; extracted `<script>` passes `node --check` |
| A9 | `apply_selection.py parse` a blob with `sym=run-N`, `sym=edit` + fenced `#edit` block, and `#note` lines | JSON carries picks/edits/notes exactly; a `voice` blob parses with `kind: voice` and is **refused** by `apply` |
| A10 | `apply_selection.py apply` that blob, then `verify_code.py <orig> FINAL_plain.py` | splices land (incl. inline comments), a **class** pick takes the class docstring only (methods untouched), multi-line edit re-indented under the symbol, header preserved, `CODE IDENTICAL`; an all-suggested blob is a stated no-op |
| A11 | plant a TIC_PATTERNS phrase in the winner pass's docstring for one symbol, `cp` it to `merged.py`, run `autoroute_tics.py <rundir> plain merged.py` | that symbol spliced from the first clean pass, `pick.json` gains `autoroute`, re-scan shows 0 flags, `CODE IDENTICAL`; the page's selection-rationale section lists the auto-route |
| A12 | `render_library.py <outdir> plain <roomA>=<origA> <roomB>=<origB>`, then parse a 2-section blob and `apply ... <fileB>` | one faceted page (`<outdir>/picker.html`) with a file dropdown; card ids namespaced `<file.py>#<sym>`; `parse` returns a 2-element array; `apply` without the basename filter is refused, with it only that file's section lands; `CODE IDENTICAL` |
| A12b | give the winner pass an em-dash on one symbol with a clean alternative in another pass, run `autoroute_tics.py` | the symbol routes mechanically (no LLM), `tics.py` reports 0 violations; with NO clean alternative, `polish.py` runs ONE round and writes leftovers to `bans.json`, which the decision page shows in its flags section + as a card warning |
| A12c | `regen_phase2.py <room> plain --tight` on a room with a kept ledger | every docstring 1 sentence (max 2), behavior/contract only, **zero** bodies and **zero** Args/Returns/Raises sections; traps + mechanics as `#` comments at their lines; self-documenting symbols bare; facts present as clean sentences or deliberately dropped (never crammed); `CODE IDENTICAL`; `<room>/phase2.json` records `{"voice": "plain", "genre": ..., "tight": true, "less": false}` |
| A12d | `regen_phase2.py <room> plain --less` on a room with a kept ledger | **single sentence summary lines** WITH short Args/Returns/Raises where they apply; bodies **tiny (≤ 2 sentences) and rare (a few spots, never most symbols)**; docstrings behavior/contract only (traps + mechanics in `#` comments); no entry padded into prose; `phase2.json` records `"less": true`; passing `--tight --less` together is **refused**; `CODE IDENTICAL` |
| A13 | open picker.html, pick a non-suggested take, reload (picks restored), then change FINAL and re-render | saved state keys on the FINAL content hash (the spec `key`): same content restores picks, changed content starts clean; theme toggle persists and defaults to the OS scheme |
| A14 | `python3 $SKILL/preflight.py --expect-email nobody@example.com` (CLI logged in as anyone else) | **exit 1** + an `ACCOUNT MISMATCH` warning naming both accounts — a mismatch is a hard failure, not advisory; with the CLI's real email it exits 0 |
| A15 | `REGEN_NO_OPEN=1 serve_report.py <fabricated room>` in the background, `curl` GET the report URL, then POST a blob to `/selection` | GET returns 200; stdout printed `SERVING <url>` then one `SELECTION RECEIVED -> <path>` line; `selection.txt` byte-equals the posted blob and `apply_selection.py parse` reads it; the room's FINAL is untouched by the server; renderers under `REGEN_NO_OPEN=1` print the link without opening a browser |

## B. Clean-room end-to-end (read-only; `claude -p`)
Pattern (no human picker — auto-keep every ledger fact): `regen_phase1.py <target> $RUN --kind <genre>` →
`cp $RUN/ledger_provisional.md $RUN/ledger_final.md` → `regen_phase2.py $RUN plain` → `verify_code.py <target> $RUN/FINAL_plain.py`. Script the pattern into a throwaway driver under `.scratch/` when running several rows; `/tmp` artifacts from prior sessions don't survive, so never depend on one.

After a B-run, also skim the phase's `claude -p` transcript (session log under `~/.claude/projects/` keyed by the room's cwd) for wasted motion — re-derived facts the ledger already carried, improvised helper scripts, retries. Waste that repeats across runs means a workflow prompt needs a tweak; the artifacts alone don't show it.

| # | Genre / scope | Check |
|---|---|---|
| B1 | code | docstrings state behavior + caller contract, line-mechanics as inline `#`, Args/Returns present; `CODE IDENTICAL` |
| B2 | test | each test docstring = one-sentence claim (subject acting, domain terms), NO Args/Returns/body; above-line comments only on non-obvious setup; `CODE IDENTICAL` |
| B3 | functional_test | claims at end-to-end / scenario altitude; otherwise like B2 |
| B4 | example | a short comment on nearly every meaningful line giving what + why; verb-led module summary + use-case + how-to-run (names no script file); imports preserved; `CODE IDENTICAL` |
| B5 | **method** | run B1 on the multi-method fixture, then `regen_method.py <orig> $RUN plain <Class.method>` → `METHOD_plain.py`; `diff` vs original shows ONLY that method's span changed (other docstrings byte-identical); `CODE IDENTICAL` |
| B6 | **folder** | `regen_batch.py phase1 2 --kind test <two tests/ files>` → two **distinct** `mkdtemp` rooms, a `batch_manifest.json`, each room's `phase1.json` records `genre: test` |
| B7 | **--all** | for each lane (`code` source / `test` / `functional_test` / `example`) of one library, run B6-style `regen_batch phase1 --kind <lane>` — two files per lane (or the lane's full set when smaller); the row validates batching mechanics, not content, so don't burn a whole library on it → fresh rooms per lane, **no collisions** across lanes (genre-prefixed room names) |
| B8 | **refine keeps the run shape — and is actually fresh** | on a finished `--tight` room, `regen_symbol.py $RUN plain <sym>` → that symbol is STILL ≤ 2 sentences with no sections (phase2.json honored — the old bug regenerated it in default code shape); same check on a `--less` room (sections stay, summary stays ≤ 2 sentences) and a `--kind test` room (stays a one-sentence claim); `CODE IDENTICAL`. **Freshness is part of the row**: after the run, `runs/run-1..4.py`, `pick.json`, AND `merged.py` all carry post-launch mtimes, and the spliced take matches the new winner — a shape-only check passes on a stale splice (the 2026-06-10 bug: the workflow died mid-flight / `merged.py` was never re-copied, and the old take re-shipped as "regenerated") |

## C. Cold-session script (the human invokes the skill)
Run each in a fresh session. Confirm the resolution + gates, then Discard (or Apply on one to test the write).
Only a live interactive session can drive these gates — `claude -p` is headless (`AskUserQuestion` cannot fire there), so an agent cannot run layer C for you. What an agent CAN do afterward: each C-run leaves its room under `/tmp/regen-cr`, so a follow-up session can verify the mechanical outcomes from the artifacts (`verify_code.py` vs the original, distinct rooms across parallel runs, `bans.json` / `tics.json` / `legibility.json` contents, nothing committed).

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
| C10 | `/regen-comments <a source file> --tight` | 1–2 sentence behavior-only docstrings with nothing after them (traps/mechanics as `#` comments) on every non-bare symbol; in the refine loop, exhaust the 4 cached takes on one symbol so `regen_symbol.py` fires → the fresh take is **still tight**. Repeat with `--less` → adds rare tiny bodies + short Args/Returns/Raises sections |
| C11 | on any C1 run, drive the refine loop deep: **tighten** a symbol, **edit the facts → add** a deliberately wrong fact, add a **NOTE(initials)**, then drop a ledger fact | tighten prints KEPT/DROPPED (push-back on DROPPED); the wrong fact comes back contradicted → push-back; the NOTE lands verbatim at the symbol; the ledger drop triggers `drift_check` offering stale symbols |
| C12 | `/regen-comments --create-voice` | name → clean-room draft → free-text edit → test run on a real target (report rendered, nothing applied) → save on accept; the new voice then appears in the menu with a preview |
| C13 | `/regen-comments <file> --without-comment-triage` | runs purely from code (no comment lens); existing header (copyright/license) still preserved mechanically |
| C14 | run preflight with a deliberately wrong `--expect-email` mid-C1 | the run **stops** at step 0 with the mismatch named; it proceeds only after you explicitly agree (never silently) |
| C15 | any C1 run with the report served (Runbook step 7's serve loop) → click **Submit to session** in the browser | the `SELECTION RECEIVED` Monitor event lands in-session; the orchestrator parses, runs the invariant-7 read, applies, and re-renders with no paste; the round menu continues; Discard/Apply stops the server |

Gate-fix confirmations (call these out during the above):
- **voice menu** lists every voice and never errors (the old 5-option `AskUserQuestion` is gone).
- **picker** with exactly 1 questionable fact → a 2-option **Keep / Drop** (not an error); with 5+ → a numbered text list to drop.
- **two parallel invocations** of the skill → **distinct** rooms (no shared dir, no stale-artifact poisoning).
- every run: `CODE IDENTICAL` reported before the report; the report auto-opens; **nothing is committed** automatically; apply writes to the working tree only on explicit confirm.

## D. Trigger-routing evals (description-level)
The loader routes on `description:` + `when_to_use` alone — the body never enters the routing decision. `trigger-evals.json` holds 20 realistic queries: 10 that should route here and 10 near-misses that belong to a sibling skill (`audit-comments`, `audit-docs`, `audit-code`, `guide-generation`, `code-review`) or to a plain edit. The near-misses are the load-bearing half — they share the words "comments" and "docstrings" with this skill and test the boundary, not the bullseye.

To run: `python3 .github/skills/_shared/run_trigger_evals.py .github/skills/regen-comments/trigger-evals.json --workers 4` — each query fires a fresh `claude -p` from the repo root (so the real skill list loads), 3 runs per query, majority vote. Pass = every `should_trigger: true` query routes to `regen-comments` and every near-miss routes elsewhere; the table also reports per-row `expected_route` agreement, and the exit code is 0 only when every row passes.

Run after any edit to this skill's `description` / `when_to_use`, and when a new sibling skill lands whose scope borders comments, docstrings, or voices. A near-miss that starts routing here means the two descriptions need sharper exclusions, not a pushier trigger list.
