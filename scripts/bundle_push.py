"""Commit + tag + push staged artifacts to a bundle repository.

Used by release.yml (experimental) and promote.yml (stable) to push the
bundle staging tree into ChuMicro-Bundle-Experimental or ChuMicro-Bundle.
Handles the no-op case (staging identical to current bundle) by exiting 0
without creating a tag.

Usage::

    python scripts/bundle_push.py \
        --bundle-dir .bundle-repo \
        --tag 2026.05.10 \
        --commit-message "Update: timing v1.2.3"

    python scripts/bundle_push.py \
        --bundle-dir .bundle-repo \
        --tag 2026.05.10 \
        --matrix '{"include":[{"library_name":"timing","version":"1.2.3"}]}'

Pass either ``--commit-message`` (single-library promotion path) or
``--matrix`` (multi-package experimental release path).  When ``--matrix``
is given, the commit message is built from its entries.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

_BOT_NAME = "github-actions[bot]"
_BOT_EMAIL = "github-actions[bot]@users.noreply.github.com"


def _build_commit_message_from_matrix(matrix_json: str) -> str:
    """Return ``"Update: foo vX, bar vY"`` from a matrix JSON string."""
    data = json.loads(matrix_json)
    include = data.get("include", [])
    if not include:
        return "Update: (empty matrix)"
    pieces = [f"{entry['library_name']} v{entry['version']}" for entry in include]
    return "Update: " + ", ".join(pieces)


def _run(command: list[str], cwd: Path) -> subprocess.CompletedProcess[bytes]:
    """Run a subprocess and return the completed result, capturing nothing."""
    return subprocess.run(command, cwd=cwd, check=False)


def _has_staged_changes(bundle_dir: Path) -> bool:
    """Return whether ``git diff --cached`` reports any changes."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=bundle_dir, check=False,
    )
    return result.returncode != 0


def push_bundle(bundle_dir: Path, tag: str, commit_message: str) -> int:
    """Configure git, stage everything, commit + tag + push if there are changes."""
    if not bundle_dir.is_dir():
        print(f"::error::bundle-dir {bundle_dir} does not exist.", file=sys.stderr)
        return 1

    _run(["git", "config", "user.name", _BOT_NAME], cwd=bundle_dir)
    _run(["git", "config", "user.email", _BOT_EMAIL], cwd=bundle_dir)
    _run(["git", "add", "-A"], cwd=bundle_dir)

    if not _has_staged_changes(bundle_dir):
        print("No changes to commit.")
        return 0

    commit = _run(["git", "commit", "-m", commit_message], cwd=bundle_dir)
    if commit.returncode != 0:
        print("::error::Bundle commit failed.", file=sys.stderr)
        return commit.returncode

    tag_result = _run(["git", "tag", tag], cwd=bundle_dir)
    if tag_result.returncode != 0:
        print(f"::error::Failed to create tag {tag}.", file=sys.stderr)
        return tag_result.returncode

    push = _run(["git", "push", "origin", "main", tag], cwd=bundle_dir)
    if push.returncode != 0:
        print("::error::Bundle push failed.", file=sys.stderr)
        return push.returncode

    print(f"✓ Pushed {tag} to bundle repository at {bundle_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Commit + tag + push staged artifacts to a bundle repository.",
    )
    parser.add_argument("--bundle-dir", required=True, help="Bundle checkout directory.")
    parser.add_argument("--tag", required=True, help="Date tag for the bundle commit.")

    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--commit-message",
        help="Literal commit message (single-library promotion path).",
    )
    source.add_argument(
        "--matrix",
        help="GitHub Actions matrix JSON; commit message built from its entries.",
    )

    args = parser.parse_args(argv)

    if args.matrix is not None:
        commit_message = _build_commit_message_from_matrix(args.matrix)
    else:
        commit_message = args.commit_message

    return push_bundle(Path(args.bundle_dir), args.tag, commit_message)


if __name__ == "__main__":
    raise SystemExit(main())
