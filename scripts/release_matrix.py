"""Build the release-job matrix from VERSION files.

Walks ``libraries/*/VERSION`` and ``workbench/*/VERSION``, filters by an
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
import subprocess
import sys
from pathlib import Path

from repo_layout import ROOT


def _read_version(version_file: Path) -> str:
    """Return the trimmed VERSION file contents."""
    return version_file.read_text().strip()


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
) -> list[dict[str, str]]:
    """Return the release-matrix entries for changed packages."""
    entries: list[dict[str, str]] = []
    parents: list[tuple[Path, str]] = [
        (ROOT / "libraries", "library"),
        (ROOT / "workbench", "workbench"),
    ]
    for parent_dir, kind in parents:
        if not parent_dir.is_dir():
            continue
        for version_file in sorted(parent_dir.glob("*/VERSION")):
            library_dir = version_file.parent
            library_name = library_dir.name

            if libraries_filter is not None and library_name not in libraries_filter:
                continue

            version = _read_version(version_file)
            tag = f"chumicro-{library_name}-v{version}{suffix}"

            if _tag_exists(tag):
                print(f"Tag {tag} already exists — skipping {library_name}.")
                continue

            entries.append({
                "library_name": library_name,
                "library_dir": str(library_dir.relative_to(ROOT)),
                "version": version,
                "tag": tag,
                "kind": kind,
            })
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
    args = parser.parse_args(argv)

    libraries_filter: list[str] | None = None
    if args.libraries:
        libraries_filter = [name.strip() for name in args.libraries.split(",") if name.strip()]

    entries = _collect_entries(args.suffix, libraries_filter)
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
