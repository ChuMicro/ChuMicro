# Next Up

> Work queue.  One bullet per item, no sub-bullets — anything needing more than a title goes to [`workstreams/<name>.md`](workstreams/) and surfaces here as a one-line pointer.  Tracks status, not research.  No `## Done` section — `git --no-pager log` carries history.

## Now

- [ ] **Public repo mode — process and settings BOTH LANDED 2026-08-09; punch list remains.**  [workstreams/public-repo-mode.md](workstreams/public-repo-mode.md) — PR #11 merged (Decision 0120 main-is-PR-only, workflow least-privilege + SHA pins, `@claude /review`, maintainer runbook, contributor-docs updates), and the five settings flips are done and verified: ruleset bypass actors to PR-mode, workflow-token default back to read, fork-PR CI approval for all outside collaborators, pypi environment restricted to main, and private vulnerability reporting ENABLED (found disabled while flipping — SECURITY.md's only reporting channel pointed at a switched-off feature).  `ANTHROPIC_API_KEY` verified live: the first `@claude /review` ran end to end on PR #14 and its findings were applied there.  Dependabot #7/#9 closed as superseded by #11's SHA pins.  Open: the workstream punch list (changelogs, py.typed, labeler, provenance, chunraid hardware lane someday) and the repo-level require-SHA-pinning setting.

## Next

- [ ] workspace: the scaffolded library README's contributing section hardcodes `chumicro-workspace add-device`; every live hint now adapts via `runner_invocation`, but `scaffold_library` has no workspace root in scope to adapt generated docs at scaffold time.
