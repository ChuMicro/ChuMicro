"""Check for API breaking changes and cross-reference with VERSION bumps.

Uses ``griffe check`` to compare the current public API of each changed
publishable package against its last release tag.  Fails when breakages
are detected but the VERSION bump level is insufficient (Decision 0020).
Covers both ``libraries/`` and ``workbench/`` (Decision 0032 — same
release lifecycle, same pre-merge gate).

Usage::

    python scripts/check_api.py [--base BASE_REF]

Exits 0 when all changed packages pass.  Exits 1 on enforcement failure.
"""

from __future__ import annotations

import re
import subprocess
import sys

from workspace import (
    ROOT,
    changed_publishable_packages,
    find_package_dir,
    read_version,
    release_tags,
)


def _parse_version(version: str) -> tuple[int, int, int] | None:
    """Parse a semver string into (major, minor, patch).

    Args:
        version: Semantic version string (e.g. ``"1.2.3"``).
    """
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _bump_level(old_version: str, new_version: str) -> str | None:
    """Determine the bump level between two versions.

    Args:
        old_version: Previous version string.
        new_version: Current version string.

    Returns:
        ``"major"``, ``"minor"``, ``"patch"``, or ``None`` if unchanged.
    """
    old_parsed = _parse_version(old_version)
    new_parsed = _parse_version(new_version)
    if old_parsed is None or new_parsed is None:
        return None
    if new_parsed[0] > old_parsed[0]:
        return "major"
    if new_parsed[1] > old_parsed[1]:
        return "minor"
    if new_parsed[2] > old_parsed[2]:
        return "patch"
    return None


def _check(base_reference: str) -> int:
    """Run the API breakage check.

    Args:
        base_reference: Git ref to detect changed packages against.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    try:
        packages = changed_publishable_packages(base_reference)
    except RuntimeError as error:
        print(error)
        return 2

    if not packages:
        print("No release-relevant package changes detected.")
        return 0

    overall_ok = True

    for parent_dir, package_basename in sorted(packages):
        package_label = f"{parent_dir}/{package_basename}"
        package_root = ROOT / parent_dir / package_basename

        tags = release_tags(package_basename)
        if not tags:
            print(f"SKIP: {package_label} — no previous release tag found.")
            continue
        tag = tags[0]

        package_dir = find_package_dir(package_root)
        if package_dir is None:
            print(f"SKIP: {package_label} — no importable package under src/.")
            continue
        package_name = package_dir.name

        new_version = read_version(package_root)
        if new_version is None:
            print(f"SKIP: {package_label} — no VERSION file.")
            continue

        # Extract old version from tag (e.g., chumicro-timing-v0.1.0 → 0.1.0).
        old_version = tag.split("-v", 1)[1] if "-v" in tag else None
        if old_version is None:
            print(f"SKIP: {package_label} — cannot parse version from tag {tag}.")
            continue

        bump = _bump_level(old_version, new_version)

        # Run griffe to compare the current public API against the tagged
        # release.  griffe parses Python source statically and detects
        # removed/renamed symbols, changed signatures, etc.
        # --search must be a path *relative to cwd*: griffe 2.x silently
        # ignores absolute --search paths (resolves nothing, exits 0
        # with no output), which previously made this gate a no-op.
        # cwd=ROOT means the relative path resolves correctly for both
        # libraries/<name>/src and workbench/<name>/src.
        # stdout and stderr are both captured because griffe emits
        # breakage details on different streams depending on version.
        # A non-zero exit code indicates at least one breaking change.
        src_dir = str((package_root / "src").relative_to(ROOT))
        result = subprocess.run(
            [
                sys.executable, "-m", "griffe", "check",
                package_name,
                "--against", tag,
                "--search", src_dir,
            ],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        griffe_output = (result.stdout + result.stderr).strip()
        has_breakages = result.returncode != 0

        if not has_breakages:
            print(f"OK: {package_label} — no API breakages detected.")
            continue

        # Breakages detected — check whether the VERSION bump level is
        # sufficient.  SemVer pre-1.0 semantics (major == 0) allow
        # breaking changes on a minor bump; post-1.0 requires a major
        # bump.  See Decision 0020.
        major_version = _parse_version(new_version)
        is_pre_1 = major_version is not None and major_version[0] == 0

        if bump == "major":
            print(f"OK: {package_label} — breakages detected, major bump acknowledged.")
            if griffe_output:
                print(f"     {griffe_output}")
            continue

        if bump == "minor" and is_pre_1:
            print(
                f"OK: {package_label} — breakages detected, minor bump "
                "sufficient for 0.x (SemVer pre-1.0 semantics)."
            )
            if griffe_output:
                print(f"     {griffe_output}")
            continue

        # Insufficient bump.
        bump_label = bump or "unchanged"
        print(
            f"FAIL: {package_label} — API breakages detected but VERSION "
            f"bump is only '{bump_label}'."
        )
        if griffe_output:
            for line in griffe_output.splitlines():
                print(f"     {line}")
        if is_pre_1:
            print("     Requires at least a minor bump (0.x package).")
        else:
            print("     Requires a major bump (1.x+ package).")
        overall_ok = False

    return 0 if overall_ok else 1


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv``).
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Check API breakages against last release tag."
    )
    parser.add_argument(
        "--base",
        default="origin/main",
        help="Base ref to detect changed packages (default: origin/main)",
    )
    args = parser.parse_args(argv)
    return _check(args.base)


if __name__ == "__main__":
    raise SystemExit(main())
