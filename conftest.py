"""Root-level test configuration for the ChuMicro workspace.

Auto-discovers library and support package source roots so that
``pytest`` can resolve imports even without editable installs
(e.g., in CI or on a fresh clone before setup runs).

Functional tests (``functional_tests/``) are excluded from normal
host-side collection.  When an IDE targets one directly — whether
a single file, a single function, or the whole directory — the
``pytest_device`` plugin intercepts it and routes execution to a
connected board.  No environment variable setup needed; the plugin
reads ``devices.yml`` to find the target device.

See ``plans/decisions/0009-per-library-test-runs.md`` for the
per-library test isolation strategy.
See ``plans/decisions/0027-device-testing-infrastructure.md`` for
IDE integration via the device plugin.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# Always register the device plugin.  It only activates for files
# inside functional_tests/ directories — normal test runs are
# unaffected.
pytest_plugins = ["pytest_device"]


def pytest_ignore_collect(collection_path, config):
    """Ignore functional_tests/ during normal discovery, allow explicit targeting.

    Normal test runs (``python scripts/run.py test``) skip
    ``functional_tests/`` directories since those require a connected
    device.  When the IDE targets a ``functional_tests`` path directly
    (play button on a file, function, or directory), collection is
    allowed and the ``pytest_device`` plugin routes execution to
    hardware.
    """
    if "functional_tests" not in collection_path.parts:
        return None  # Not a functional_tests path — use default behavior.

    # Check if any CLI arg explicitly targets a functional_tests path.
    for arg in config.args:
        arg_path = Path(arg).resolve()
        if "functional_tests" in arg_path.parts:
            return False  # Explicitly targeted — allow collection.

    return True  # Normal traversal — ignore functional_tests.


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

# scripts/ modules use bare imports (e.g. ``from workspace import ROOT``).
# Add scripts/ to sys.path so tests collected from root can resolve them.
_scripts_dir = str(ROOT / "scripts")
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)
