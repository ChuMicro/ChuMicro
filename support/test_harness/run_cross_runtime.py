"""Worker entry point for one cross-runtime test file.

Invoked as ``<runtime-binary> run_cross_runtime.py --worker <test_file>``
by the ``chumicro-pytest-device`` plugin's :class:`UnixPortBackend`.
One subprocess per ``libraries/<name>/tests/test_*.py`` file, fresh
heap per call.

The script bootstraps ``sys.path`` so the harness package is
importable, then delegates to
:func:`chumicro_test_harness.discovery.run_one_file`.  That function
sets ``sys.path`` to include every ``libraries/*/src/`` plus
``support/*/src/`` so library imports resolve, then ``exec()``s the
file as a module and prints ``PASS`` / ``FAIL`` / ``SKIP`` / ``HEAP``
/ ``SUMMARY`` lines back to stdout.

Run from the workspace root::

    micropython support/test_harness/run_cross_runtime.py \\
        --worker libraries/timing/tests/test_heartbeat.py
"""

import sys

# Bootstrap: the harness package isn't pip-installed, so add its src/
# directory to sys.path manually before importing.  This script is always
# invoked from the repo root, making the relative path stable.
sys.path.insert(0, "support/test_harness/src")

from chumicro_test_harness.discovery import run_one_file  # noqa: E402

argv = sys.argv[1:]
if not argv or argv[0] != "--worker" or len(argv) < 2:
    print("usage: run_cross_runtime.py --worker <test_file>")
    raise SystemExit(2)

raise SystemExit(run_one_file(argv[1]))
