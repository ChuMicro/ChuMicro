# Workstream: public repo mode

Status: **active.**  Opened 2026-08-09, the day the repo went public (user call: "we need to go into public repo mode... we are public now so we need to do public things and be a good public face").

## Goal

The repository operates as a public project: `main` is PR-only for everyone (Decision 0120), fork PRs are supported and safe to run CI against, AI review is available without being abusable, the release fabric runs least-privilege, and the contributor-facing docs describe the process that actually exists.

## Landed 2026-08-09 (the public-repo-mode PR)

- Decision 0120 (main is PR-only), 0019 corrected in place, AGENTS.md rule and task-checkpoint skill moved to branch-plus-PR flow.
- Workflow hardening: per-job permissions (only the release jobs hold `contents: write` + `id-token: write`), every action SHA-pinned with a version comment, CI concurrency cancellation for superseded PR runs, `persist-credentials: false` on CI checkouts, dispatch input moved out of shell interpolation, docs-deploy token dropped to read (its push rides the deploy key).
- `ai-review.yml`: Claude review on a maintainer's `@claude /review` comment (user call 2026-08-09: comment command over label, and the gate exists because a drive-by PR must never be able to spend tokens on the maintainer's account).  PR-as-data design, advisory-only.  Abuse model written up in docs/contributing/maintainers.md.
- Docs: CONTRIBUTING "How changes land", maintainer runbook, first-time-contributor CI-approval notes, security-fix release path in SECURITY.md and releases.md, README channel visibility and repo-map cleanup, promotion-request template takes a wave, labels grown (ai-review, good first issue, help wanted, question, needs-triage, security) and de-em-dashed.

## Settings — ALL FLIPPED and verified 2026-08-09 (user go, run from the session)

- Main ruleset bypass actors: `pull_request` mode for OrganizationAdmin, RepositoryRole(admin), and the user.  Direct pushes to main are dead; emergency bypass works only through a PR merge.
- Actions default workflow permissions: back to `read` (it had been widened to `write` during the release-403 hunt; every workflow declares its own, so the default only backstops future files).
- Fork-PR workflow approval: all outside collaborators.
- `pypi` environment: deployment branch policy restricts to `main` (verified: one policy row, `main`).
- Private vulnerability reporting: **found DISABLED and enabled.**  Durable lesson: SECURITY.md's only reporting channel pointed at a switched-off feature, and nothing in the repo could have caught it — settings-side claims in docs need a settings-side verification step, which the maintainer runbook's verification commands now cover.
- `ANTHROPIC_API_KEY`: user reports added 2026-08-09; not visible in repo Actions secrets from the session (may be org-level), so the first live `@claude /review` is the real verification.
- Still open: the repo-level "require SHA pinning" Actions setting, now that every workflow is SHA-pinned.

## Punch list (deferred, roughly by value)

- **Changelogs.**  Zero changelog files for 19 independently versioned PyPI packages; users diff versions by reading auto-generated release notes.  Decide the shape (per-library CHANGELOG.md vs release-notes page on the docs site) before writing any.
- **`py.typed` for the 13 device libraries.**  Only the 5 workbench packages ship it, so typed consumers of the libraries get no annotations despite the style guide mandating them.  One marker file each plus a hatchling include; verify wheel contents.
- **PR auto-labeler.**  17 of 29 labels (`lib:*`, `semver:*`) have no automation; a path-based labeler workflow covers `lib:*` nearly for free.  `needs-review` label is redundant with native review state and can be dropped at the same time.
- **README badges** (CI, docs, license).  Small, conventional, currently absent.
- **Bundle provenance.**  PyPI uploads carry attestations; the circup zips and bundle-repo trees (the path device users actually install from) are unsigned.  Investigate artifact attestations on the bundle release assets.
- **`BUNDLE_TOKEN` scope.**  A PAT today.  Replace with a fine-grained PAT scoped to the two bundle repos (Contents + Releases) or a GitHub App token.
- **SUPPORT.md** formalizing Discussions as the help channel (GitHub surfaces it in the issue flow).
- **Dependabot for Python dev deps.**  Deliberately excluded today (`dependabot.yml` comment); `requirements-dev.txt` pins cryptography and a git-fork mike with no automated security updates.  Revisit the exclusion.
- **Planning-tree public face.**  `plans/` and `docs/superpowers/` are tracked and public with no README telling a visitor what they are looking at; decision records are a public asset, the work queue and handoffs deserve a one-paragraph framing file.
- **CodeQL + secret scanning.**  Settings-side (default setup covers Python for free on public repos); not a file in this repo.

## Hardware CI via chunraid (someday, explicitly not now)

The missing piece is not the boards, it is the babysitter: a host harness that can power-cycle a wedged board and drive the reset / hold-boot-button dance when a runtime locks up mid-suite, because a hardware lane whose recovery is "walk to the bench" cannot gate anything.  Design sketch when the time comes: chunraid hosts the boards ("stable and reliable chips that don't crash every 10 minutes", user call 2026-08-09), a controllable power/BOOT-line mux per board, the existing `chumicro-pytest-device` + `devices.yml` machinery on top, reporting into the `board-test` label rather than required checks at first.  Do not start this before the recovery harness exists.
