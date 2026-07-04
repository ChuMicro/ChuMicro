# Workstream: regen-comments / voice tooling — extraction from the monorepo

Status: **parked for extraction** (user call 2026-07-04: "the regen comments work and
voice … is kind of its own work stream and not really related to chumicro anymore,
thats going to get pulled out").  This file is the holding pen: the queued items below
left `plans/next-up.md` on that call and move out with the tooling when the extraction
happens.  Until then the underlying workstream / handoff files stay in place untouched,
so nothing here needs re-discovery.

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

## Extraction TODO (when the pull-out happens)

- Decide the destination repo and move the skills (`regen-comments`, voice writers,
  their webui) + the workstream/handoff files listed above.
- Resolve the `voice-writers-validation` branch as part of the move.
- Sweep `plans/` for remaining pointers into the moved files.
