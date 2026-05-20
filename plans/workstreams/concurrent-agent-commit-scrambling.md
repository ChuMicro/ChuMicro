# Workstream: Concurrent-agent commit scrambling

Status: **proposed.**  Incident logged 2026-05-19 during the pytest-device audit.  Process / skill note, not a code-recovery task.

## Incident

Five concurrent `/audit-library` sessions (repl, workspace, deploy, pytest-device, plus a HotPath / cache refactor) committed against one local `main` branch and one shared git index over a ~30-minute window.

At least two commits landed with message-vs-content mismatch:

- `84e3c1a3 deploy: drop "canonical X" tic` actually carries the pytest-device MEDIUM-perf changes (`VERSION` + memoize cache + new tests).
- `b4fbd5ba workspace audit: drop "Legacy additive deploy"` carries the deploy `"canonical X"` docstring drops plus workspace CLI edits.

Every intended file change landed somewhere, but commit-message-vs-diff is unreliable for these two commits — `git log -p` is authoritative.

No code recovery needed.

## Infra opportunities

1. **Require explicit pathspecs in the `git-commit` skill body when other Claude processes are detectable on the same checkout.**  `git add -p` or a list of files by name closes the door on accidentally folding another agent's staged delta into your commit.
2. **Post-commit verification step that re-reads the staged file set vs. the message claim.**  Cousin to the `--cached` stat check already done pre-commit — would catch the mismatch class at write time instead of read time.
