# Next Up

> Work queue.  One bullet per item, no sub-bullets — anything needing more than a title goes to [`workstreams/<name>.md`](workstreams/) and surfaces here as a one-line pointer.  Tracks status, not research.  No `## Done` section — `git --no-pager log` carries history.

## Now

- [ ] **Public repo mode — process flip landed on the `public-repo-mode` branch, settings flips pending (user call 2026-08-09).**  [workstreams/public-repo-mode.md](workstreams/public-repo-mode.md) — Decision 0120 (main is PR-only), workflow least-privilege + SHA pins, `@claude /review`, maintainer runbook, and the contributor-docs updates ride one PR; the one-time maintainer settings flips (ruleset bypass to PR-mode, Actions default to read, fork-PR approval to all outside collaborators, pypi environment branch policy, `ANTHROPIC_API_KEY` with a spend cap) are listed in the workstream and the PR body.

## Next

- [ ] **Workspace-tooling hygiene, the seam-coherence tail** ([workstreams/seam-coherence.md](workstreams/seam-coherence.md) items 8-13; the library side landed 2026-08-09, board-validated).  In plain terms: `update` overwrites tool-owned files without checking for local edits and never deletes files removed upstream; `library add` writes `pyrightconfig.json` paths into a tracked file, permanently dirtying a template checkout; the ownership-zone tables are hand-restated in four documents and drift; template CI installs from `>=` floors with no lockfile, so one bad workspace release breaks every consumer's CI with nothing to roll back to; and `update` silently clobbers user edits to `pyproject.toml` outside the dependencies carve-out.
- [ ] **Device-matrix reliability** ([workstreams/device-matrix-reliability.md](workstreams/device-matrix-reliability.md)) — what remains after the 2026-08-09 bench repairs (FSKit flush barriers, UID drive pinning, boards back on drive mode) lives in the workstream: first-association grace, the `wifi.tx_power_dbm` knob for the UM P4 boards, the tinys3 RF watch, and the CP-serial transport notes.
