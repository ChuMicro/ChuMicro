"""Root-level test configuration for the Chumicro workspace.

Auto-discovers library and support package source roots so that
``pytest`` can be run directly without requiring manual PYTHONPATH
setup.  Also excludes ``device_tests/`` from host-side collection.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Exclude on-device tests from host-side pytest collection.
collect_ignore_glob = ["**/device_tests/**"]


def _discover_source_roots() -> list[str]:
    """Return src/ directories for all packages under libraries/ and support/."""
    roots: list[str] = []
    for parent in [ROOT / "support", ROOT / "libraries"]:
        if not parent.is_dir():
            continue
        for child in sorted(parent.iterdir()):
            src = child / "src"
            if src.is_dir():
                roots.append(str(src))
    return roots


for _src_root in _discover_source_roots():
    if _src_root not in sys.path:
        sys.path.insert(0, _src_root)

