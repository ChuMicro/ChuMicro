# Decision 0002: Per-library version file strategy

Status: `accepted`
Date: `2026-03-31`

## Context

The repository is a mono-workspace, but libraries are published individually. A repo-level label does not clearly identify which library version should change, and it leaves the actual version edit disconnected from the code change that requires it.

## Decision

Each publishable library owns a checked-in `VERSION` file in its library root. That file is the canonical published version for the library.

When a pull request changes a library in a way that affects its released surface area, the same pull request must update that library's `VERSION` file with the smallest correct semantic-version bump.

PR automation should validate that release-relevant library changes do not merge without the corresponding `VERSION` file update, and release automation should read or validate versions from those files.

## Consequences

- version intent lives next to the library that is actually changing
- PR review includes an explicit, concrete version edit instead of inferred label intent
- future workflows should fail clearly when a changed library is missing the expected `VERSION` file update
- `pyproject.toml` uses setuptools `dynamic` version to read directly from `VERSION` — there is no duplicate to keep in sync
- libraries should not maintain a separate `__version__` attribute in source code; consumers on CPython can use `importlib.metadata.version()` if needed at runtime


