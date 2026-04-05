# Decision 0020: API breakage detection with griffe

Status: `accepted`
Date: `2026-04-05`

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
3. Cross-references the result with the VERSION bump level:
   - **Breakages detected + patch bump** → FAIL (needs minor or major bump).
   - **Breakages detected + minor bump** → PASS for `0.x` libraries (SemVer `0.x` semantics: minor = breaking). FAIL for `1.x+` libraries (needs major bump).
   - **Breakages detected + major bump** → PASS (breakage acknowledged).
   - **No breakages** → any bump level is fine.
   - **No previous tag** → skip (first release, nothing to compare against).

### SemVer 0.x semantics

Before `1.0.0`, SemVer allows breaking changes in minor releases. The check enforces this: for `0.x` libraries, a minor bump is sufficient to acknowledge breakages. Once a library reaches `1.0.0`, major bumps are required for breaking changes.

### CI integration

A new `api-check` job in `ci.yml` runs on PRs (like `version-check`). It requires `fetch-depth: 0` to access tags.

The check is also available locally via `python scripts/run.py check-api`.

### Limitations

- `griffe` uses static analysis. It detects structural API changes (removed classes, changed signatures) but not semantic changes (a function returns different values for the same inputs).
- It doesn't cover CLI changes, configuration format changes, or exception type changes.
- For these, human review and good commit messages remain essential.

## Consequences

- Contributors get early feedback on whether their VERSION bump matches their changes.
- Reduces the risk of accidentally publishing breaking changes as patch releases.
- `griffe` becomes an explicit dev dependency (added to `requirements-dev.txt`).
- The check is advisory for `0.x` libraries in the sense that a minor bump satisfies it.

