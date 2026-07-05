# Decision 0107: parked libraries

Status: `accepted`
Date: `2026-07-05`
Summary: A `PARKED` marker file holds a library out of the publish set (release, bundle, channel, landing page) while it stays in-tree and tested; `chumicro_logging` is the first parked library.
Related: 0002 (per-library VERSION files), 0032 (publishable roots), 0038 §6 (pre-release floor), 0092 (no backwards-compat before publication), 0096 (remove events — the delete verdict this softens)

## Context

`chumicro_logging` audits clean but has zero adopters in either repo as of the
2026-07-04 fleet audit.  Decision 0096 deleted `events` under the same
zero-consumer finding; logging instead earns a softer verdict — keep it in-tree
and maintained, but stop advertising and shipping it until a real consumer shows
up.  The publish set was until now implicit: a library qualifies when it has both
`VERSION` and `pyproject.toml` at its root, a gate re-enumerated in
`release_matrix`, `find_publishable_packages`, `libraries_channel`,
`bundle_manager`, the landing page, and mip validation.  There was no way to say
"in the tree but not in the publish set."  The pre-release floor (Decision 0038 §6,
`VERSION == 0.0.0`) does not apply — logging is at `0.5.1` — and overloading `0.0.0`
to mean "parked" would conflate two unrelated states.

## Decision

A library is **parked** by placing a `PARKED` marker file at its root.  The file's
contents are a free-text note recording why and when it was parked; un-parking is
deleting the file.  One shared predicate, `repo_layout.is_parked(library_dir)`,
owns the marker check (with `read_parked_reason` for the note); every consumer
routes through it rather than reading the file or hardcoding a library name.

Parking excludes a library from the **publish set** only:

- **Skips it** — `release_matrix` (the primary gate: no release tag, so no PyPI
  publish and no bundle staging, even under an explicit `--libraries` request),
  `find_publishable_packages()` (so `run.py build` won't build it),
  `libraries_channel`, `bundle_manager` README metadata, `generate_landing_page`,
  and mip-install validation (nothing in the bundle to validate against).
- **Still includes it** — all test/lint/docs discovery (`discover_package_dirs`,
  `discover_library_dirs`, `discover_ruff_paths`, functional/cross-runtime/
  on-device suites) and editable install (`find_publishable_packages(include_parked=True)`).
  Parked ≠ unmaintained: the library stays green in-tree.
- **Unchanged** — the pre-merge VERSION (`check_version`) and API (`check_api`)
  gates keep applying.  Parking does not exempt a library from Decision 0002's
  bump discipline; keeping VERSION accurate is what keeps it release-ready, so
  un-parking is one step rather than a version-archaeology exercise.

`chumicro_logging` is parked as the first instance.

## Consequences

The VERSION + `pyproject.toml` gate keeps meaning "could be published"; parking is
the one explicit subtraction on top of it, checked in one place.  A parked library
costs a test lane and a docs build but no bundle/PyPI/landing-page surface, and its
absence there is self-documenting (the marker names the reason).  Adding a real
consumer is un-parking: delete the marker and the next release picks the library
up.  Because the check is a shared predicate keyed on a file, no script carries a
library name — the mechanism generalizes to any future park without further edits.
