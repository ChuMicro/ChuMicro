# Handoff 2026-05-12 — workspace-library-curation design fully resolved, Phase 1 implementation pending

## Audit 2026-05-17 (252 commits later — resume-ready, with corrections)

Validated against ground truth before any cold resume: `eb2d7543`, the
workstream-as-source-of-truth, Decision 0062 (`accepted`),
`release.yml`'s publish-on-VERSION-bump trigger, and the
`sources._resolve_module` walker seam all still hold. **Q1's
load-bearing premise is intact** — all 15 libraries still
`include = ["src/", "VERSION", "README.md"]`; no Phase 1 work started;
"nothing partial" still true. One **material drift**: `ef4f8e1f`
declared `[test]` extras across all 15 libraries' `pyproject.toml`
*after* this handoff — Q1's "sdist ships `tests/`" now means a curated
consumer who wants to run the shipped tests installs
`chumicro-<lib>[test]`; the build-time regression test should also
assert the `[test]` extra is declared, and the design note should say
so. Trivial drift: `patch_experimental` is line 606, not ~604. The
`.idea/chumicro.iml` gotcha below is **stale** — strike it.

## What this session was about

User picked up the `workspace-library-curation` workstream (chartered earlier the same day as a Tier 2 follow-up to Decision 0062).  Goal: drive the four open design questions in the workstream doc to resolution so Phase 1 implementation can start.  All four questions answered through iterative back-and-forth; design committed as `eb2d7543`.

## What got done

- `eb2d7543` — `workspace-library-curation: resolve all four design questions`.  Folded the live design conversation into the workstream doc; updated the `## Next` entry in `plans/next-up.md` to reflect the simplified design.

## What's in flight

Nothing partial.  Working tree has one pre-existing unrelated change (see Gotchas).

## Decisions made

All four resolved-design sections are now in `plans/workstreams/workspace-library-curation.md` — the workstream doc is the source of truth.  Headlines:

- **Q1 — Source channel**: PyPI sdist for both `stable` and `experimental`.  No new bundle subtree, no `bundle_manager.py` change.  Gating prep: extend each library's `[tool.hatch.build.targets.sdist].include` from `["src/", "VERSION", "README.md"]` to also ship `tests/` + `examples/` + `docs/`.  15 one-line edits + a build-time regression test.
- **Q2 — Pin-state location**: new `libraries:` table in `workspace.yml` sibling to existing `library_sources:`.  Defer `libraries.yml` split until table crosses ~30 entries.
- **Q3 — Default channel + pin format**: default `stable`; `--channel experimental` per-add override; `--floating` opt-in records `version: HEAD` for always-fresh resolution.  No SHA path — `release.yml` already publishes every main merge with a VERSION bump to `chumicro-<lib>-experimental` on PyPI, so tracking main HEAD ≡ tracking experimental latest.
- **Q4 — Declined transitive deps**: record `declined: true` in `workspace.yml`.  Library-side ImportError contract from Decision 0062 keeps runtime failures loud if the user forgets to also add `__chumicro_skip_factories__` to their entrypoint.

Plus a new section, **Dev-mode interaction (per-library override)**: `chumicro-dev.toml` redirects only chumicro libraries that exist in the sibling checkout — partial sibling checkouts work cleanly, and user / third-party libraries in `libraries/` are never touched by dev mode.

Nothing here needs promotion to an ADR — the design is workstream-scoped (an implementation plan for a specific workstream), not a cross-cutting tradeoff.  ADR conversation can come later if something cross-cutting surfaces during Phase 1.

## What was learned

Verified facts that drove the design (all bench-checked 2026-05-12):

- Every library's `pyproject.toml` uses identical hatch sdist config: `include = ["src/", "VERSION", "README.md"]`.  Tests, examples, docs are NOT in current sdists.
- `chumicro_mqtt-0.10.2.tar.gz` is 10 files / 32 KB.  Post-change estimate: 80-150 KB per library.
- `.github/workflows/release.yml` triggers on `push: main` filtered to `paths: libraries/*/VERSION`.  So every VERSION-bumped main merge auto-publishes to PyPI experimental — this is what makes "no main channel" tenable.
- `bundle_manager.py`'s `patch_experimental()` (line 604) renames `chumicro-<lib>` → `chumicro-<lib>-experimental` for the experimental release.  Both channels are already on PyPI; only the sdist content is missing.

## To verify next session before Phase 1 starts

- **Walker integration** — does `chumicro_deploy.sources._resolve_module` already put `libraries/` ahead of any sibling chumicro checkout in search-path order?  The workstream doc names this as a Phase-1-implementation detail; verify before writing the fetch backend so the seam is right.
- **`workspace.yml` schema_version field** — does the `libraries:` table addition need a schema version field, or can the CLI tolerate absence (legacy workspaces) by treating it as `{}`?  Lean: latter, pick during Phase 2 CLI scaffolding.
- **sdist regression-test placement** — build-time inside `scripts/run.py build`, or publish-time inside `release.yml`?  Lean: build-time so contributors see failures before push; publish-time as backstop.

## Dead ends — design alternatives tried and rejected

Future-me may be tempted by these.  Don't re-walk them:

- **`full/<lib>/` subtree in bundle repos** (was the initial Q1 answer).  Rejected after user surfaced duplication concern — would have created a second source of truth alongside the PyPI sdist, conflated bundle-repo purpose (deployment artifacts for `mip`/`circup`) with source distribution, and added a `_stage_full_subtree()` helper to `bundle_manager.py` that wasn't earning its keep.
- **GitHub tarball API backend** for a `main` channel (the second-pass Q1 answer that came after dropping `full/`).  Rejected after user pointed out that `release.yml`'s publish-on-VERSION-bump means main HEAD ≡ experimental latest.  An additional fetch backend would only have uniquely fetched unpublished WIP commits — and a developer wanting those is by definition working on chumicro itself and belongs in dev mode (sibling checkout), which the per-library override now handles correctly.
- **Blanket dev-mode override** (initial assumption).  Rejected — user clarified dev mode should only redirect chumicro libraries that exist in the sibling checkout, not blanket-override every entry in `libraries:`.  This is now per-library: partial sibling checkouts work, user/third-party libs flow through untouched.
- **Refusing-install on declined transitive deps** (Q4 option a).  Rejected as too friction-y for the common case of user injecting a custom transport.
- **Silent install with no decline record** (Q4 option c).  Rejected — loses audit trail, every subsequent `library update` re-asks the same question.

## How to rebuild context fast

Read in this order:

1. `plans/workstreams/workspace-library-curation.md` (the resolved design — single source of truth)
2. `plans/decisions/0062-entrypoint-factory-skip.md` (the parent ADR that triggered this workstream as a Tier 2 follow-up)
3. `libraries/mqtt/pyproject.toml` lines 45-47 (the sdist-include block that needs the 15-library edit)
4. `.github/workflows/release.yml` lines 1-5 (the publish-on-main-VERSION-bump trigger that makes "no main channel" tenable)
5. `scripts/bundle_manager.py` `patch_experimental()` around line 604 (how the experimental package name is currently produced)

Useful grep terms when poking around:

- `__chumicro_skip_factories__` — Decision 0062's opt-out marker; appears in `workbench/deploy/src/chumicro_deploy/skip_factories.py` + `sources.py`
- `library_sources:` — existing workspace.yml table the curated `libraries:` table will live alongside
- `chumicro-dev.toml` — the marker file that activates dev mode

For Phase 1 implementation, the first concrete units of work are independent and can be parallelized:

- Per-library `pyproject.toml` sdist-include extension (15 libraries × one line)
- Build-time regression test in `scripts/run.py build` that asserts each built sdist contains `tests/`, `examples/`, `docs/`
- New `chumicro_workspace.library` module with PyPI fetch backend (depends on the first two landing first so there's something to fetch)
- The `chumicro-workspace library {list,add,update,remove,switch-channel}` CLI surface (depends on the fetch backend)

## Open questions waiting on user

None blocking.  User gave green light on the full design; Phase 1 is unblocked.  The three "remaining open items" in the workstream doc are implementation-detail questions to resolve in flow during Phase 1 work, not user decisions.

## Gotchas

- ~~`.idea/chumicro.iml` is dirty in the working tree~~ **STALE (2026-05-17 audit)** — that was a 2026-05-12 session-transient PyCharm artifact; the tree is clean 252 commits later. Ignore this gotcha.
- **`[test]` extras now exist (post-handoff, `ef4f8e1f`)** — Q1's "extend each library's sdist `include` to ship `tests/`" must reconcile with the per-library `[test]` optional-dependency extra: shipping the test files is necessary but not sufficient to *run* them off a curated install; the consumer needs `chumicro-<lib>[test]`. Fold this into the Q1 design note and the build-time sdist regression test (assert both the `tests/` content *and* the `[test]` extra) when Phase 1 starts.
- **`version: HEAD` is a sentinel, not a PyPI version string** — when implementing the resolver, detect `HEAD` before passing to PyPI's version resolver.  PyPI doesn't recognize "HEAD" as a version; the resolver should translate `HEAD` → `latest` for the channel's package.
- **Phase 1 changes 15 library `pyproject.toml` files** — that's a VERSION bump per library (sdist content change is a publish-affecting change).  Either bundle all 15 into one VERSION-bump commit per library, or take a more deliberate approach with a workstream-wide release pass.  Worth deciding before the edits land so the publish chain doesn't churn.
