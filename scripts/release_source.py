"""Download + unpack a frozen library source archive from a GitHub Release.

Used by promote.yml to replay the experimental source onto main's
working tree before building the stable package.  The archive carries
``src/``, ``pyproject.toml``, ``VERSION``, and ``README.md`` — every
file the build needs.

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
    """Remove the existing package source under ``library_dir`` and unpack ``archive_path``."""
    src_dir = library_dir / "src"
    if src_dir.is_dir():
        shutil.rmtree(src_dir)
    for filename in ("pyproject.toml", "VERSION", "README.md"):
        target = library_dir / filename
        if target.is_file():
            target.unlink()
    with zipfile.ZipFile(archive_path) as archive:
        archive.extractall(library_dir)


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
