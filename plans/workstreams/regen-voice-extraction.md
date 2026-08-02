# Workstream: regen-comments / voice tooling — extraction from the monorepo

Status: **EXTRACTED 2026-07-04.** Destination: sibling repo
`/Users/chuxor/circuitpython/regen-voice-tools` (branch `main`, carved at monorepo commit
`391c349d`). The regen-comments skill + parked items below now live there; this file stays
in the monorepo as the record of the move. See "Extraction executed" at the bottom.

Original holding-pen note (user call 2026-07-04: "the regen comments work and voice … is
kind of its own work stream and not really related to chumicro anymore, thats going to get
pulled out"). The queued items below left `plans/next-up.md` on that call and moved out
with the tooling.

## Items parked (formerly next-up entries, verbatim state as of 2026-07-04)

- **Comment-generation round 18 (guided vs bare no-guidance control) — built, awaiting
  dispatch + analysis.**  [`../handoffs/2026-05-30-comment-generation-round18-guided-vs-bare.md`](../handoffs/2026-05-30-comment-generation-round18-guided-vs-bare.md)
  Deferred earlier as user-present clean-room spend.
- **Deferred clean-room and audit benches, gated on bench-token spend.**
  [`deferred-clean-room-benches.md`](deferred-clean-room-benches.md) — regen-comments
  round-35 prompt-package variance, audit-code/branch register-sample injection at n≥5,
  `/audit-skill` across the over-budget skills.  The audit-code/audit-skill runs ride
  along here because they share the clean-room bench machinery, even though those skills
  themselves stay in-repo.
- **regen-comments interactive layer: cold-session gate walk (C1–C14)** per
  `TESTPLAN.md` layer C, plus one 2-voice comparison run before trusting library-scale
  work; layers A+B+D and C15 were validated live 2026-06-10.
- **regen-comments voice-pick menu rework** (user feedback 2026-06-12: layout grates).
  Rider that touches an in-repo skill: audit-skill's voice-question label
  (`SKILL.md:89`, "Numbered voice — type the menu number under Other") trips the
  ask-wording craft check — reword whenever the menu-UX pass happens, wherever that
  work then lives.
- **regen-comments: voiced speaker for the report's prose bits.**
  [`regen-report-voiced-speaker.md`](regen-report-voiced-speaker.md) — G (domain-fluent
  learn-then-speak) leads pending the user's voice verdict.
- **Reconcile + retire the `voice-writers-validation` branch.**  Commits `b61f6df2`
  (shared dark-override theming) + `52934e58` (voice-compare onto the shared picker)
  exist only on `origin/voice-writers-validation`, not on main; the syn3 checkpoint
  handoff lives ON that branch, never merged.  Conflicts with main on
  `regen-comments/SKILL.md` + `render_compare.py`; the branch's voices revert is
  obsolete (who-form retained, 2026-06-20 user call).  Resolve during extraction —
  either merge the webui commits before the tooling leaves, or take them with it.

## What stays in the monorepo (explicitly NOT parked)

Comment-content work on the libraries themselves (the websockets + wifi fact
spot-check, the strict-no-body docstring rule and its body-slim sweep) and the audit
tooling that isn't voice/comment-generation (`audit-code`/`audit-branch` pipeline
continuity, the `/audit-library` retrofit, the usage-path lens) — those remain in
`plans/next-up.md`.

## Extraction executed (2026-07-04)

Destination: `/Users/chuxor/circuitpython/regen-voice-tools` (git `main`, carved at monorepo
commit `391c349d`).

**Moved** (copied to the new repo, deleted from the monorepo working tree):
- `.github/skills/regen-comments/` **and** its `.claude/skills/regen-comments/` mirror (the
  two mirrors were byte-identical) → new repo `skills/regen-comments/` (single copy).
- `plans/workstreams/regen-report-voiced-speaker.md`,
  `plans/workstreams/regen-comments-variance-bench.md`.
- The regen/voice handoffs: `2026-05-30-comment-generation-round18…/round19…/round20…/round21…`,
  `2026-05-31-voice-register-theme-test.md`,
  `2026-06-07-regen-comments-writer-quality-next-phase.md`,
  `2026-06-10-regen-bench35-in-flight.md`.
- The syn3 checkpoint handoff (`2026-06-14-voice-writer-syn3-checkpoint.md`), recovered from
  the `voice-writers-validation` branch (it existed only there).

**Copied and left in the monorepo** (a staying skill also consumes each — split evidence in
the extraction report):
- Voice registry `.github/skills/_shared/voices/` — consumed by `audit-code` (`voices.py`)
  and `audit-branch` (`branch_phase1.py`).
- `.github/skills/_shared/speak_wf.js` — consumed by `audit-skill`.
- `.github/skills/_shared/run_trigger_evals.py` — consumed by `audit-branch`, `audit-skill`,
  `new-skill`.
- Top-level `.claude/surfaces/` kit → vendored into the new repo as an intentional fork frozen at
  `391c349d` (the monorepo kit keeps serving in-repo skills; the two may diverge).
- `plans/workstreams/deferred-clean-room-benches.md` (mixed regen + audit benches): copied;
  the monorepo original carries a top note that the regen round-35 item now lives in the
  extraction repo.

**Branch `voice-writers-validation`:** NOT merged, NOT deleted. Its two unique commits
(`b61f6df2` shared theming, `52934e58` render_compare collapse) are exported as patch files
in the new repo's `reference/branch-patches/`. Both are already independently re-landed on
main (theming → `.claude/surfaces/theme.py`; the collapse → `render_compare.py` is the 176-line
spec-builder), so neither was applied — the branch is ready for the user to **retire after
review**. The branch's voices revert (`0385432a`) is obsolete (who-form retained, 2026-06-20).

**Remaining TODO:** the user attaches a GitHub remote to `regen-voice-tools` (none set yet).
The orchestrator should also decide the fate of the monorepo's regen-only strip helper —
`scripts/run.py` `strip-comments` subcommand + its backing `scripts/strip_comments.py`
(help text: "used by /regen-comments") — now that the skill has left.
