# Decision 0075: Retire `init` — workspace creation is clone-only

Status: `accepted`
Date: `2026-05-18`
Summary: Workspace creation is clone-only (`git clone` of `ChuMicro-Workspace-Template` + `python3 run.py setup`); `chumicro-workspace init` removed; ownership zones collapse from three to two.
Related: [Decision 0038](0038-workspace-bootstrap-via-clone.md) (§3 partially superseded — `init` retired, `update` retained), [Decision 0029](0029-project-workspace.md) §9 (ownership zones — now two, not three).

## Context

Decision 0038 §3 folded `init` and `update` into `chumicro-workspace`
and explicitly *rejected* retiring `init`, on the reasoning that "a
thin wrapper costs almost nothing and gives users a forkable name to
invoke." Practice contradicted that:

- `init` is unreachable as a real entry point. To run
  `chumicro-workspace init` a user must already have
  `chumicro-workspace` installed — but the only supported way to get
  it installed is `run.py setup` *inside an already-cloned template*.
  The non-circular path (clone the repo, or GitHub "Use this
  template") never touches `init`. The README leads with the clone
  recipe; `init` is documented nowhere as primary.
- A "thin wrapper" is not free: it re-implements `git clone` + `.git`
  strip + `git init`, carries `--force` (a destructive clear), owns a
  parser, a command, `_report_init_files`, and the `ApplyAction.WRITTEN`
  reporting branch, and forces every doc and the zone model to keep an
  "init" vocabulary that no longer maps to anything.
- It actively contradicts the design intent that there be *no* path
  where a user `cd`s into an empty directory, runs a CLI command, and
  is handed a workspace. Creation is cloning a repo, full stop.

## Decision

**Invariant: no CLI command may materialize a workspace on disk.**
Workspace creation is exclusively: clone the
`ChuMicro-Workspace-Template` repo (`git clone`, or GitHub "Use this
template"), then `python3 run.py setup`. This is the principle Decision
0038 §3 should have stated; it recorded the mechanism ("clone, not
pip-installed scaffolder") instead, leaving a hole a clone-based `init`
CLI walked straight through.

Accordingly, `chumicro-workspace init` and
`chumicro_workspace.template_apply.init` are removed.

`update` is retained unchanged and is now the *sole* CLI surface of
the clone-and-reflow machinery: it re-flows the `Zone.TOOL_OWNED`
slice of an existing workspace from the template upstream. It is the
supported way to pull template evolution into a workspace.

The ownership model collapses from three zones to two. With `init`
gone, `Zone.INIT_ONLY` (`.gitignore`, `README.md`) was behaviorally
identical to the `classify()` user-owned default — both are skipped by
`update`. The zone, its path set, and the classify branch are deleted;
those files fall through to `USER_OWNED` with identical behavior.
`ApplyAction.WRITTEN` and the init-only test/fixture vocabulary go with
them. Nothing was published, so no compatibility surface is owed.

## Consequences

- One fewer command, one fewer ownership zone, one fewer report
  action; `template_apply.py` loses `init`, `_git_init`,
  `_strip_dot_git`, `_report_init_files`.
- Decision 0038 §3's "Rejected: retire `init`" is reversed; §3 carries
  a superseding pointer to this decision. The clone recipe (§1) and
  `update` (§3) are unaffected.
- Docs that listed `init` as a lifecycle command (`AGENTS.md`,
  `workbench/README.md`, `workbench/workspace/README.md`) drop it;
  health/error hints that pointed at `init` now point at `setup` /
  `update` / the clone recipe as appropriate.
- Historical/archived plans that describe the shipped-then-removed
  `init` are left intact as historical record.
- The separately-tracked `run.py` bootstrap hardening (idempotent
  self-repair + verify, ported from `scripts/prepare_workspace.py`)
  lets the clone-only path stand as the only path without a fallback.
