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

## Third incident (2026-05-20, evening)

`/audit-comments workbench/deploy` Pass 1 HIGH collided with a concurrent `/audit-comments workbench/checks` Pass 2.  The checks-Pass-2 commit (`e302b5d9 audit-comments checks Pass 2 — REWRITE 5 degraded comments + 1 ## Next`) carries the deploy-Pass-1-HIGH working-tree edits as a silent rider: `tests/test_recovery.py`, `tests/test_circuitpython_transport.py`, `tests/test_firmware_url.py`, `tests/test_diff_deploy.py`, `tests/test_macos_fskit.py` — five files, ten line-pair edits dropping "legacy"/"canonical" tics and a history paragraph.  Commit subject and body describe only the checks REWRITEs.  `git log -p e302b5d9 -- workbench/deploy/tests/` shows the absorbed deploy edits.

Window confirmation: the staging-add and the failing-commit on the deploy side were separated by an arrow-pair of `git restore --staged` calls (to drop unrelated pre-staged files: `plans/next-up.md`, `scripts/*`, `workbench/checks/*` that the deploy agent had inherited in its index).  Between the deploy agent's `git restore --staged` and its `git commit`, the checks agent's `git add -A` + `git commit` ran.  The deploy agent's `git commit` then ran with an empty index ("no changes added to commit") because the checks commit had already swept the deploy staged files into its own commit.

Diagnostic signal: a deploy `git commit` failing with "no changes added" when `git diff` of the intended files shows the edits are still on disk (modified-but-unstaged) is the signature.  Compare against the most recent commit's `-- <your-files>` to confirm whether the work landed elsewhere.

## Infra opportunities

1. **Require explicit pathspecs in the `git-commit` skill body when other Claude processes are detectable on the same checkout.**  `git add -p` or a list of files by name closes the door on accidentally folding another agent's staged delta into your commit.
2. **Post-commit verification step that re-reads the staged file set vs. the message claim.**  Cousin to the `--cached` stat check already done pre-commit — would catch the mismatch class at write time instead of read time.
