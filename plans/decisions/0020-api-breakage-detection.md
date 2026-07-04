# Decision 0020: API breakage detection with griffe

Status: `accepted`
Date: `2026-04-05`
Summary: `griffe check` detects per-library API breakages in CI; pre-publication an under-bumped break is warn-only (Decision 0092), becoming a hard fail at first publication.
Related: Decision 0002 (per-library version files), Decision 0092 (no backwards compat before publication)

## Context

Decision 0002 requires that library changes affecting the released surface area include a VERSION bump. But it doesn't verify that the bump *level* matches the nature of the change. A contributor could introduce a breaking API change with only a patch bump, or add new features with a major bump when minor would suffice.

Manual review catches this sometimes. We need automated detection.

## Decision

### Tool: griffe check

`griffe` is already an indirect dependency via `mkdocstrings`. It provides `griffe check <package>` which compares the current public API against a git ref and reports breakages (removals, signature changes, type changes).

### Integration

A new script `scripts/check_api.py` runs for each library with release-relevant changes:

1. Finds the latest git tag matching `<lib_name>-v*` for the library.
2. Runs `griffe check` comparing current source against that tag.
3. Classifies the result against the VERSION bump level:
   - **Breakages detected + major bump** → PASS (breakage acknowledged).
   - **Breakages detected + minor bump** → PASS for `0.x` libraries (SemVer `0.x` semantics: minor = breaking); insufficient for `1.x+` libraries (needs major).
   - **Breakages detected + insufficient bump** (patch on any library, or minor on a `1.x+` library) → the publication-gated outcome below.
   - **No breakages** → any bump level is fine.
   - **No previous tag** → skip (first release, nothing to compare against).

### Warn-only until first publication

Nothing in this workspace has been published, and Decision 0092 makes breaking changes free before first publication (break and migrate every consumer in one commit). So an under-bumped breakage is *reported, not blocked*: `check_api.py` prints a WARNING naming the break and the bump it would require at publication, then exits 0. The griffe detection is untouched — this is a reporting-level demotion, not a weakened detector.

A single module-level `PUBLISHED` flag in `check_api.py` gates this. While `False`, the insufficient-bump case warns and passes. Flipping it to `True` at first publication restores the hard failure: an insufficient bump for a detected breakage exits non-zero and reddens the required CI check. Decision 0092 self-retires at that point, and a real SemVer/deprecation policy takes over.

### SemVer 0.x semantics

Before `1.0.0`, SemVer allows breaking changes in minor releases. The thresholds reflect this: for `0.x` libraries a minor bump acknowledges breakages and a patch bump does not; once a library reaches `1.0.0`, major bumps are required for breaking changes. Pre-publication these thresholds are reported as warnings rather than enforced (see above); they become enforcing once `PUBLISHED` is set.

### CI integration

A new `api-check` job in `ci.yml` runs on PRs (like `version-check`). It requires `fetch-depth: 0` to access tags.

The check is also available locally via `python scripts/run.py check-api`.

### Limitations

- `griffe` uses static analysis. It detects structural API changes (removed classes, changed signatures) but not semantic changes (a function returns different values for the same inputs).
- It doesn't cover CLI changes, configuration format changes, or exception type changes.
- For these, human review and good commit messages remain essential.

## Consequences

- Contributors get early feedback on whether their VERSION bump matches their changes.
- Reduces the risk of accidentally publishing breaking changes as patch releases (once `PUBLISHED` re-arms the gate at first publication).
- `griffe` becomes an explicit dev dependency (added to `requirements-dev.txt`).
- Pre-publication the check is advisory throughout — warn-only per Decision 0092 — so no breakage can redden CI; at publication it becomes enforcing, and even then a minor bump satisfies it for `0.x` libraries.
