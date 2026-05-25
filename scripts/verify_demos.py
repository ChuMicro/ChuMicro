"""Compile-check the ``demos/`` tree.

Each ``demos/<name>/`` directory holds a self-contained demo with
``app.py`` (deployed to a board) and ``driver.py`` (host
orchestration).  The driver scripts reach across the mono-repo into
workbench packages and fixtures, so a rename in any of those would
silently break a demo until somebody ran it against real hardware.

This task parses every ``.py`` under ``demos/`` with :mod:`ast`,
fails on syntax errors or empty files, and prints a per-file status
line.  It does not execute the files or resolve imports — that's a
deeper check that requires the venv have every dependency present;
the compile check is the cheap gate preflight can afford to run.

See ``demos/README.md`` for the directory convention.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from repo_layout import ROOT


def _collect_demo_python_files(demos_root: Path) -> list[Path]:
    """Return every ``.py`` file under ``demos/<name>/`` in sorted order."""
    if not demos_root.is_dir():
        return []
    return sorted(demos_root.rglob("*.py"))


def verify_demos() -> int:
    """Parse every ``.py`` under ``demos/`` and report results."""
    demos_root = ROOT / "demos"
    demo_files = _collect_demo_python_files(demos_root)
    if not demo_files:
        print("No demo files found under demos/.")
        return 0

    failures = 0
    for demo_file in demo_files:
        relative = demo_file.relative_to(ROOT)
        source = demo_file.read_text(encoding="utf-8")
        if not source.strip():
            print(f"  FAIL: {relative}  (empty file)")
            failures += 1
            continue
        try:
            ast.parse(source, filename=str(demo_file))
        except SyntaxError as error:
            print(f"  FAIL: {relative}  (syntax error: {error})")
            failures += 1
            continue
        print(f"  OK:   {relative}")

    if failures:
        print(f"\n{failures} demo file(s) failed compile-check.")
        return 1
    print(f"\n{len(demo_files)} demo file(s) parsed cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(verify_demos())
