# TESTPLAN.md skeleton — empirical validation for a driver-backed skill

Write a TESTPLAN.md next to the SKILL.md whenever the skill bundles scripts or a driver. A skill that only guides prose can stop at the cold-walk; a skill that runs code has failure modes no cold read finds — the regen-comments TESTPLAN's first full run surfaced two pipeline crashes and a prompt gap that five readers had walked past.

## The four layers

| Layer | What it exercises | Who runs it |
|---|---|---|
| **A — mechanical** | Each bundled script against a fixture: parse/apply round trips, refusal paths, exit codes, guard behavior | Self-executing (any session) |
| **B — end-to-end** | The full pipeline on a real target, per mode/genre the skill claims to support; outputs graded against the skill's own shape rules | Self-executing (slow — clean-room or subagent runs) |
| **C — human gates** | The interactive forks: menus, pickers, sign-off loops, apply/discard | Needs-human (a cold session driven by the user) |
| **D — trigger routing** | `python3 .github/skills/_shared/run_trigger_evals.py <skill-dir>/trigger-evals.json` — majority-vote probes against the live skill registry | Self-executing |

Not every skill needs all four. A skill with no interactive forks has no layer C; layer D exists for any skill with a `trigger-evals.json`.

## Row discipline

Each row carries: the exact invocation, the expected observable, and a **self-executing / needs-human** mark. Two rules make rows worth running:

- **A row must discriminate.** Ask of every expected observable: would a clearly-wrong run still satisfy it? *"exit 0"* passes a script that silently did nothing; *"exit 1 AND the refusal names the offending symbol"* discriminates. A row that cannot fail is worse than no row — it manufactures false confidence on every future run.
- **A row must be runnable from the file alone.** Name the fixture (or how to fabricate it), not "the usual test file". A generic target (any small `.py` in the repo) beats a machine-specific path that goes stale.

## Worked row

```
| A3 | apply refuses a blob naming two files | `python3 $SKILL/apply_selection.py apply $RUN plain two-file-blob.txt` | exit 1; stderr names both files and the expected single-file form | self-executing |
```

## After the first full run

Findings go to the work queue, not the TESTPLAN — a TESTPLAN records what to check, never what was once broken (history lives in commit messages). Rows that needed fixture surgery to run get their fixture instructions corrected in the same edit.
