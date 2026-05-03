"""Entry point for cross-runtime unit tests (MicroPython / CircuitPython unix-ports).

Bootstraps ``sys.path`` so the harness package is importable, then
delegates to either :func:`chumicro_test_harness.discovery.run_all`
(manager mode) or :func:`chumicro_test_harness.discovery.run_one_file`
(worker mode, when invoked with ``--worker <test_file>``).

Manager mode (default): Positional arguments are library names to
include.  When no arguments are given, all libraries are tested.
By default each test file runs in a fresh subprocess (clean heap
per file, mirroring real-board behaviour) — pass ``--no-isolate``
to fall back to the legacy single-process model.

Worker mode (internal): triggered by ``--worker <file>`` and runs
exactly one test file in this process; its stdout becomes the
manager's per-file output.  Not meant to be called by humans
directly.

Run from the repo root::

    python support/test_harness/run_cross_runtime.py
    python support/test_harness/run_cross_runtime.py timing runner
    python support/test_harness/run_cross_runtime.py --no-isolate timing
"""

import sys

# Bootstrap: the harness package isn't pip-installed, so add its src/
# directory to sys.path manually before importing.  This script is always
# invoked from the repo root, making the relative path stable.
sys.path.insert(0, "support/test_harness/src")

from chumicro_test_harness.discovery import run_all, run_one_file  # noqa: E402

argv = sys.argv[1:]

# Worker mode — internal, spawned by the manager.
if argv and argv[0] == "--worker":
    if len(argv) < 2:
        print("usage: run_cross_runtime.py --worker <test_file>")
        raise SystemExit(2)
    raise SystemExit(run_one_file(argv[1]))

# Manager mode — parse opt-out flag, then positional libraries.
isolate_per_file = True
if argv and argv[0] == "--no-isolate":
    isolate_per_file = False
    argv = argv[1:]

libraries = argv if argv else None
raise SystemExit(run_all(libraries=libraries, isolate_per_file=isolate_per_file))
