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


def _has_explicit_functional_arg(config) -> bool:
    """Did the pytest invocation explicitly target a functional_tests path?

    True for ``pytest .../functional_tests/test_x.py``,
    ``.../functional_tests/test_x.py::test_y``, or a bare
    ``functional_tests/`` directory — i.e. the path-target invocations
    IDE Testing panels emit when the user clicks gutter ▶, right-clicks
    "Run Tests in folder", or runs a specific test by name.

    False for default discovery / sweeps where the user did not name a
    functional_tests path themselves.
    """
    for arg in config.args:
        # Strip nodeid suffix (``path::Test::method``) before resolving.
        path_part = str(arg).split("::", 1)[0]
        if "functional_tests" in Path(path_part).parts:
            return True
    return False


def pytest_ignore_collect(collection_path, config):
    """Make ``functional_tests/`` items visible to IDE discovery without sweeping them.

    IDE Testing panels (VS Code, PyCharm) only render gutter ▶ buttons
    next to tests pytest actually collected during discovery, so any
    "hide at collection time" approach kills the gutter-▶ workflow for
    hardware tests entirely.  This hook therefore only hides
    ``functional_tests/`` when the workspace has *no*
    ``devices.yml`` — fresh clones keep a clean Testing tree until the
    user runs ``python scripts/run.py setup`` and fills in board
    details.

    Once ``devices.yml`` exists, items are *collected* (so VS Code can
    paint gutter buttons) but a sibling ``pytest_collection_modifyitems``
    hook below *deselects* them whenever the invocation didn't
    explicitly target a ``functional_tests/`` path.  Net effect:

    - VS Code Testing tree: functional tests visible with gutter ▶.
    - Click gutter ▶ on one test, or right-click "Run Tests in
      folder" → invocation includes a ``functional_tests`` path arg →
      runs against hardware via ``pytest_device``.
    - Bare ``pytest`` from rootdir, or any "run all unit tests"
      sweep that doesn't name a ``functional_tests`` path → items
      collected but immediately deselected; only host tests run.

    The plugin ``pytest.skip(...)`` s with a friendly message at runtime
    when ``devices.yml`` exists but has no defaults configured.
    """
    if "functional_tests" not in collection_path.parts:
        return None  # Not a functional_tests path — use default behavior.

    # Always allow when path-targeted via CLI args.
    if _has_explicit_functional_arg(config):
        return False

    # Otherwise gate on devices.yml so fresh clones stay tidy and
    # configured workspaces get gutter buttons.  The sweep-deselect
    # hook below keeps configured workspaces from running hardware
    # tests during default sweeps.
    if (ROOT / "devices.yml").exists():
        return False

    return True


def pytest_collection_modifyitems(config, items):
    """Deselect ``functional_tests/`` items during default sweeps.

    Pairs with ``pytest_ignore_collect`` above: items remain
    *collected* so IDE Testing panels render gutter buttons, but when
    the invocation didn't explicitly name a ``functional_tests`` path
    we deselect them so a default ``pytest`` / "Run All Tests" sweep
    only runs host tests.

    When the user *does* explicitly target a ``functional_tests/``
    path or nodeid, this hook returns immediately and the items
    proceed to run against hardware.
    """
    if _has_explicit_functional_arg(config):
        return

    deselected: list = []
    selected: list = []
    for item in items:
        if "functional_tests" in str(item.fspath):
            deselected.append(item)
        else:
            selected.append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected


def _discover_source_roots() -> list[str]:
    """Return src/ directories for all packages under libraries/, support/, and workbench/."""
    roots: list[str] = []
    for parent in [ROOT / "support", ROOT / "libraries", ROOT / "workbench"]:
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
