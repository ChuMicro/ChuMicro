# Workstream: Concurrent-agent commit scrambling

Status: **proposed.**  Incident logged 2026-05-19 during the pytest-device audit.  Process / skill note, not a code-recovery task.

## Incident

Five concurrent `/audit-library` sessions (repl, workspace, deploy, pytest-device, plus a HotPath / cache refactor) committed against one local `main` branch and one shared git index over a ~30-minute window.

At least two commits landed with message-vs-content mismatch:

- `84e3c1a3 deploy: drop "canonical X" tic` actually carries the pytest-device MEDIUM-perf changes (`VERSION` + memoize cache + new tests).
- `b4fbd5ba workspace audit: drop "Legacy additive deploy"` carries the deploy `"canonical X"` docstring drops plus workspace CLI edits.

Every intended file change landed somewhere, but commit-message-vs-diff is unreliable for these two commits — `git log -p` is authoritative.

No code recovery needed.

## Second incident (2026-05-20)

`/audit-comments libraries/config` Pass 2 collided with a concurrent `/audit-comments libraries/mqtt` Pass 1. The mqtt-Pass-1 commit (`5f9b0d41 audit-comments mqtt Pass 1 — subtractive sweep across 3 src/ files`) carries the config-Pass-2 working-tree edits as a silent rider: `libraries/config/VERSION`, `libraries/config/src/chumicro_config/section.py` (the `is_config_like` rewrite), and `libraries/config/tests/test_config.py` (the `test_default_path_constant_is_root_runtime_config_msgpack` docstring rewrite) all landed inside the mqtt commit. Commit message describes only mqtt; the config diff has no commit subject of its own. Same shape as the prior incident: every change landed, the message-vs-content mapping is wrong, `git log -p` is authoritative.

New data point: the scrambling can scoop in-flight working-tree edits between one agent's Pass 1 commit and its Pass 2 commit, not just files the second agent staged itself. The window is `Pass-1-commit → Pass-2-staging`.

## Infra opportunities

1. **Require explicit pathspecs in the `git-commit` skill body when other Claude processes are detectable on the same checkout.**  `git add -p` or a list of files by name closes the door on accidentally folding another agent's staged delta into your commit.
2. **Post-commit verification step that re-reads the staged file set vs. the message claim.**  Cousin to the `--cached` stat check already done pre-commit — would catch the mismatch class at write time instead of read time.
