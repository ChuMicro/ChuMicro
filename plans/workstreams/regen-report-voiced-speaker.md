# regen-comments: voiced speaker for the report's prose bits

Status: in design — winning prompt shape identified, user verdict on variant G pending.

The decision page's prose (independent summary, symbol purposes, selection rationale, ledger
glosses) renders voiceless even on a voiced run: the summarizer, selector, and gloss prompts are
deliberately plain or format-constrained, and the constrained gloss prompt is why the validated
ledger reads as broken voice. The fix is a post-pass **speaker** (the `_shared/speak_wf.js`
pattern): ONE clean-room `claude -p` call per run reads the finished room's plain bits and says
them all in voice, leaving the converged writer / summarizer / selector prompts untouched.

## Prompt findings (A–G, 2026-06-12, bourdain on the events-core room)

Seven variants raced on identical bits; the user judged voice, deterministic checks judged bans.

- **A** persona + sample + trimmed speak_wf rules: loses voice inside comma-riddled fact runs.
- **B** persona + sample, no rules: voice holds but leans on tics (10+ em-dashes) to push through
  dense facts.
- **C** persona only: thin, "non-rich" voice — the register sample is a necessity.
- **D** B + sentence budget (1–2 facts/sentence): density solved but staccato — the structure rule
  became the voice.
- **E** learn-then-speak (understand first, write from understanding, never borrow wording or
  sentence order): the breakthrough — restructures dense facts instead of transcribing them.
  Residue: rhythm inversion (all punch, no roll) and a vivid image on nearly every line.
- **F** E + explicit rhythm rule: overcorrected into all-roll run-ons, register drifted soft.
- **G** E + one domain-fluency line ("you have spent enough years around code to talk about it the
  way you talk about kitchens: fluent in the mechanics, never performing them"): best so far —
  varied rhythm, mechanisms said plainly, color spent sparingly.

The portable lesson: **structural rules get performed; identity gets inhabited.** Rules about
sentence shape (D, F) are obeyed so literally they become the voice; identity framing (E's
understand-first, G's fluency) changes the output without leaving fingerprints. The metaphor
saturation in B/E reads as the model bridging the domain gap — granting fluency (G) removes the
need for the bridge. Generalizes to any voice: persona + fluency line + register sample +
learn-then-speak + the one mechanical ban line.

## Plan

1. User verdict on G (or one more nudge round). Test scripts: `.scratch/voice-abc/run_{abc,de,fg}.py`
   (gitignored; prompts inline there, winning G prompt reproduced by run_fg.py).
2. Production speaker: one `claude -p` per run room (after phase 2) reading
   summary.json + pick.json + ledger.json glosses, writing `voiced.json` with the same keys.
3. Renderers prefer `voiced.json` when present (render_report.build_file_entry); plain remains the
   no-voice path. Library scope: one speaker call per room, batched like phase 2.
4. Fact-drift eye for the voiced bits folds into the existing `flag_legibility` call — no new
   agent (agent-consolidation call, next-up bullet 2026-06-12).
5. Open lever if roll still falls short: the em-dash ban fights bourdain's long-line habit; report
   prose is not shipped comment text, so a report-only relaxation is on the table.

## Validation history

- 2026-06-12: A–G raced on /tmp rooms (evaporated; outputs quoted in the session transcript).
  D/E/F/G all ban-clean; facts survived in all seven.
