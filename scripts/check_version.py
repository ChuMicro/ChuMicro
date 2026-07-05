"""Check that package VERSION files are updated when release-relevant files change.

Used in CI to enforce Decision 0002: PRs that change a publishable
package's ``src/`` or ``pyproject.toml`` must also bump the package's
``VERSION`` file.  Covers both ``libraries/`` (device libraries) and
``workbench/`` (host-only tools, per Decision 0032
§workbench-release-lifecycle).

Decision 0038 §6 carves out ``0.0.0`` as a pre-release floor: while
a package's ``VERSION`` reads ``0.0.0``, this gate stays quiet.  The
intent is to let pre-release packages absorb churn without nuisance
"bump VERSION" failures.  The gate kicks in the moment VERSION crosses
to anything non-zero.

Parked libraries (Decision 0107) are deliberately *not* exempt.  Parking
holds a library out of the publish set, not out of maintenance: it stays
in-tree and keeps taking fixes, and the discipline that VERSION track
``src/`` / ``pyproject.toml`` changes is exactly what keeps it
release-ready, so un-parking (removing the marker) is a one-step action
rather than a version-archaeology exercise.  Enforcement here keys off
changed file paths under the publishable roots, so a parked library's
edits still trip the gate with no special-casing — this comment records
that the coverage is intended, not accidental.

Usage::

    python scripts/check_version.py [--base BASE_REF]

Exits 0 when all changed packages have a VERSION update (or when only
non-release-relevant files changed, or when the package is at the
``0.0.0`` pre-release floor).  Exits 1 when enforcement fails.
"""

from __future__ import annotations

from repo_layout import (
    PUBLISHABLE_ROOTS,
    RELEASE_RELEVANT,
    ROOT,
    changed_files,
    read_version,
    release_tags,
)

PRE_RELEASE_FLOOR = "0.0.0"


def _check(base_reference: str) -> int:
    """Run the VERSION enforcement check.

    Args:
        base_reference: Git ref to diff against.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        changed = changed_files(base_reference)
    except RuntimeError as error:
        print(error)
        return 2

    if not changed:
        print("No changed files detected.")
        return 0

    # Group changed files by package.  Publishable packages live at
    # libraries/<name>/... and workbench/<name>/... (Decision 0032: the
    # workbench tree follows the same release lifecycle as libraries
    # minus bundle staging, so both roots get the same gate).
    packages_needing_bump: set[tuple[str, str]] = set()
    packages_with_bump: set[tuple[str, str]] = set()

    for path in changed:
        parts = path.split("/")
        if len(parts) < 3 or parts[0] not in PUBLISHABLE_ROOTS:
            continue

        package_id = (parts[0], parts[1])

        # Check if VERSION itself was changed.  The len==3 guard ensures
        # we only match the root-level VERSION file (<root>/<name>/VERSION)
        # and not a hypothetical nested file like <root>/<name>/src/VERSION.
        if parts[2] == "VERSION" and len(parts) == 3:
            packages_with_bump.add(package_id)
            continue

        # Check if the changed path is release-relevant.
        # RELEASE_RELEVANT = {"src", "pyproject.toml"}.  For "src",
        # parts[2] matches the directory name so any file under src/
        # qualifies (len(parts) >= 3 already holds).  For "pyproject.toml",
        # it matches the filename directly at the package root.
        if parts[2] in RELEASE_RELEVANT:
            packages_needing_bump.add(package_id)

    # Decision 0038 §6: while a package's VERSION reads 0.0.0, the
    # gate stays quiet.  Pre-release packages absorb churn without
    # nuisance "bump VERSION" failures.
    pre_release_packages: set[tuple[str, str]] = set()
    for parent_dir, package_name in packages_needing_bump:
        package_dir = ROOT / parent_dir / package_name
        if read_version(package_dir) == PRE_RELEASE_FLOOR:
            pre_release_packages.add((parent_dir, package_name))

    missing = packages_needing_bump - packages_with_bump - pre_release_packages
    if missing:
        for parent_dir, package_name in sorted(missing):
            print(
                f"FAIL: {parent_dir}/{package_name}/ has release-relevant changes "
                "but VERSION was not updated."
            )
        print()
        print("Update the VERSION file with a semantic version bump (Decision 0002).")
        print("If only internal changes occurred (no API/behavior change), a patch bump suffices.")
        return 1

    if pre_release_packages:
        for parent_dir, package_name in sorted(pre_release_packages):
            print(
                f"PRE-RELEASE: {parent_dir}/{package_name}/ at "
                f"{PRE_RELEASE_FLOOR} — VERSION bump not required "
                "(Decision 0038 §6)."
            )

    if packages_needing_bump:
        for parent_dir, package_name in sorted(packages_needing_bump):
            print(f"OK: {parent_dir}/{package_name}/ — VERSION updated.")
    else:
        print("No release-relevant package changes detected.")

    # Warn about new packages that have never been released.
    # PyPI projects must be created manually before the first publish.
    all_changed_packages = packages_needing_bump | packages_with_bump
    for parent_dir, package_name in sorted(all_changed_packages):
        if not release_tags(package_name):
            print(
                f"NOTE: {parent_dir}/{package_name}/ has no release tags — "
                "this appears to be a new package.  Before merging, "
                "ask @chux.maker to create the PyPI project "
                f"(chumicro-{package_name}) so the release workflow can publish."
            )

    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv``).
    """
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
