---
name: regen-comments
description: Regenerate Python docstrings and inline comments from the code's actual behavior, in a chosen voice, in a clean room that project memory and stale comments cannot poison. Use when asked to (re)write, refresh, or clean up the comments/docstrings of a Python file, especially when existing comments are suspect or you want a specific voice. Not for prose docs or non-Python files.
when_to_use: The user asks to write / rewrite / regenerate / clean up / refresh docstrings or comments on a Python file or files; or wants comments redone in a particular voice; or distrusts the current comments and wants them rebuilt from the code.
---

# regen-comments

Rebuild docstrings and inline comments for Python file(s) **from the code's behavior**, in a chosen voice. Every model layer that reads or judges the code runs in a **clean room** (`claude -p` from `/tmp`) so a project `CLAUDE.md`/`AGENTS.md` or the file's own stale comments cannot leak into the output. You (the in-session orchestrator) do only mechanical work and the human gates; you never judge code yourself.

## Inputs and modes
- **target**: one Python **file**, OR a **directory/library**. A file runs the single-file procedure. A directory triggers **library-aware mode** (Runbook step 1b): a one-time library triage builds `LIBRARY_FACTS.md`, then the procedure loops per file with that cross-file ledger rode into every room. The input type is detected (file vs dir) — there is no separate flag.
- **`--voice <key>`** (optional): run with any voice in `voices.json`. If omitted, present a **4-voice pick menu** via `AskUserQuestion` (default **cutler**); the other registry voices are reachable only via `--voice`. **A run is always exactly ONE voice.**
- **`--without-comment-triage`** (default: comment-triage **ON**): by default the file's *existing* comments are mined for genuinely non-derivable facts — reliable enough now to be the default. Pass this flag to skip that lens and work purely from code. Writers stay clean-room either way; comment knowledge enters only through the (filtered) ledger. Copyright/license/author **header preservation is mechanical and always-on**, independent of this flag.
- **`--create-voice`** (mode, no comment generation): add a voice to `voices.json`. Prompt for a key + a one-line persona paragraph, validate it against the persona discipline (named person or disposition, a SINGLE clause, NO rule-work baked inside it — see `[[personas-clean-one-clause]]`), append, and exit. Does not touch any target file. Voices are data; never author a per-voice agent file.
- **Model:** every clean-room layer runs on **opus** (correctness-first; the lenses do the hard cross-method discovery and the judges gate correctness).
- **Passes:** **4** writer passes per voice before per-symbol consolidation.

### The 4-voice pick menu (when no `--voice`)
`cutler` (default), `elon`, `cantrill`, `hemingway`. The full registry (`linus`, `torvalds`, `pewdiepie`, and any added via `--create-voice`) is reachable with `--voice <key>` but is not in the menu. The menu is the FIRST human gate; it precedes everything else. Each option carries a `preview` — that voice's cached sample from `voices.json` `previews` (all voices rendered against one fixed no-code subject) — so the user compares voices before picking.

## Invariants (do not violate)
1. **Clean room for every code-reading/judging layer.** Lenses, ledger-writer, writers, consolidation judge, verifier all run as `claude -p` launched **from a `/tmp` room**, never the in-session Workflow tool. Flags: `--allowedTools Read Write [Workflow Task] --permission-mode acceptEdits --model opus`. Never pass `--add-dir` pointing at the project (it would re-add a `CLAUDE.md` dir). Never use `bypassPermissions`.
2. **You are the only interactive layer.** Orchestrator does: mechanical strip, launching the `claude -p` phases, the human picker, mechanical reattach, presentation. Headless `claude -p` cannot ask the user anything — so the human gate lives only here, *between* phases.
3. **Writers never see the original comments.** The commented file is only ever in the comment-lens room; it is physically absent from writer rooms. Enforced by file placement, not instruction.
4. **Code stays byte-identical.** Only docstrings/comments are added; verify with an AST-equality check (strip docstrings, compare) and by running the file.
5. **Warn about user-global memory.** `~/.claude/CLAUDE.md` loads under `claude -p` regardless of cwd. Tell the user it may influence the comments; it's out of scope to neutralize.
6. **Never auto-commit.** After the human approves the report, you may write the finished file onto the working tree (uncommitted, reversible) on an explicit confirm; never `git add`/`git commit`. The human reviews the diff and commits.

## Procedure

### Runbook (the orchestrator follows these literally; the conceptual steps below explain each phase)
Let `SKILL=.github/skills/regen-comments`, `RUN=/tmp/regen-cr/<slug>-<n>` (a fresh dir).
0. **Preflight (in-session):** `python3 $SKILL/preflight.py --expect-email <the account THIS session runs as>` (pass the session's account email from your context, so it can compare). It confirms `claude` is on PATH, runnable, and **logged in**, and reports the CLI's account from `claude auth status`. Every phase shells out to `claude -p`, which uses the CLI's OWN login — if that differs from your session's account (different org / model access / subscription / billing), the clean-room work silently runs under the wrong account. **STOP and tell the user** on a preflight failure (missing / not logged in) OR an ACCOUNT MISMATCH / unknown-account warning, and get their go-ahead before proceeding. If you don't know the session's account email, run it without `--expect-email` and surface the CLI account for the user to confirm.
1. **Voice gate (in-session):** if `--voice <key>` given, use it; else present the 4-voice menu (default `cutler`) via `AskUserQuestion`, each option's `preview` = that voice's cached sample from `voices.json` `previews` (run `gen_voice_previews.py` once to populate). (`--create-voice` → registry-add flow, then stop.)
1b. **Library mode (in-session, only when `target` is a directory):** `python3 $SKILL/regen_phase0.py <target_dir> $LIBROOM` (`LIBROOM=/tmp/regen-cr/<slug>-lib`). It strips the library source, runs the broad library triage as one clean-room `claude -p`, and writes `$LIBROOM/LIBRARY_FACTS.md` (domain + cross-file contracts + glossary). Then run steps 2–8 **for each `.py` file** in the library, passing `--lib $LIBROOM/LIBRARY_FACTS.md` to phase 1 each time. A single-file target skips this step. **To go faster**, batch the gate-free phases with `regen_batch.py` (concurrency 2-3 — each pipeline is its own `claude -p` fan-out, so higher oversubscribes): `python3 $SKILL/regen_batch.py phase1 3 --lib $LIBROOM/LIBRARY_FACTS.md <files...>` (writes a room manifest), then do the pickers per room, then `python3 $SKILL/regen_batch.py phase2 3 <voice> <rooms...>`.
2. **Phase 1 (clean-room grounding):** `python3 $SKILL/regen_phase1.py <target.py> $RUN [--without-comment-triage] [--lib <LIBRARY_FACTS.md>]` (the orchestrator supplies `--lib` automatically in library mode). It strips, captures the header for preservation, then runs the triage workflow (3 lenses + comment lens + ledger-writer + **validator/converge loop**) as one clean-room `claude -p`, prints the **questionable facts** + whether the validator still flags issues, and writes `$RUN/{ledger_provisional.md, ledger.json, preserve.json, validation.json, phase1.json}`.
3. **Validator gate (in-session):** the ledger-writer already re-ran against the validator up to 4× inside phase 1. Only if `phase1.json` shows `needs_user: true` (still flagged after the loop) do you ESCALATE — present the flagged facts (`validation.json`) plus a recommendation in an `AskUserQuestion` with a free-text window, then apply the user's steer before phase 2.
4. **Picker (in-session, the one human gate):** present the questionable facts via multi-select `AskUserQuestion`; then write `$RUN/ledger_final.md` = `ledger_provisional.md` with the **rejected** facts' lines removed (high-confidence facts are auto-kept).
5. **Phase 2 (clean-room write):** `python3 $SKILL/regen_phase2.py $RUN <voice>`. Runs the writer workflow (4 passes + per-symbol consolidation + an independent summarizer), reattaches the preserve lane, writes `$RUN/{FINAL_<voice>.py, merged.py, picks.json, summary.json}`.
6. **Report (in-session):** `python3 $SKILL/render_report.py $RUN <voice> <target.py>` → `$RUN/report.html`. Surface it with `SendUserFile` and print its `file://` line.
7. **Refine (optional human loop, in-session):** offer to refine any symbol from the report. Per the human's pick, run the right tool (all below), then `render_report.py` again to refresh and re-surface. Loop until they are satisfied. See Step 8 for the full loop.
   - **roll the dice** (different take, cheap): `splice_symbol.py $RUN/FINAL_<voice>.py $RUN/runs/run-<N>.py <symbol> $RUN/FINAL_<voice>.py`, cycling N=1..4; after the four cached candidates are exhausted, `regen_symbol.py` for a fresh one.
   - **drop / edit a fact**: edit that fact's line in `$RUN/ledger_final.md`, then `python3 $SKILL/regen_symbol.py $RUN <voice> <symbol>`.
   - **add a fact**: ask *correction or your-own-note?* Correction → `python3 $SKILL/stubify_fact.py $RUN "<fact>"`, act on the verdict (confirmed → append the stub to `ledger_final.md` + `regen_symbol.py`; contradicted → raise suspicion, do not block; unverifiable+needs_source → ask for a URL/desc; else trust). Your-own-note → ask initials, add `# NOTE(<initials>): <verbatim>` at the symbol (offer to voice it or keep verbatim).
   - **write it myself**: replace that symbol's docstring with the human's exact text (in-session `Edit`; then `tics.py` + AST check).
   - After any ledger edit: `python3 $SKILL/drift_check.py $RUN <voice> <symbol> "<what changed>"`; if it flags sure-stale symbols, offer to regen those too (never block).
8. **Apply (in-session):** when the human approves, confirm via `AskUserQuestion`, then write the finished file onto the working tree (`cp $RUN/FINAL_<voice>.py <target.py>` — uncommitted, reversible) so they review the diff in their editor. **Never `git add`/`git commit`.**

The conceptual phases (what each does + the invariants):

### Step 0 — Voice, strip, rooms (in-session)
**Voice (first human gate):** if `--voice <key>` was given, use it; otherwise present the 4-voice menu (default `cutler`) via `AskUserQuestion` and use the pick. A run is exactly one voice. (If invoked as `--create-voice`, do the registry-add flow instead and stop — no generation.)
**Strip:** run `strip.py target.py` → stripped code (comments + docstrings removed, executable code byte-identical), and capture the file's leading header (copyright/license/author) for later reattach. Set up `/tmp/regen-cr/<run>/` rooms. Copy stripped code into the code-lens / writer / judge rooms; by default copy the original (commented) file into the comment-lens room only (skipped with `--without-comment-triage`).
- **Success:** a single voice is fixed; stripped code parses and runs identically to the original.

### Step 0b — Library triage (library-aware mode, when the target is a directory)
When the target is a directory, run `regen_phase0.py` ONCE before the per-file loop: it strips the library source (clean-room — library facts come from code behavior, not comments), lays it under `lib/`, and runs the broad library triage (`library_triage.md`) as one `claude -p` → `LIBRARY_FACTS.md` (domain + cross-file contracts + glossary; same telegraphic ledger shape, at library scope). Every per-file room then gets this file: the per-file lenses **defer** to it (never re-surface a fact it already states, recording only file-specific facts or this file's application of a contract), and the writers + consolidation judge treat it as a **correctness/vocabulary reference**, emitting a library fact only where a symbol in that file touches it.
- **Success:** `LIBRARY_FACTS.md` carries the cross-file contracts + glossary as telegraphic facts; a single-file run skips this step entirely.

### Step 1 — Triage + validate (one `claude -p` from `/tmp`)
Launch one `claude -p` that runs the **triage workflow** (`triage_wf.js`): 3 code lenses on the stripped code (trap / cross-method trace / naming-vs-behavior), plus the comment lens on the commented file (runs by default; skipped with `--without-comment-triage`), then the ledger-writer merges → provisional ledger (telegraphic stubs, each with a confidence). A fixture-agnostic **validator** then checks every fact against the code and the ledger-writer re-runs against its notes until clean or 4 attempts (Step 2). The comment lens produces the **preserve lane** (live-TODOs, plus any copyright/author it flags); the copyright/license/author **header** is captured mechanically by phase 1 regardless of the flag, so it survives even `--without-comment-triage`.
- **Success:** ledger carries the non-derivable + cross-method facts as telegraphic fragments (never copyable sentences); comment-derived facts tagged and carried clean (not "grounded" against code); validator converged or `needs_user` set.

### Step 2 — Validate the ledger (inside the Step 1 workflow)
The **validator** runs against the stripped code as a stage of the triage workflow. It is **fixture-agnostic** — no trap list, no knowledge of this file's facts. For EACH ledger fact: is it true against the code? And for every fact in a correctness-critical *class* — a returned flag's referent, an inversion, a dual-role value, a boundary condition — is it stated **explicitly and unambiguously** (a reader could not invert it)? If any is wrong or under-specified, the **ledger-writer re-runs against the validator's notes (writer-only; lenses are fixed) up to 4 times**, re-validating each time. If it still won't converge, phase 1 sets `needs_user` and the orchestrator escalates to the human (Runbook step 3).
- **Success:** every ledger fact correct against the code; correctness-critical facts unambiguous; no copyable-prose stubs; converged or escalated.

### Step 3 — Picker (human gate, in-session)
Surface the **questionable** facts (confidence low/med, or comment-derived) and any borderline **preserve** items to the user via `AskUserQuestion` (multi-select keep/drop). High-confidence facts are auto-kept and never shown. Assemble the **final ledger** = high-confidence facts + the questionable facts the user kept (mechanically drop the rejected `- ` lines from the provisional ledger). The ledger-writer ran first on purpose, so the human judges polished stubs, not raw lens fragments.
- **Success:** final ledger written; only approved facts remain.

### Step 4 — Write + consolidate (one `claude -p` from `/tmp`)
Launch one `claude -p` that runs the **writer workflow** (`writers_wf.js`): the chosen voice, **4 passes** (clean-room: stripped code + final ledger only), then **per-symbol consolidation** — a judge that takes the best docstring + that symbol's inline comments **per module / class / method / function** across the 4 passes and assembles ONE merged file, gating on correctness against the code + **must-carry** facts + no cruft leak + no verbatim ledger lift.
- **Must-carry** = any NON-DERIVABLE fact in the final ledger (a domain constraint, author intent — typically the comment-derived facts the human kept). For each symbol the judge confirms every must-carry fact that pertains to it is present in the chosen candidate. (Definition is generic — derived from the ledger, NOT a fixed trap list.)
- **Success:** one merged candidate; code AST-identical; must-carry facts present; no cruft leak; no lifted ledger phrasing.

### Step 5 — Verify (mechanical detect + clean-room polish)
Phase 2 runs `polish.py` on the merged file: `tics.py` deterministically detects the absolute mechanical-ban violations (banned sentence-openers `The`/`That`/`This`/…, em-dashes, semicolons, the words `canonical`/`shape`) in docstrings/comments, and a clean-room `claude -p` minimally rewrites only the offending sentences (meaning + voice intact), looping until the detector is clean (max 3) and reverting any pass that altered executable code. Generators drift on "no exceptions" style rules, so this backstop is what makes the bans actually hold.
- **Success:** zero mechanical-ban violations in the finished file; code AST-identical; voice intact.

### Step 6 — Reattach (mechanical, in-session)
Run `reattach.py` to ride the **preserve lane** back onto each finished file: headers (copyright/author/license) to the top, live directives/TODOs (`# noqa`, `TODO(TICKET)`) back to their original line. A writer never rewords these.
- **Success:** preserved lines present verbatim; nothing else changed; code still byte-identical.

### Step 7 — Report (in-session)
Run `render_report.py` to build `report.html`: an **independent** plain-English summary of the file (written from the code, not the comments — so the human can check the comments against a description they did not write), the validated ledger, per-symbol before/after docstrings, and the consolidation rationale. Surface it with `SendUserFile` and a `file://` line.
- **Success:** `report.html` rendered and surfaced.

### Step 8 — Refine (optional human loop, in-session)
From the report the human can refine any symbol; loop until satisfied, re-rendering after each change. Per pick:
- **roll the dice** — a different take. Cheap: `splice_symbol.py` cycles the cached candidates `runs/run-1..4.py` for that symbol (its docstring + comments swap, code guaranteed unchanged). Once the four are exhausted, `regen_symbol.py` generates fresh.
- **drop / edit a fact** — edit `ledger_final.md`, then `regen_symbol.py <symbol>` (re-runs the writer against the edited ledger and splices only that symbol back; every other symbol stays as the human had it).
- **add a fact** — ask *correction or your-own-note?*. A **correction** goes through `stubify_fact.py` (validates against the code: confirmed → append stub + regen; contradicted → raise suspicion, never block; unverifiable+checkable → ask for a source; otherwise trust). A **your-own-note** is kept verbatim as `# NOTE(<initials>): …` at the symbol (ask initials; offer to voice it or keep verbatim) — the comment lens re-harvests it on a later run.
- **write it myself** — replace that symbol's docstring with the human's exact words.
- After any **ledger** edit, `drift_check.py` looks for OTHER symbols the change made sure-stale and offers to regen those too (never blocks the single-symbol intent).
Every regeneration re-runs `polish.py`, and `splice_symbol.py` guards code byte-identity, so no edit can drift the code.
- **Success:** the human is satisfied with every symbol; code still AST-identical; zero mechanical-ban violations.

### Step 9 — Apply (human gate)
When the human approves, confirm, then write the finished file onto the working tree (uncommitted) so they review the diff in their editor. Do not commit.
- **Success:** on the human's confirm the finished file landed in the working tree (uncommitted), or they declined and nothing changed.

## Done when
A finished commented file exists for the chosen voice, with: executable code byte-identical to the original, every ledger fact correct against the code and the correctness-critical ones stated explicitly, must-carry domain facts present, preserve lane reattached verbatim, zero mechanical-ban violations, voice intact — surfaced via `report.html` (independent summary + ledger + before/after + rationale), optionally refined per symbol through the Step 8 loop, and either written to the working tree on the human's confirm or left for them, with nothing committed automatically.

## Reference files
- `preflight.py` — Step 0 check: `claude` CLI on PATH + runnable + **logged in**, and which **Claude account** it resolves to (`claude auth status`) — `claude -p` uses the CLI's own login, which can differ from the session's account; `--expect-email` flags a mismatch. Imported by every driver as a guard (installed + logged-in).
- `regen_batch.py` — library-mode speedup: bounded-parallel runner for the gate-free phases (phase 1 grounding across files, then phase 2 writing across rooms); keep concurrency low (2-3).
- `strip.py` — mechanical comment/docstring stripper (line surgery, not `ast.unparse`).
- `reattach.py` — mechanical preserve-and-reattach.
- `voices.json` — voice registry (data; add voices here).
- `triage_wf.js` — triage workflow (3 code lenses + comment lens + ledger-writer + **validator/converge loop**; telegraphic-stub + no-invented-examples + comment-facts-are-non-code-derivable rules). The fixture-agnostic validator (per-fact correctness + explicitness of correctness-critical fact classes; NO trap list / NO file-specific knowledge) is folded in as a stage and drives the ledger-writer re-run loop.
- `writers_wf.js` — writer fan-out + per-symbol consolidation + an independent code summarizer (`summary.json`).
- `tics.py` / `polish.py` — Step 5 verify: `tics.py` deterministically detects mechanical-ban violations (banned openers, em-dashes, semicolons, `canonical`/`shape`) in docstrings/comments; `polish.py` runs the clean-room fix loop with a code-identity guard.
- `render_report.py` — mechanical HTML report (no LLM): independent summary + validated ledger + per-symbol before/after + consolidation rationale. Code/correctness-first.
- `gen_voice_previews.py` / `voice_preview_wf.js` — render every voice against one fixed no-code subject and cache the samples into `voices.json` `previews` for the pick menu. Re-run after adding a voice.
- `splice_symbol.py` — refinement-loop primitive: swap one symbol's docstring+comments from another version (a cached candidate or a fresh regen), guarding executable code byte-identical.
- `regen_symbol.py` — refinement loop: regenerate one symbol against the edited ledger and splice only it back (every other symbol stays as the human had it), then re-polish.
- `stubify_fact.py` — refinement loop: validate a human-supplied fact against the code and turn it into a telegraphic stub (confirmed / contradicted / unverifiable + needs_source).
- `drift_check.py` — refinement loop: after a ledger edit, flag OTHER symbols the change made sure-stale (conservative; sure-only).
- `regen_phase0.py` / `library_triage.md` — library-aware mode: `regen_phase0.py` strips a library subtree and runs the broad library-triage prompt as one clean-room `claude -p`, emitting `LIBRARY_FACTS.md` (domain + cross-file contracts + glossary) that rides into each per-file room — the lenses, writers, and consolidation judge all consult it (deferring to it for cross-file facts, emitting them only where a file's code touches them).

## Patterns to avoid
- Running any code-reading agent via the in-session Workflow tool (poison risk + no file isolation) — always `claude -p` from `/tmp`.
- Putting the human picker inside a `claude -p` (it can't ask) — the gate is in-session, between phases.
- Per-file consolidation (picking one whole pass) — consolidate **per symbol**.
- Writing correctness-critical ledger facts as fluent sentences (writers echo them verbatim, collapsing voice) — telegraphic fragments only.
- `git checkout CLAUDE.md` to "restore" it — may re-enable an `@AGENTS.md` include the user disabled.
