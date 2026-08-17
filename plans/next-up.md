# Next Up

> Work queue.  One bullet per item, no sub-bullets — anything needing more than a title goes to [`workstreams/<name>.md`](workstreams/) and surfaces here as a one-line pointer.  Tracks status, not research.  No `## Done` section — `git --no-pager log` carries history.

## Now

- [ ] **Public repo mode — process and settings BOTH LANDED 2026-08-09; punch list remains.**  [workstreams/public-repo-mode.md](workstreams/public-repo-mode.md) — PR #11 merged (Decision 0120 main-is-PR-only, workflow least-privilege + SHA pins, `@claude /review`, maintainer runbook, contributor-docs updates), and the five settings flips are done and verified: ruleset bypass actors to PR-mode, workflow-token default back to read, fork-PR CI approval for all outside collaborators, pypi environment restricted to main, and private vulnerability reporting ENABLED (found disabled while flipping — SECURITY.md's only reporting channel pointed at a switched-off feature).  `ANTHROPIC_API_KEY` verified live: the first `@claude /review` ran end to end on PR #14 and its findings were applied there.  Dependabot #7/#9 closed as superseded by #11's SHA pins.  Open: the workstream punch list (changelogs, py.typed, labeler, provenance, chunraid hardware lane someday) and the repo-level require-SHA-pinning setting.

## Next

- [ ] **No lint rule gates tick math, so `ticks_diff` is convention-only.**  AGENTS.md:66 requires all time math through `chumicro_timing`, but its named offenders are tick *sources* (`time.monotonic`, `supervisor.ticks_ms`), not the naive `now_ms >= deadline_ms` compare that `ticks_diff` exists to prevent; the style guide omits the rule entirely and no CHU rule covers it.  A violation passes every CPython test and every board run until `TICKS_PERIOD` (`1 << 29` ms, ~6.2 days) wraps and the compare inverts.  Library sources are clean today (grepped 2026-08-17); scope a CHU rule plus a style-guide entry, and watch false positives on size/index/count compares.

- [ ] **Workspace → workbench rename: chumicro-side follow-through (template repo renamed 2026-08-10).**  [workstreams/workbench-rename.md](workstreams/workbench-rename.md) — near-term half LANDED 2026-08-10 (`DEFAULT_TEMPLATE_URL` + its pinned test, the doc links, the two checks-rule comments; workspace 0.54.1 → 0.54.2).  Remaining: the sized full-rename menu (PyPI package, module, `workspace.yml`, hosted docs path), each needing a per-surface user call, and the workbench-word collision spots to reword when touched.
