"""Download + unpack a frozen library source archive from a GitHub Release.

Used by promote.yml to replay the experimental source onto main's
working tree before building the stable package.  The archive is a
``git archive`` snapshot of the library's full tracked tree (``src/``,
``pyproject.toml``, ``VERSION``, ``README.md``, plus the ``tests/``,
``examples/``, and ``docs/`` trees the sdist ships), so the promoted
build carries no main-current content.

Usage::

    GH_TOKEN=... python scripts/release_source.py \
        --tag chumicro-timing-v0.3.0-experimental \
        --source-zip chumicro-timing-v0.3.0-source.zip \
        --library-dir libraries/timing

Requires the ``gh`` CLI on PATH.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from repo_layout import ROOT


def _download_archive(tag: str, source_zip: str, target_dir: Path) -> Path:
    """Download ``source_zip`` from release ``tag`` into ``target_dir``."""
    target_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "gh", "release", "download", tag,
            "--pattern", source_zip,
            "--dir", str(target_dir),
        ],
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to download {source_zip} from release {tag}.")
    archive_path = target_dir / source_zip
    if not archive_path.is_file():
        raise RuntimeError(f"Downloaded archive not found at {archive_path}.")
    return archive_path


def _replace_package_source(library_dir: Path, archive_path: Path) -> None:
    """Replace ``library_dir``'s entire content with ``archive_path``'s.

    Everything under the package directory is removed first: the sdist
    ships ``tests/``, ``examples/``, and ``docs/`` alongside ``src/``,
    so extracting over a partially-cleared checkout would mix frozen
    source with whatever main carries at promotion time.
    """
    for child in library_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(library_dir)
    for required in ("pyproject.toml", "VERSION", "src"):
        if not (library_dir / required).exists():
            raise RuntimeError(
                f"Archive {archive_path.name} is missing {required!r} — it "
                "predates the full-tree archive format and cannot be promoted "
                "safely.  Re-release the experimental version to mint a "
                "full-tree archive."
            )


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Download + unpack a release source archive over a package directory.",
    )
    parser.add_argument("--tag", required=True, help="GitHub Release tag to download from.")
    parser.add_argument("--source-zip", required=True, help="Archive filename in the release.")
    parser.add_argument(
        "--library-dir", required=True,
        help="Package directory to replay the archive over (relative to repo root).",
    )
    args = parser.parse_args(argv)

    library_dir = ROOT / args.library_dir
    if not library_dir.is_dir():
        print(f"::error::library-dir {args.library_dir} does not exist.", file=sys.stderr)
        return 1

    with tempfile.TemporaryDirectory(prefix="release-source-") as tmpdir:
        try:
            archive_path = _download_archive(args.tag, args.source_zip, Path(tmpdir))
            _replace_package_source(library_dir, archive_path)
        except (RuntimeError, zipfile.BadZipFile) as error:
            print(f"::error::{error}", file=sys.stderr)
            return 1

    print(f"✓ Replayed {args.source_zip} onto {args.library_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
