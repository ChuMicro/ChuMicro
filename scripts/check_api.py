"""Check for API breaking changes and cross-reference with VERSION bumps.

Uses ``griffe check`` to compare the current public API of each changed
library against its last release tag.  Fails when breakages are detected
but the VERSION bump level is insufficient (Decision 0020).

Usage::

    python scripts/check_api.py [--base BASE_REF]

Exits 0 when all changed libraries pass.  Exits 1 on enforcement failure.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Paths within a library that trigger an API check.
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


def _changed_libraries(base_ref: str) -> set[str]:
    """Return names of libraries with release-relevant changes."""
    changed = _changed_files(base_ref)
    libs: set[str] = set()
    for path in changed:
        parts = path.split("/")
        if len(parts) >= 3 and parts[0] == "libraries" and parts[2] in _RELEASE_RELEVANT:
            libs.add(parts[1])
    return libs


def _latest_tag(lib_name: str) -> str | None:
    """Find the latest git tag matching ``<lib_name>-v*``."""
    result = subprocess.run(
        ["git", "tag", "--list", f"{lib_name}-v*", "--sort=-v:refname"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip().splitlines()[0]


def _read_version(lib_name: str) -> str | None:
    """Read the current VERSION file for a library."""
    version_file = ROOT / "libraries" / lib_name / "VERSION"
    if not version_file.exists():
        return None
    return version_file.read_text().strip()


def _parse_version(version: str) -> tuple[int, int, int] | None:
    """Parse a semver string into (major, minor, patch)."""
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def _bump_level(old_version: str, new_version: str) -> str | None:
    """Determine the bump level between two versions."""
    old = _parse_version(old_version)
    new = _parse_version(new_version)
    if old is None or new is None:
        return None
    if new[0] > old[0]:
        return "major"
    if new[1] > old[1]:
        return "minor"
    if new[2] > old[2]:
        return "patch"
    return None


def _find_package_name(lib_name: str) -> str | None:
    """Find the importable package name under a library's src/ directory."""
    src_dir = ROOT / "libraries" / lib_name / "src"
    if not src_dir.is_dir():
        return None
    for child in src_dir.iterdir():
        if child.is_dir() and (child / "__init__.py").exists():
            return child.name
    return None



def _check(base_ref: str) -> int:
    """Run the API breakage check.  Returns exit code."""
    libs = _changed_libraries(base_ref)
    if not libs:
        print("No release-relevant library changes detected.")
        return 0

    overall_ok = True

    for lib_name in sorted(libs):
        tag = _latest_tag(lib_name)
        if tag is None:
            print(f"SKIP: {lib_name} — no previous release tag found.")
            continue

        package_name = _find_package_name(lib_name)
        if package_name is None:
            print(f"SKIP: {lib_name} — no importable package under src/.")
            continue

        new_version = _read_version(lib_name)
        if new_version is None:
            print(f"SKIP: {lib_name} — no VERSION file.")
            continue

        # Extract old version from tag (e.g., timing-v0.1.0 → 0.1.0).
        old_version = tag.split("-v", 1)[1] if "-v" in tag else None
        if old_version is None:
            print(f"SKIP: {lib_name} — cannot parse version from tag {tag}.")
            continue

        bump = _bump_level(old_version, new_version)

        # Run griffe check.
        # Search path must include the library's src/ directory.
        src_dir = str(ROOT / "libraries" / lib_name / "src")
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
            print(f"OK: {lib_name} — no API breakages detected.")
            continue

        # Breakages detected — check bump level.
        major_version = _parse_version(new_version)
        is_pre_1 = major_version is not None and major_version[0] == 0

        if bump == "major":
            print(f"OK: {lib_name} — breakages detected, major bump acknowledged.")
            if griffe_output:
                print(f"     {griffe_output}")
            continue

        if bump == "minor" and is_pre_1:
            print(
                f"OK: {lib_name} — breakages detected, minor bump "
                "sufficient for 0.x (SemVer pre-1.0 semantics)."
            )
            if griffe_output:
                print(f"     {griffe_output}")
            continue

        # Insufficient bump.
        bump_label = bump or "unchanged"
        print(
            f"FAIL: {lib_name} — API breakages detected but VERSION "
            f"bump is only '{bump_label}'."
        )
        if griffe_output:
            for line in griffe_output.splitlines():
                print(f"     {line}")
        if is_pre_1:
            print("     Requires at least a minor bump (0.x library).")
        else:
            print("     Requires a major bump (1.x+ library).")
        overall_ok = False

    return 0 if overall_ok else 1


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Check API breakages against last release tag."
    )
    parser.add_argument(
        "--base",
        default="origin/develop",
        help="Base ref to detect changed libraries (default: origin/develop)",
    )
    args = parser.parse_args(argv)
    return _check(args.base)


if __name__ == "__main__":
    raise SystemExit(main())

