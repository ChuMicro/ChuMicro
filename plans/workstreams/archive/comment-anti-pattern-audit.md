# Workstream: Code-comment anti-pattern audit

Status: **complete (2026-05-09).**

## Outcome

CHU012 lint shipped with patterns covering every shape the audit
surfaced; 122 violations across 38 files cleaned.  Lint wired into
`python scripts/run.py lint` so future regressions fail at preflight.

## What landed

- `scripts/check_dated_narration.py` — CHU012 lint with 12
  patterns covering: dated incidents (Surfaced / Discovered /
  Observed / Captured / Caught / shipped / landed + ISO date),
  dated verifications (verified live | on hardware + date,
  live-tested | bench-tested + date), workstream-phase pointers
  (Phase | Step | Slice + workstream, workstream Phase N), F-numbered
  + ISO-date pairs, verification-pass / finding labels with a date,
  "Regression for YYYY-MM-DD", hyphenated workstream-named passes
  ("in the deploy-audit pass"), removed-code framing (Earlier
  versions / Previously this / We used to / Used to be), Slice + N
  (Slice is workstream-only jargon in this codebase), and
  Phase | Step + N when NOT followed by a colon (procedural
  numbered steps stay clean).

- `scripts/tests/test_check_dated_narration.py` — 78 tests
  covering each pattern's hit / miss cases plus end-to-end check
  against fixture files.

- `scripts/run.py:lint()` runs CHU012 alongside ruff + the other
  CHU lints.

- 38 files cleaned across `libraries/`, `workbench/`, and
  `scripts/`: docstrings, test class docstrings, file-level
  module docstrings, code comments, and CLI help / stub messages
  trimmed of dated narration and workstream-phase pointers.

## Suppression

`# noqa: CHU012` (Markdown: `<!-- noqa: CHU012 -->`) — pair every
suppression with a one-line *why* a reviewer can verify (e.g. a
workaround pinned to a specific firmware version where the dated
framing genuinely is the *why* of current code).

## Triggered by

- User feedback during workbench-deploy-reliability session,
  mid-2026-05-09: "many comments in this session are adding
  comments referring to changes and history. that is not what
  code comments are for."
- AGENTS.md commit `e13df11` formalised the rule but didn't sweep
  existing code.
