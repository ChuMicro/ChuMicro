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

import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from repo_layout import (
    ROOT,
    changed_publishable_packages,
    find_package_dir,
    read_version,
    release_tags,
)

#: Cap on concurrent ``griffe check`` invocations — each is an
#: independent subprocess against a different package + tag, no
#: shared state.  Mirrors ``scripts/run.py``'s
#: ``_DEFAULT_PACKAGE_PARALLEL_WORKERS`` and respects the same
#: ``CHUMICRO_PARALLEL_PACKAGES`` env override so CI tunes once.
_DEFAULT_GRIFFE_PARALLEL_WORKERS = 4


def _resolve_parallel_workers() -> int:
    raw = os.environ.get("CHUMICRO_PARALLEL_PACKAGES")
    if not raw:
        return _DEFAULT_GRIFFE_PARALLEL_WORKERS
    try:
        return max(1, int(raw))
    except ValueError:
        return _DEFAULT_GRIFFE_PARALLEL_WORKERS


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


def _check_one_package(
    parent_dir: str, package_basename: str,
) -> tuple[bool, list[str]]:
    """Check a single package; return ``(ok, output_lines)``.

    Pure-function shape so the caller can fan out across a thread
    pool without worrying about shared state — every parameter
    derived from the args, every output collected into the returned
    list.  ``ok`` is ``False`` when breakages exist and the VERSION
    bump level is insufficient.

    Args:
        parent_dir: ``"libraries"`` or ``"workbench"``.
        package_basename: e.g. ``"timing"`` or ``"pytest-device"``.
    """
    package_label = f"{parent_dir}/{package_basename}"
    package_root = ROOT / parent_dir / package_basename
    output_lines: list[str] = []

    tags = release_tags(package_basename)
    if not tags:
        output_lines.append(f"SKIP: {package_label} — no previous release tag found.")
        return True, output_lines
    tag = tags[0]

    package_dir = find_package_dir(package_root)
    if package_dir is None:
        output_lines.append(
            f"SKIP: {package_label} — no importable package under src/.",
        )
        return True, output_lines
    package_name = package_dir.name

    new_version = read_version(package_root)
    if new_version is None:
        output_lines.append(f"SKIP: {package_label} — no VERSION file.")
        return True, output_lines

    # Extract old version from tag (e.g., chumicro-timing-v0.1.0 → 0.1.0).
    old_version = tag.split("-v", 1)[1] if "-v" in tag else None
    if old_version is None:
        output_lines.append(
            f"SKIP: {package_label} — cannot parse version from tag {tag}.",
        )
        return True, output_lines

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
        output_lines.append(f"OK: {package_label} — no API breakages detected.")
        return True, output_lines

    # Breakages detected — check whether the VERSION bump level is
    # sufficient.  SemVer pre-1.0 semantics (major == 0) allow
    # breaking changes on a minor bump; post-1.0 requires a major
    # bump.  See Decision 0020.
    major_version = _parse_version(new_version)
    is_pre_1 = major_version is not None and major_version[0] == 0

    if bump == "major":
        output_lines.append(
            f"OK: {package_label} — breakages detected, major bump acknowledged.",
        )
        if griffe_output:
            output_lines.append(f"     {griffe_output}")
        return True, output_lines

    if bump == "minor" and is_pre_1:
        output_lines.append(
            f"OK: {package_label} — breakages detected, minor bump "
            "sufficient for 0.x (SemVer pre-1.0 semantics).",
        )
        if griffe_output:
            output_lines.append(f"     {griffe_output}")
        return True, output_lines

    # Insufficient bump.
    bump_label = bump or "unchanged"
    output_lines.append(
        f"FAIL: {package_label} — API breakages detected but VERSION "
        f"bump is only '{bump_label}'.",
    )
    if griffe_output:
        for line in griffe_output.splitlines():
            output_lines.append(f"     {line}")
    if is_pre_1:
        output_lines.append("     Requires at least a minor bump (0.x package).")
    else:
        output_lines.append("     Requires a major bump (1.x+ package).")
    return False, output_lines


def _check(base_reference: str) -> int:
    """Run the API breakage check.

    Each per-package griffe invocation is independent (different
    package, different tag, no shared state), so we fan out across
    :data:`_DEFAULT_GRIFFE_PARALLEL_WORKERS` threads.  Output is
    collected per package and replayed in alphabetical (submission)
    order so the on-screen log stays deterministic regardless of
    which subprocess finishes first.

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

    sorted_packages = sorted(packages)
    workers = max(1, min(_resolve_parallel_workers(), len(sorted_packages)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(_check_one_package, parent_dir, basename)
            for parent_dir, basename in sorted_packages
        ]
        results = [future.result() for future in futures]

    overall_ok = True
    for ok, lines in results:
        for line in lines:
            print(line)
        if not ok:
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
