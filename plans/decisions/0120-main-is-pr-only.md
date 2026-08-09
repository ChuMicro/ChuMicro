# Decision 0120: Main is PR-only

Status: `accepted`
Date: `2026-08-09`
Summary: `main` takes changes only via squash-merged PRs with required checks green, maintainer and agent sessions included; topic branches replace direct pushes; ruleset bypass is PR-mode only.
Related: 0019, 0092, 0117

## Context

The repository is public as of 2026-08-09.  Decision 0019 chose the single-branch model and, while the repo was private, had maintainer and agent work commit directly to `main`, because an approval requirement would have blocked the only path work actually took.  Public changes the calculus: outside contributors follow the PR flow the contributor docs describe, the history is the project's public face, and a direct-push habit means the required checks gate nothing for exactly the actor who ships most changes.  Merges to `main` also auto-publish experimental releases (0019), so an unreviewed push is an unreviewed release.

## Decision

- `main` accepts changes only through pull requests: squash merge, review threads resolved, required checks green (`preflight`, `compatibility (3.11)` / `(3.12)` / `(3.13)`, `Validate mpy bytecode`).  The ruleset enforces this for every actor, and its bypass actors are configured in "pull request" mode, so even an emergency bypass moves through a PR merge, never a direct push.
- Maintainer and agent sessions work on short-lived topic branches (`fix/…`, `docs/…`, `feature/…`, as CONTRIBUTING.md names them) and open a PR.  A topic branch lives for one PR and is deleted on merge (repository setting).
- Decision 0019's single-branch model otherwise stands: `main` is the only long-lived branch, releases are tags, hotfix release branches stay short-lived.  This decision changes how changes reach `main`, not the branch topology.
- The agent checkpoint flow (task-checkpoint skill) ends a unit of work by pushing its topic branch and opening or updating a PR, not by pushing `main`.

Rejected: keeping direct pushes with a "be careful" norm.  Norms without enforcement already failed quietly here: the 2026-07-28 direct push landed 17 unbumped `pyproject.toml` edits under green CI because the diff-base logic graded only the pushed tip, a shape a PR diff (`origin/main...HEAD`) grades whole by construction.

## Consequences

- The maintainer's own work waits for CI like everyone else's.  Required approvals stay at zero while the project has one maintainer (GitHub forbids self-approval); the required checks plus the deliberate merge click are the gate.
- Merges land as squash commits, so `release.yml`'s push trigger sees one commit per PR and grades the whole change-set.
- AGENTS.md's workflow rules and the task-checkpoint skill change from "commit and push" to "push the branch, open the PR".
- Concurrent sessions stop interleaving commits on `main` between fetch and push; each rides its own branch, which also retires the failure class in `plans/workstreams/concurrent-agent-commit-scrambling.md`.
