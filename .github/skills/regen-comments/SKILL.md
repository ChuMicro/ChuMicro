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
`cutler` (default), `elon`, `cantrill`, `hemingway`. The full registry (`linus`, `torvalds`, `pewdiepie`, and any added via `--create-voice`) is reachable with `--voice <key>` but is not in the menu. The menu is the FIRST human gate; it precedes everything else.

## Invariants (do not violate)
1. **Clean room for every code-reading/judging layer.** Lenses, ledger-writer, writers, consolidation judge, verifier all run as `claude -p` launched **from a `/tmp` room**, never the in-session Workflow tool. Flags: `--allowedTools Read Write [Workflow Task] --permission-mode acceptEdits --model opus`. Never pass `--add-dir` pointing at the project (it would re-add a `CLAUDE.md` dir). Never use `bypassPermissions`.
2. **You are the only interactive layer.** Orchestrator does: mechanical strip, launching the `claude -p` phases, the human picker, mechanical reattach, presentation. Headless `claude -p` cannot ask the user anything — so the human gate lives only here, *between* phases.
3. **Writers never see the original comments.** The commented file is only ever in the comment-lens room; it is physically absent from writer rooms. Enforced by file placement, not instruction.
4. **Code stays byte-identical.** Only docstrings/comments are added; verify with an AST-equality check (strip docstrings, compare) and by running the file.
5. **Warn about user-global memory.** `~/.claude/CLAUDE.md` loads under `claude -p` regardless of cwd. Tell the user it may influence the comments; it's out of scope to neutralize.
6. **Never auto-commit.** Present finished candidates; the human makes the final voice pick and applies it.

## Procedure

### Runbook (the orchestrator follows these literally; the conceptual steps below explain each phase)
Let `SKILL=.github/skills/regen-comments`, `RUN=/tmp/regen-cr/<slug>-<n>` (a fresh dir).
1. **Voice gate (in-session):** if `--voice <key>` given, use it; else present the 4-voice menu (default `cutler`) via `AskUserQuestion`. (`--create-voice` → registry-add flow, then stop.)
1b. **Library mode (in-session, only when `target` is a directory):** `python3 $SKILL/regen_phase0.py <target_dir> $LIBROOM` (`LIBROOM=/tmp/regen-cr/<slug>-lib`). It strips the library source, runs the broad library triage as one clean-room `claude -p`, and writes `$LIBROOM/LIBRARY_FACTS.md` (domain + cross-file contracts + glossary). Then run steps 2–6 **for each `.py` file** in the library, passing `--lib $LIBROOM/LIBRARY_FACTS.md` to phase 1 each time. A single-file target skips this step.
2. **Phase 1 (clean-room grounding):** `python3 $SKILL/regen_phase1.py <target.py> $RUN [--without-comment-triage] [--lib <LIBRARY_FACTS.md>]` (the orchestrator supplies `--lib` automatically in library mode). It strips, captures the header for preservation, then runs the triage workflow (3 lenses + comment lens + ledger-writer + **validator/converge loop**) as one clean-room `claude -p`, prints the **questionable facts** + whether the validator still flags issues, and writes `$RUN/{ledger_provisional.md, ledger.json, preserve.json, validation.json, phase1.json}`.
3. **Validator gate (in-session):** the ledger-writer already re-ran against the validator up to 4× inside phase 1. Only if `phase1.json` shows `needs_user: true` (still flagged after the loop) do you ESCALATE — present the flagged facts (`validation.json`) plus a recommendation in an `AskUserQuestion` with a free-text window, then apply the user's steer before phase 2.
4. **Picker (in-session, the one human gate):** present the questionable facts via multi-select `AskUserQuestion`; then write `$RUN/ledger_final.md` = `ledger_provisional.md` with the **rejected** facts' lines removed (high-confidence facts are auto-kept).
5. **Phase 2 (clean-room write):** `python3 $SKILL/regen_phase2.py $RUN <voice>`. Runs the writer workflow (4 passes + per-symbol consolidation), reattaches the preserve lane, writes `$RUN/FINAL_<voice>.py`.
6. **Present (in-session):** show `FINAL_<voice>.py`; the human reviews + applies. **Never auto-commit/apply.**

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

### Step 5 — Verify
Cold-reader pass per merged candidate: fabrication check, tic-density at human level (not zero), cruft-leak (no copyright/author/tracker-ref or wrong stale claim), no-lift. Flag anything for the human.
- **Success:** each candidate is correct, clean, and reads in its voice.

### Step 6 — Reattach (mechanical, in-session)
Run `reattach.py` to ride the **preserve lane** back onto each finished file: headers (copyright/author/license) to the top, live directives/TODOs (`# noqa`, `TODO(TICKET)`) back to their original line. A writer never rewords these.
- **Success:** preserved lines present verbatim; nothing else changed; code still byte-identical.

### Step 7 — Present (human gate)
Show the finished candidate(s). The human picks the voice and applies it. Do not commit.

## Done when
A finished commented file exists per requested voice, with: executable code byte-identical to the original, every ledger fact correct against the code and the correctness-critical ones stated explicitly, must-carry domain facts present, preserve lane reattached verbatim, no cruft leak, voice intact — presented for the human's final pick, nothing committed automatically.

## Reference files
- `strip.py` — mechanical comment/docstring stripper (line surgery, not `ast.unparse`).
- `reattach.py` — mechanical preserve-and-reattach.
- `voices.json` — voice registry (data; add voices here).
- `triage_wf.js` — triage workflow (3 code lenses + comment lens + ledger-writer + **validator/converge loop**; telegraphic-stub + no-invented-examples + comment-facts-are-non-code-derivable rules). The fixture-agnostic validator (per-fact correctness + explicitness of correctness-critical fact classes; NO trap list / NO file-specific knowledge) is folded in as a stage and drives the ledger-writer re-run loop.
- `writers_wf.js` — writer fan-out + per-symbol consolidation/verify.
- `regen_phase0.py` / `library_triage.md` — library-aware mode: `regen_phase0.py` strips a library subtree and runs the broad library-triage prompt as one clean-room `claude -p`, emitting `LIBRARY_FACTS.md` (domain + cross-file contracts + glossary) that rides into each per-file room — the lenses, writers, and consolidation judge all consult it (deferring to it for cross-file facts, emitting them only where a file's code touches them).

## Patterns to avoid
- Running any code-reading agent via the in-session Workflow tool (poison risk + no file isolation) — always `claude -p` from `/tmp`.
- Putting the human picker inside a `claude -p` (it can't ask) — the gate is in-session, between phases.
- Per-file consolidation (picking one whole pass) — consolidate **per symbol**.
- Writing correctness-critical ledger facts as fluent sentences (writers echo them verbatim, collapsing voice) — telegraphic fragments only.
- `git checkout CLAUDE.md` to "restore" it — may re-enable an `@AGENTS.md` include the user disabled.
