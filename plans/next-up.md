# Next Up

> Work queue.  One bullet per item, no sub-bullets — anything needing more than a title goes to [`workstreams/<name>.md`](workstreams/) and surfaces here as a one-line pointer.  Tracks status, not research.  No `## Done` section — `git --no-pager log` carries history.

## Now

- [ ] **Public repo mode — process and settings BOTH LANDED 2026-08-09; punch list remains.**  [workstreams/public-repo-mode.md](workstreams/public-repo-mode.md) — PR #11 merged (Decision 0120 main-is-PR-only, workflow least-privilege + SHA pins, `@claude /review`, maintainer runbook, contributor-docs updates), and every one-time settings flip is done and verified: ruleset bypass actors to PR-mode, workflow-token default back to read, fork-PR CI approval for all outside collaborators, pypi environment restricted to main, and private vulnerability reporting ENABLED (found disabled while flipping — SECURITY.md's only reporting channel pointed at a switched-off feature).  Dependabot #7/#9 closed as superseded by #11's SHA pins.  Open: the workstream punch list (changelogs, py.typed, labeler, provenance, chunraid hardware lane someday) and the first live `@claude /review` smoke test.

## Next

- [ ] **Workspace-tooling hygiene, the seam-coherence tail** ([workstreams/seam-coherence.md](workstreams/seam-coherence.md) items 8-13; the library side landed 2026-08-09, board-validated).  In plain terms: `update` overwrites tool-owned files without checking for local edits and never deletes files removed upstream; `library add` writes `pyrightconfig.json` paths into a tracked file, permanently dirtying a template checkout; the ownership-zone tables are hand-restated in four documents and drift; template CI installs from `>=` floors with no lockfile, so one bad workspace release breaks every consumer's CI with nothing to roll back to; and `update` silently clobbers user edits to `pyproject.toml` outside the dependencies carve-out.
- [ ] **Device-matrix reliability** ([workstreams/device-matrix-reliability.md](workstreams/device-matrix-reliability.md)) — what remains after the 2026-08-09 bench repairs (FSKit flush barriers, UID drive pinning, boards back on drive mode) lives in the workstream: first-association grace, the `wifi.tx_power_dbm` knob for the UM P4 boards, the tinys3 RF watch, and the CP-serial transport notes.
