"""Entry point for cross-runtime unit tests (MicroPython / CircuitPython unix-ports).

Bootstraps ``sys.path`` so the harness package is importable, then
delegates to :func:`chumicro_test_harness.discovery.run_all`.

Run from the repo root::

    python support/test_harness/run_cross_runtime.py
"""

import sys

sys.path.insert(0, "support/test_harness/src")

from chumicro_test_harness.discovery import run_all  # noqa: E402

raise SystemExit(run_all())

