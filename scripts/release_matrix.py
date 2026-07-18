"""Build the release-job matrix from VERSION files.

Walks ``libraries/*/VERSION`` and ``workbench/*/VERSION``, skips parked
libraries (Decision 0107: held out of the publish set), filters by an
optional package list, skips packages whose release tag already exists,
and emits a GitHub Actions matrix JSON describing the packages to release.
Decision 0032 rule 3: workbench packages carry ``kind=workbench`` so the
bundle + validate-mip jobs can filter them out (they ship to PyPI only,
not to circup / mip).

Usage::

    python scripts/release_matrix.py --suffix '-experimental' \
        [--libraries timing,deploy]

Writes ``has_releases``, ``matrix``, ``has_library_releases``, and
``library_matrix`` to ``$GITHUB_OUTPUT`` when set, otherwise to stdout in
the same ``key=value`` format.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from repo_layout import ROOT, is_parked

#: Decision 0038 §6 pre-release floor.  A freshly scaffolded package sits
#: at ``0.0.0`` until its first real version; releasing it on an unrelated
#: bump would ship an empty/placeholder project.  Mirrors the same floor
#: enforced by ``scripts/check_version.py`` (``PRE_RELEASE_FLOOR``).
PRE_RELEASE_FLOOR = "0.0.0"

#: A releasable version is exactly MAJOR.MINOR.PATCH.  Anything else would
#: publish to experimental but could never be promoted (promote_validate.py's
#: tag regex is strict), and the raw string interpolates into workflow shell
#: lines.
_VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


def _read_version(version_file: Path) -> str:
    """Return the trimmed VERSION file contents, validated as MAJOR.MINOR.PATCH.

    Args:
        version_file: Path to a package's VERSION file.
    """
    version = version_file.read_text().strip()
    if not _VERSION_PATTERN.match(version):
        sys.exit(
            f"Malformed VERSION in {version_file}: {version!r} "
            "(expected MAJOR.MINOR.PATCH, e.g. 1.2.3)"
        )
    return version


def _tag_exists(tag: str) -> bool:
    """Return whether the given git ref exists."""
    result = subprocess.run(
        ["git", "rev-parse", f"refs/tags/{tag}"],
        capture_output=True,
        cwd=ROOT,
        check=False,
    )
    return result.returncode == 0


def _collect_entries(
    suffix: str,
    libraries_filter: list[str] | None,
    *,
    include_tagged: bool = False,
) -> list[dict[str, str]]:
    """Return the release-matrix entries for changed packages.

    Args:
        suffix: Tag suffix (e.g. ``"-experimental"``).
        libraries_filter: Package basenames to include (``None`` = all).
            Names that match no discovered package abort the run.
        include_tagged: When True, keep packages whose release tag already
            exists.  Dispatch-only escape hatch for the "tag exists but the
            bundle/publish leg never ran" trap; ``skip-existing`` on the
            PyPI publish step and softprops/action-gh-release's
            release-update behavior make the re-run idempotent.
    """
    entries: list[dict[str, str]] = []
    discovered_names: set[str] = set()
    # support/ packages are host-only infrastructure (Decision 0032 keeps them
    # out of the device bundle, same as workbench). A support package only
    # publishes once it carries a VERSION file — chumicro-test-harness is the
    # first, so the [test] extra libraries declare becomes installable.
    parents: list[tuple[Path, str]] = [
        (ROOT / "libraries", "library"),
        (ROOT / "workbench", "workbench"),
        (ROOT / "support", "support"),
    ]
    for parent_dir, kind in parents:
        if not parent_dir.is_dir():
            continue
        for version_file in sorted(parent_dir.glob("*/VERSION")):
            library_dir = version_file.parent
            library_name = library_dir.name
            discovered_names.add(library_name)

            # Parked libraries (Decision 0107) are held out of the
            # publish set unconditionally — even an explicit --libraries
            # request cannot release one; un-park it (remove the marker)
            # first.  This is the primary release gate, so the exclusion
            # lives here ahead of the name filter.
            if is_parked(library_dir):
                print(f"Library {library_name} is parked — excluding from release matrix.")
                continue

            if libraries_filter is not None and library_name not in libraries_filter:
                continue

            version = _read_version(version_file)

            # Decision 0038 §6: a package sitting at the 0.0.0 pre-release
            # floor is never released — otherwise a freshly scaffolded
            # library would ship on the next unrelated VERSION bump.
            # Mirrors the floor enforced in check_version.py.
            if version == PRE_RELEASE_FLOOR:
                print(
                    f"Library {library_name} is at the {PRE_RELEASE_FLOOR} "
                    "pre-release floor — skipping (Decision 0038 §6)."
                )
                continue

            tag = f"chumicro-{library_name}-v{version}{suffix}"

            if _tag_exists(tag) and not include_tagged:
                print(f"Tag {tag} already exists — skipping {library_name}.")
                continue

            entries.append({
                "library_name": library_name,
                "library_dir": str(library_dir.relative_to(ROOT)),
                "version": version,
                "tag": tag,
                "kind": kind,
            })

    # A typo'd or PyPI-form filter name (mqqt, http-server instead of the
    # directory basename http_server) would otherwise silently no-op:
    # has_releases=false and a green run that published nothing.  Error
    # style mirrors repo_layout.resolve_named_packages().
    if libraries_filter is not None:
        unknown = sorted(set(libraries_filter) - discovered_names)
        if unknown:
            available = ", ".join(sorted(discovered_names))
            sys.exit(
                f"Unknown package(s): {', '.join(unknown)} "
                "(--libraries takes directory basenames, e.g. http_server)\n"
                f"Available: {available}"
            )
    return entries


def _emit_outputs(entries: list[dict[str, str]]) -> str:
    """Build the GitHub Actions output payload as a single newline-joined string."""
    library_entries = [entry for entry in entries if entry["kind"] == "library"]

    lines: list[str] = []
    if entries:
        lines.append("has_releases=true")
        lines.append(f"matrix={json.dumps({'include': entries})}")
    else:
        lines.append("has_releases=false")
        lines.append('matrix={"include":[]}')

    if library_entries:
        lines.append("has_library_releases=true")
        lines.append(f"library_matrix={json.dumps({'include': library_entries})}")
    else:
        lines.append("has_library_releases=false")
        lines.append('library_matrix={"include":[]}')

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Build the release-job matrix from VERSION files.",
    )
    parser.add_argument(
        "--suffix", default="",
        help="Tag suffix (e.g. '-experimental'). Empty for stable.",
    )
    parser.add_argument(
        "--libraries", default="",
        help="Comma-separated package basenames to filter (empty = all).",
    )
    parser.add_argument(
        "--include-tagged", action="store_true",
        help="Include packages whose release tag already exists "
        "(dispatch-only re-run escape hatch; publish is idempotent via "
        "skip-existing + release update).",
    )
    args = parser.parse_args(argv)

    libraries_filter: list[str] | None = None
    if args.libraries:
        libraries_filter = [name.strip() for name in args.libraries.split(",") if name.strip()]

    # Unscoped, --include-tagged would re-include EVERY tagged package,
    # rebuilding them from a drifted tree and overwriting the source-zip
    # assets on their GitHub releases.
    if args.include_tagged and not libraries_filter:
        sys.exit("--include-tagged requires --libraries to scope the re-run")

    entries = _collect_entries(
        args.suffix, libraries_filter, include_tagged=args.include_tagged,
    )
    payload = _emit_outputs(entries)

    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(payload)
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
