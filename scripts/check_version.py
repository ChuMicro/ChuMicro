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
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Paths within a library that require a VERSION bump when changed.
_RELEASE_RELEVANT = {"src", "pyproject.toml"}


def _changed_files(base_ref: str) -> list[str]:
    """Return files changed between *base_ref* and HEAD."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        # Fallback: diff against base_ref directly (shallow clones).
        result = subprocess.run(
            ["git", "diff", "--name-only", base_ref, "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
    if result.returncode != 0:
        print(f"git diff failed: {result.stderr.strip()}")
        sys.exit(2)
    return [line for line in result.stdout.strip().splitlines() if line]


def _check(base_ref: str) -> int:
    """Run the VERSION enforcement check.  Returns exit code."""
    changed = _changed_files(base_ref)
    if not changed:
        print("No changed files detected.")
        return 0

    # Group changed files by library.
    # Libraries live at libraries/<name>/...
    libs_needing_bump: set[str] = set()
    libs_with_bump: set[str] = set()

    for path in changed:
        parts = path.split("/")
        if len(parts) < 3 or parts[0] != "libraries":
            continue

        lib_name = parts[1]

        # Check if VERSION itself was changed.
        if parts[2] == "VERSION" and len(parts) == 3:
            libs_with_bump.add(lib_name)
            continue

        # Check if the changed path is release-relevant.
        # src/anything or pyproject.toml at the library root.
        if parts[2] in _RELEASE_RELEVANT:
            libs_needing_bump.add(lib_name)

    missing = libs_needing_bump - libs_with_bump
    if missing:
        for lib in sorted(missing):
            print(
                f"FAIL: libraries/{lib}/ has release-relevant changes "
                "but VERSION was not updated."
            )
        print()
        print("Update the VERSION file with a semantic version bump (Decision 0002).")
        print("If only internal changes occurred (no API/behavior change), a patch bump suffices.")
        return 1

    if libs_needing_bump:
        for lib in sorted(libs_needing_bump):
            print(f"OK: libraries/{lib}/ — VERSION updated.")
    else:
        print("No release-relevant library changes detected.")

    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Check VERSION file enforcement.")
    parser.add_argument(
        "--base",
        default="origin/develop",
        help="Base ref to diff against (default: origin/develop)",
    )
    args = parser.parse_args(argv)
    return _check(args.base)


if __name__ == "__main__":
    raise SystemExit(main())

