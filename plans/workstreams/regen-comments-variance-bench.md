# regen-comments: variance-aware bench of the round-35 prompt package

One bench, n≥5 per arm, deterministic counts only (round-21 handoff "THE VARIANCE
RECKONING": run noise is 57–70% of a rule effect, so n=1 soul comparisons are noise).
Everything below landed 2026-06-10/11 on directional n=1 evidence and is queued here for
the rigorous confirm; narrative and per-change validation live in `git log` for that day
(`1d15bbd0..71b67e47`).

## Arms to race

- **Sample injection**: same voice with vs without the `voice_samples/<key>.md` excerpt.
- **Lean prompts vs benched-D+sample**: the live writer text vs the raw A/B/C/D winner,
  so the post-fold additions either earn their seats with counts or get cut.

## Deterministic counts per arm

- body paragraphs / sections per mode (the tight 0-body, less rare-tiny-body, default
  3–4-sentence-cap contracts)
- summary-line sentence counts (1 everywhere; tight allows 2-in-1-paragraph)
- tic + ban counts (incl. the `" -- "` em-dash stand-in)
- n-gram copy-signal against the sample text
- scaffold-frame counts ("one thing to know" family)

## Open calibrations the bench should settle

- **Body frequency for less**: every symbol drew a tiny body on fact-dense ledgers at
  both prompt densities — "a few spots, never most symbols" is not binding there.
  Options: teeth, a class carve-out (the class docstring strains every mode's cap), or
  acceptance (frequency tracks fact density).
- **Watcher/selector recall on broken sentences**: a flatly garbled docstring shipped
  past BOTH `flag_legibility` and the selector's legibility floor while a clean cached
  alternative existed; only the human gate caught it. Seed known-broken sentences and
  count detection.
- **Trap-dense file**: did the phase-1 parsimony rule over-prune where many facts are
  real? (Held over from the first round-35 bench.)
- **`flag_tics.py` sample-phrase leaks**: the scanner covers persona phrases but not
  distinctive excerpt phrases landing in docstrings — extend the scan to the sample text.

## Also riding (small, same harness)

- `create_voice.py` still carries the superseded named-person house-style prompt;
  optionally ground `gen` in a samples file for future voices.
