# Owner verdicts

One file per verdict the page owner gives on a cold-writer candidate. These
records are the calibration set: a reviewer prompt is judged by how often it
agrees with them, and a draft the owner accepted is what "passes" looks like.

Each file carries:

- `Page`: the destination path.
- `Run`: the run directory under `.scratch/cold-writer/` and the draft's SHA-256,
  so the draft can be matched even after scratch is cleared.
- `Verdict`: `accepted`, `rejected`, or `not chosen` (the owner picked a sibling
  without a critique of this one).
- `Owner said`: the critique verbatim, however short.
- `Draft`: the full draft text, unchanged, so the record stands without scratch.

Reviewers read these files. Writers never do: a draft here is prose, and the
writer's inputs stay telegraphic.
