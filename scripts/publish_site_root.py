"""Publish the host-root site into a clone of the site repository.

The site repository is build output, the same way ``gh-pages`` is: this
rebuilds its whole tree from :mod:`generate_site_root`, commits when
anything moved, and pushes.  Wiping first is what retires a file whose
name changed, which matters for the IndexNow key: a stale key left
behind would keep answering after the current one replaced it.

Usage (from repository root)::

    git clone git@github.com:ChuMicro/chumicro.github.io.git .site-repo
    python scripts/publish_site_root.py --clone-dir .site-repo --push
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from generate_site_root import build


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run *command* in *cwd*, raising on a non-zero status."""
    return subprocess.run(command, cwd=cwd, check=True, capture_output=True, text=True)


def _clear_tree(clone_dir: Path) -> None:
    """Remove every tracked path except ``.git`` from *clone_dir*."""
    for entry in clone_dir.iterdir():
        if entry.name == ".git":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()


def _has_staged_changes(clone_dir: Path) -> bool:
    """Return whether the index differs from HEAD."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"], cwd=clone_dir, check=False,
    )
    return result.returncode != 0


def publish(clone_dir: Path, *, push: bool, message: str) -> int:
    """Rebuild *clone_dir* from the generator, then commit and push.

    Args:
        clone_dir: An existing clone of the site repository.
        push: Whether to push after committing.  ``False`` stages and
            commits only, which is what a dry run wants.
        message: Commit message for the publish commit.

    Returns:
        Process exit status: 0 on success, including the no-change case.
    """
    if not (clone_dir / ".git").is_dir():
        print(f"ERROR: {clone_dir} is not a git clone")
        return 1

    _clear_tree(clone_dir)
    written = build(clone_dir)
    print(f"Staged {len(written)} files into {clone_dir}")

    _run(["git", "add", "-A"], clone_dir)
    if not _has_staged_changes(clone_dir):
        print("Host-root site unchanged; nothing to publish")
        return 0

    _run(["git", "commit", "-m", message], clone_dir)
    if push:
        _run(["git", "push"], clone_dir)
        print("Pushed host-root site")
    else:
        print("Committed host-root site (not pushed)")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Publish the host-root site.

    Args:
        argv: Command-line arguments, or ``None`` to read ``sys.argv``.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--clone-dir", type=Path, required=True,
        help="existing clone of the site repository",
    )
    parser.add_argument(
        "--push", action="store_true", help="push after committing",
    )
    parser.add_argument(
        "--message", default="Rebuild host-root site",
        help="commit message for the publish commit",
    )
    args = parser.parse_args(argv)
    return publish(args.clone_dir, push=args.push, message=args.message)


if __name__ == "__main__":
    raise SystemExit(main())
