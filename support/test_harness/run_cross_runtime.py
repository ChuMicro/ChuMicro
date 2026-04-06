"""Entry point for cross-runtime unit tests (MicroPython / CircuitPython unix-ports).

Bootstraps ``sys.path`` so the harness package is importable, then
delegates to :func:`chumicro_test_harness.discovery.run_all`.

Positional arguments are library names to include.  When no arguments
are given, all libraries are tested.  ``run.py`` uses this to filter
by platform targeting.

Run from the repo root::

    python support/test_harness/run_cross_runtime.py
    python support/test_harness/run_cross_runtime.py timing runner
"""

import sys

sys.path.insert(0, "support/test_harness/src")

from chumicro_test_harness.discovery import run_all  # noqa: E402

libraries = sys.argv[1:] if len(sys.argv) > 1 else None
raise SystemExit(run_all(libraries=libraries))

