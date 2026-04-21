# Workstream: Rename ChuMicro → ChipPy

Status: `proposed`

## Purpose

Rebrand the entire project from `ChuMicro` to `ChipPy` in one coordinated cutover, and reset every publishable library to version `0.0.0`. The current version history on PyPI (`chumicro-timing` at `0.1.25`, etc.) is entirely testing churn — renaming the package namespace lets us start a clean public version history without PyPI's "you cannot delete versions, ever" constraint getting in the way.

The rename is planned to happen right before the first public-readiness milestone. Nobody is consuming the current bundles or PyPI packages yet, so we do not need to preserve backwards compatibility.

## Why ChipPy

- `Chip` is an established Charles nickname AND literally means microcontroller chip — the personal origin and domain word collide in the same syllable
- Dropping "Micro" fixes a real scope problem: CPython is a first-class runtime, and the roadmap widens, not narrows
- `Chu` sounds like "chew" when said aloud; `Chip` + `Py` reads cleanly the first time
- Short, unambiguous, playful

## Goals

1. All GitHub repositories live under a new `ChipPy` org
2. All Python packages import as `chippy_<name>` and publish to PyPI as `chippy-<name>`
3. All library `VERSION` files reset to `0.0.0`
4. All bundle infrastructure (circup zips, mip package.json, date-based tags) targets the new bundle repos
5. All docs, planning docs, IDE configs, CI, and lint rules reference the new brand
6. First post-rename release publishes fresh `0.0.0` packages and fresh bundle `YYYYMMDD` tag
7. Old `ChuMicro` org archived (not deleted — git history stays reachable for reference)

## Non-goals

- Preserving the commit hash of any ChuMicro-era commit (history is carried through, but SHAs will not match after any filter-branch-style rewrites — none are planned here, just renames in-place)
- Migrating existing PyPI package versions (impossible by design; old `chumicro-*` packages stay at their last version forever, eventually abandoned)
- Keeping old bundle repos operational during transition — they get archived
- Rewriting commit authorship (orthogonal — already handled for the bundle repo)

## Pre-flight gates

Block the cutover until every item here is a confirmed "yes":

- [ ] **GitHub org `ChipPy` is available** (claim the org first — do not start code work until this is locked)
- [ ] **PyPI namespace is free** for every planned package: `chippy-timing`, `chippy-runner`, `chippy-compat`, `chippy-msgpack` (and any support packages we choose to publish)
- [ ] **Verify `chippy` is not squatted** as a meta-package on PyPI (check even though we don't plan to publish a top-level `chippy`)
- [ ] **Decide final naming for support packages.** Current:
  - `support/abstractions/` (`chumicro_abstractions`) — internal, never published
  - `support/device_transport/` (`chumicro_device_transport`) — candidate for future publish as `chippy-deploy`, see `plans/next-up.md`
  - `support/test_harness/` (`chumicro_test_harness`) — internal
  - Decision: keep `chippy_<name>` import namespace for all of them even if never published, for consistency
- [ ] **Decide starting version.** `0.0.0` per the user's stated goal. First real feature release bumps to `0.1.0`. `0.0.0` will be the permanent first PyPI entry — reserve the `0.0.0` slot as effectively a placeholder, then bump to `0.1.0` for the first real release.
- [ ] **Decide lint rule prefix.** `CHU001`–`CHU005` → `CHP001`–`CHP005`. Propagate to `# noqa: CHU001` suppressions, `check_names.py`, `check_whitespace.py`, Decision 0022, style guide
- [ ] **Decide docs domain.** Current docs deploy to `chumicro.github.io/ChuMicro/*`. New: `chippy.github.io/ChipPy/*` (or similar). Confirm mike versioning resets cleanly
- [ ] **Decide PyCharm/VS Code workspace-file name.** `.idea/` project name and any `*.code-workspace` filename currently reference ChuMicro

## Branch strategy

Per Decision 0019 and the active branching policy (commit directly to main while the repo is private), the rename lands on `main` — but it is atomic: every internal reference must update in the same commit, or the workspace will not import, lint, test, or build. Do this as a single (possibly large) commit, not a multi-step series. Run `preflight` before committing.

Exception: the GitHub org transfer and bundle repo creation happen *outside* the repo; the in-repo code change happens *after* those are ready to receive pushes.

## Execution phases

### Phase 0 — External infrastructure (no in-repo changes)

1. Create GitHub org `ChipPy`
2. Create empty repos under it:
   - `ChipPy/ChipPy` (or rename the main repo — see "Repo rename vs fresh" below)
   - `ChipPy/ChipPy-Bundle`
   - `ChipPy/ChipPy-Bundle-Experimental`
3. Configure PyPI trusted publishers for each new package: `chippy-timing`, `chippy-runner`, `chippy-compat`, `chippy-msgpack`
   - Each requires a GitHub OIDC trusted publisher binding to `ChipPy/ChipPy` on the `pypi` environment (see `.github/workflows/release.yml:136-138`)
4. Generate a deploy key for the bundle repos if the current workflow uses one (inspect `release.yml` and `promote.yml` for the exact auth scheme before replicating)
5. Set up GitHub Pages for the docs domain on the new repo
6. Copy over GitHub org secrets / environment vars if any (inspect repo settings — do not rely on memory)

#### Repo rename vs fresh

Two options:
- **Option A (preferred): transfer the existing repo** — GitHub repo transfer preserves stars, issues, commit history, PR history, and sets up automatic redirects from the old URL for the life of the old owner. The org name changes cleanly; no SHA churn.
- **Option B: create a fresh repo** — new empty `ChipPy/ChipPy`, force-push the current `main` into it, drop history. Cleaner slate, but throws away commit history that has real context value.

Recommend Option A. The rename commits will appear in history, which is exactly what a future archaeologist needs.

### Phase 1 — In-repo rename (single atomic commit)

All of the following changes go in one commit. Do not push an intermediate broken state.

#### 1a. Rename Python package directories

```
libraries/timing/src/chumicro_timing/        → libraries/timing/src/chippy_timing/
libraries/runner/src/chumicro_runner/        → libraries/runner/src/chippy_runner/
libraries/compat/src/chumicro_compat/        → libraries/compat/src/chippy_compat/
libraries/msgpack/src/chumicro_msgpack/      → libraries/msgpack/src/chippy_msgpack/
support/abstractions/src/chumicro_abstractions/      → support/abstractions/src/chippy_abstractions/
support/device_transport/src/chumicro_device_transport/ → support/device_transport/src/chippy_device_transport/
support/test_harness/src/chumicro_test_harness/      → support/test_harness/src/chippy_test_harness/
```

Also delete the `.egg-info` directories under each `src/` — stale from editable installs, regenerated by `python scripts/run.py setup`.

#### 1b. Rewrite package metadata

Each library's `pyproject.toml` needs:
- `[project] name = "chumicro-<x>"` → `"chippy-<x>"`
- `authors = [{ name = "ChuMicro" }]` → `"ChipPy"`
- `[project.urls]` — `Homepage`, `Documentation`, `Source`, `Issues`, `Bundle` all need the new org+repo
- `[tool.hatch.build.targets.wheel] packages = ["src/chumicro_<x>"]` → `["src/chippy_<x>"]`

Affected files (confirmed via grep):
- `libraries/compat/pyproject.toml`
- `libraries/msgpack/pyproject.toml`
- `libraries/runner/pyproject.toml`
- `libraries/timing/pyproject.toml`
- `support/abstractions/pyproject.toml`
- `support/device_transport/pyproject.toml`
- `support/test_harness/pyproject.toml`
- Root `pyproject.toml`

#### 1c. Reset versions

All four `libraries/*/VERSION` files → `0.0.0\n`.

Support package versions: check each, but these aren't published so keep whatever they have unless they mention a chumicro version.

#### 1d. Rewrite imports

`from chumicro_<x> import ...` → `from chippy_<x> import ...` across:
- All library `src/`, `tests/`, `functional_tests/`, `examples/`
- All `support/*/src/`, `tests/`
- `scripts/` (many references in test code, scaffolds, templates)
- `conftest.py` files
- `support/test_harness/run_cross_runtime.py`
- `scripts/templates/*` (the new-library scaffold templates — verify the generated library uses the new namespace)

Automation hint: a well-scoped `ripgrep | xargs sed` pass can do 95% of this, but verify every diff before committing. Some strings are in prose (README, docstrings, planning docs) and should be rephrased, not mechanically substituted.

#### 1e. Rewrite strings in prose, docs, and templates

Grep survey (confirmed):

- **996 occurrences** of `chumicro|ChuMicro|CHUMICRO` across **200 files**
- Spread across: library READMEs, guides, CONTRIBUTING.md, AGENTS.md, CLAUDE.md (via AGENTS.md), all `plans/decisions/*.md`, `plans/history.md`, `plans/next-up.md`, `plans/open-questions.md`, `plans/patterns.md`, `docs/contributing/*`, `.github/skills/*/SKILL.md`, `.github/ISSUE_TEMPLATE/*`, `.github/workflows/*`, `.github/labels.yml`, `.idea/runConfigurations/*.xml`, `.idea/modules.xml`, `support/docs/extra.css`, `LICENSE`
- Templates: `scripts/templates/api.md.template`, `guide.md.template`, `readme.md.template`, `bundle_readme.md.template`, `run_config.xml.template`, `testing.py.template`

Substitutions (in prose, not code identifiers):
- "ChuMicro" → "ChipPy"
- "Chumicro" (any stray mixed-case) → "ChipPy"
- "chumicro" (in URLs, package names, ids) → "chippy"
- "CHUMICRO" (env vars if any) → "CHIPPY"

#### 1f. Update lint rule prefix

- `scripts/check_names.py`:   `_RULE_CODE = "CHU001"` → `"CHP001"`
- `scripts/check_whitespace.py`: all `CHU00N` rule codes → `CHP00N`
- `plans/decisions/0022-naming-conventions.md`: text references to CHU001
- All `# noqa: CHU001` suppressions in source — update to `CHP001`
- `AGENTS.md` / `docs/contributing/style-guide.md` references
- Tests in `scripts/tests/test_check_names.py` and `test_check_whitespace.py`

#### 1g. Update bundle infrastructure

- `scripts/bundle_layout.py`:
  - `STABLE_BUNDLE_REPO = "ChuMicro-Bundle"` → `"ChipPy-Bundle"`
  - `EXPERIMENTAL_BUNDLE_REPO = "ChuMicro-Bundle-Experimental"` → `"ChipPy-Bundle-Experimental"`
- `scripts/bundle_manager.py` — any hard-coded string or path generation referencing the old names
- `scripts/validate_mip_install.py` — references in help text and fixture URLs
- `scripts/generate_landing_page.py` — docs landing page HTML
- Any README generation template that embeds bundle URLs

#### 1h. Update CI workflows

- `.github/workflows/release.yml`:
  - Trusted publisher `environment: pypi` will need re-binding on PyPI side; workflow YAML unchanged but re-verify secrets
  - Bundle push targets (grep for `ChuMicro-Bundle`)
  - PyPI package names implicit via `pyproject.toml` so no direct hard-coding (verify)
- `.github/workflows/promote.yml`: same considerations
- `.github/workflows/ci.yml`: cache keys, matrix values (grep)
- `.github/ISSUE_TEMPLATE/*.yml`: user-facing brand strings
- `.github/labels.yml`: label names/descriptions

#### 1i. Update IDE configs

All `.idea/runConfigurations/*.xml` hard-code `chumicro` in display names, module references, or paths. `scripts/run.py sync-ide` regenerates these from `scripts/templates/run_config.xml.template` — update the template, delete all run configs, regenerate with `python scripts/run.py sync-ide`.

Also: `.idea/modules.xml`, any `.idea/workspace.xml` project-name field, and any `.vscode/` workspace file.

#### 1j. Update planning docs

All `plans/**.md` references. Decisions are "append-only" per repo policy, but renaming brand strings inside existing decisions is a fact update, not a new decision — do it in-place. Add a note to `plans/history.md` marking the rename milestone.

- Decision 0011 (platform-targeting), 0018 (distribution-bundle-repo), 0019 (branching-model), 0022 (naming-conventions), 0023 (standalone-promote-workflow), 0024 (mip-mpy-folder-serving), 0027 (device-testing-infrastructure), 0028 (deploy-modes) all reference ChuMicro
- `plans/next-up.md`: rename `chumicro-deploy`, `chumicro-settings`, `chumicro-msgpack` references to `chippy-*`
- `plans/open-questions.md`, `plans/patterns.md`, `plans/history.md`

#### 1k. Update root-level files

- `README.md` (29 occurrences)
- `CONTRIBUTING.md` (21 occurrences)
- `LICENSE` (attribution line — verify the form we use)
- `conftest.py`
- `requirements-dev.txt`
- `.gitignore`

### Phase 2 — Commit, preflight, push

1. Run `python scripts/run.py setup` to regenerate editable installs under the new package names
2. Run `python scripts/run.py preflight --coverage-threshold 94` — must pass cleanly
3. Run `python scripts/run.py build` to prove wheels build under the new names
4. Run `python scripts/run.py validate-mip --staging-dir <tmp>` to prove mip + circup paths still work (they point at not-yet-existing bundle repos, so this tests the code, not the live URL)
5. Write commit message to `.scratch/commit-msg.txt` (see skeleton below)
6. Commit and push to new origin

Commit message skeleton:

```
Rename ChuMicro to ChipPy; reset all library versions to 0.0.0

Full rebrand across the workspace:
- Python package namespaces chumicro_* → chippy_*
- PyPI package names chumicro-* → chippy-*
- Bundle repos ChuMicro-Bundle[-Experimental] → ChipPy-Bundle[-Experimental]
- GitHub org ChuMicro → ChipPy
- Lint rule prefix CHU00N → CHP00N
- All VERSION files reset to 0.0.0

Why: PyPI version history cannot be cleared, and the chumicro-*
namespace accumulated test-churn releases we want to shed before
the first public milestone. A namespace rename gives us a clean
version history with no backwards-compat tax, since nothing is
consumed from the old bundles or packages yet.

Why ChipPy specifically: "Chip" is both a Charles nickname and
the literal word for a microcontroller — scope and identity align
in one syllable. "Micro" was starting to narrow the scope
artificially since CPython is a first-class runtime.

No functional changes — symbols, APIs, and file contents (aside
from string substitutions) are unchanged. Verified via preflight
(coverage 94%+) and wheel build across all seven packages.
```

### Phase 3 — First release under new names

1. Pick a single library to release first — recommend `chippy-timing` as the smallest dependency chain
2. Bump its VERSION to `0.1.0` (skipping `0.0.0` for the first real release — `0.0.0` is reserved as the "genesis" entry if we want to reserve the slot; alternatively just start at `0.1.0` and skip `0.0.0` entirely)
3. Push VERSION bump; release workflow fires; publishes to PyPI and stages bundle
4. Verify:
   - `pip install chippy-timing` from PyPI works end-to-end
   - `mip install github:ChipPy/ChipPy-Bundle-Experimental/chippy-timing` works on MicroPython
   - `circup install chippy-timing` works on CircuitPython (once stable bundle has an entry)
   - Docs deploy to the new GitHub Pages URL
5. Release the other three in sequence, each with its own VERSION bump commit

### Phase 4 — Archive old infrastructure

Only after Phase 3 proves end-to-end success:

1. Archive `ChuMicro/ChuMicro-Bundle` and `ChuMicro/ChuMicro-Bundle-Experimental` (GitHub Archive — read-only, keeps URLs live)
2. Archive `ChuMicro/ChuMicro` (or delete if Option B was chosen; if Option A, the transfer already handled this automatically)
3. Leave existing `chumicro-*` PyPI packages as-is (PyPI does not support proper deletion). Consider uploading a `0.1.26` to each with a README-only wheel pointing users at `chippy-*`, or just abandon them silently. Recommend silent abandonment — deprecation spam is worse than no signal when there are zero users.
4. Update any external references: personal blog posts, README badges on user's profile repo, anything linked from `charles-benson.com`-adjacent places

## Risks and rollback

### Risk: PyPI name squatting between decision and Phase 0

If someone else claims `chippy-timing` on PyPI between the time we decide and the time we register, the whole plan breaks. **Register PyPI names the same hour we claim the GitHub org.** Upload empty 0.0.0 packages as placeholders if necessary.

### Risk: half-done rename on main

An incomplete substitution will break imports and fail every test. If preflight is green, the rename is complete. The single-commit discipline makes rollback = `git revert`.

### Risk: CI secrets / trusted-publisher misconfiguration

Phase 3's first release will fail if the trusted publisher bindings on PyPI are not live. Test this in advance with a "publish dry-run" on TestPyPI if the workflow supports it, or cut a pre-release tag that exercises the publish path without making it official.

### Risk: docs versioning collision

mike publishes to `gh-pages` with per-library, per-version subdirectories. A rename may leave stale paths on the old `gh-pages` branch. If the repo is transferred (Option A), GitHub Pages continues to serve the old branch — expect `chippy.github.io/ChipPy/timing/0.1.0/` to appear alongside orphaned `chumicro.github.io/ChuMicro/timing/0.1.25/` content. Accept this or explicitly `mike delete` the old versions.

### Rollback plan

If Phase 1 breaks the repo:
- `git reset --hard HEAD~1` on main (the rename is one commit)
- `git push --force-with-lease origin main`
- Nothing persists on PyPI or the bundle repos because Phase 3 hasn't run yet

If Phase 3 breaks after first release:
- Yank `chippy-timing` 0.1.0 on PyPI (`pip yank`-compatible; doesn't delete but hides)
- Revert the VERSION bump commit
- Investigate, re-release as 0.1.1 once fixed
- `0.1.0` is permanently reserved on PyPI — live with it

## Files touched (summary)

Grep scope (as of 2026-04-21): **200 files, 996 occurrences** of `chumicro|ChuMicro|CHUMICRO` plus:
- 7 Python package directory renames (`src/chumicro_*/` → `src/chippy_*/`)
- 4 VERSION resets
- 5 CHU00N → CHP00N rule code updates
- Full `.idea/` regeneration via `sync-ide`

The grep is the authoritative file list — re-run it at execution time to catch anything added since this plan was written:

```bash
rg -l 'chumicro|ChuMicro|CHUMICRO|CHU00\d'
```

## Checklist (for execution day)

- [ ] Phase 0 complete (org claimed, PyPI names registered, bundle repos exist, trusted publishers bound)
- [ ] Phase 1a: package dir renames
- [ ] Phase 1b: pyproject.toml metadata rewritten
- [ ] Phase 1c: VERSION files = 0.0.0
- [ ] Phase 1d: imports rewritten
- [ ] Phase 1e: prose/docs/template substitutions
- [ ] Phase 1f: lint rule prefix CHU → CHP
- [ ] Phase 1g: bundle_layout.py and related bundle scripts
- [ ] Phase 1h: CI workflows
- [ ] Phase 1i: IDE configs regenerated
- [ ] Phase 1j: planning docs
- [ ] Phase 1k: root-level files
- [ ] Phase 2: preflight green, wheels build, single commit pushed
- [ ] Phase 3: first real release (`chippy-timing` 0.1.0) end-to-end verified
- [ ] Phase 3: remaining libraries released
- [ ] Phase 4: old repos archived, external references updated

## Open decisions to lock before execution

1. Start version: `0.0.0` (placeholder, skip to `0.1.0` for first real release) vs `0.1.0` directly
2. Repo rename strategy: transfer (Option A) vs fresh (Option B)
3. Docs domain: `chippy.github.io/ChipPy/` vs a custom domain
4. Whether to upload final `chumicro-*` packages with deprecation pointers, or abandon silently
5. Whether to rename the CPython-side `.idea/` project identifier or leave IDE workspace-level strings alone
