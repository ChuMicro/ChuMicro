"""Check that library VERSION files are updated when release-relevant files change.

Used in CI to enforce Decision 0002: PRs that change a library's ``src/``
or ``pyproject.toml`` must also bump the library's ``VERSION`` file.

Usage::

    python scripts/check_version.py [--base BASE_REF]

Exits 0 when all changed libraries have a VERSION update (or when only
non-release-relevant files changed).  Exits 1 when enforcement fails.
"""

from __future__ import annotations

import subprocess

from discovery import RELEASE_RELEVANT, ROOT, changed_files


def _has_release_tag(library_name: str) -> bool:
    """Return True if *library_name* has at least one release tag (e.g. ``timing-v0.1.0``)."""
    result = subprocess.run(
        ["git", "tag", "-l", f"{library_name}-v*"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    return bool(result.stdout.strip())


def _check(base_ref: str) -> int:
    """Run the VERSION enforcement check.  Returns exit code."""
    changed = changed_files(base_ref)
    if not changed:
        print("No changed files detected.")
        return 0

    # Group changed files by library.
    # Libraries live at libraries/<name>/...
    libraries_needing_bump: set[str] = set()
    libraries_with_bump: set[str] = set()

    for path in changed:
        parts = path.split("/")
        if len(parts) < 3 or parts[0] != "libraries":
            continue

        library_name = parts[1]

        # Check if VERSION itself was changed.  The len==3 guard ensures
        # we only match the root-level VERSION file (libraries/<name>/VERSION)
        # and not a hypothetical nested file like libraries/<name>/src/VERSION.
        if parts[2] == "VERSION" and len(parts) == 3:
            libraries_with_bump.add(library_name)
            continue

        # Check if the changed path is release-relevant.
        # RELEASE_RELEVANT = {"src", "pyproject.toml"}.  For "src",
        # parts[2] matches the directory name so any file under src/
        # qualifies (len(parts) >= 3 already holds).  For "pyproject.toml",
        # it matches the filename directly at the library root.
        if parts[2] in RELEASE_RELEVANT:
            libraries_needing_bump.add(library_name)

    missing = libraries_needing_bump - libraries_with_bump
    if missing:
        for library_name in sorted(missing):
            print(
                f"FAIL: libraries/{library_name}/ has release-relevant changes "
                "but VERSION was not updated."
            )
        print()
        print("Update the VERSION file with a semantic version bump (Decision 0002).")
        print("If only internal changes occurred (no API/behavior change), a patch bump suffices.")
        return 1

    if libraries_needing_bump:
        for library_name in sorted(libraries_needing_bump):
            print(f"OK: libraries/{library_name}/ — VERSION updated.")
    else:
        print("No release-relevant library changes detected.")

    # Warn about new libraries that have never been released.
    # PyPI projects must be created manually before the first publish.
    all_changed_libraries = libraries_needing_bump | libraries_with_bump
    for library_name in sorted(all_changed_libraries):
        if not _has_release_tag(library_name):
            print(
                f"NOTE: libraries/{library_name}/ has no release tags — "
                "this appears to be a new library.  Before merging, "
                "ask @chux.maker to create the PyPI project "
                f"(chumicro-{library_name}) so the release workflow can publish."
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Check VERSION file enforcement.")
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base ref to diff against (default: origin/main)",
    )
    args = parser.parse_args(argv)
    return _check(args.base)


if __name__ == "__main__":
    raise SystemExit(main())
