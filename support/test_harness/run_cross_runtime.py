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

import os  # noqa: E402

from chumicro_test_harness.discovery import run_one_file  # noqa: E402

argv = sys.argv[1:]
if not argv or argv[0] != "--worker" or len(argv) < 2:
    print("usage: run_cross_runtime.py --worker <test_file>")
    raise SystemExit(2)

# Chunked exec mirrors real-board staging: the host computes top-level
# statement boundaries (the device/unix port has no CPython ast) so a
# large test file compiles statement-by-statement instead of paying a
# whole-file compile transient the board-shaped heap can't fit.  The
# CSV rides an environment variable, NOT argv: the MicroPython unix
# port FATALs (uncaught NLR) on any argv element longer than a few
# hundred bytes, and a big file's boundary list exceeds that.
chunk_boundaries = None
boundaries_csv = os.getenv("CHUMICRO_CHUNK_BOUNDARIES")
if boundaries_csv:
    chunk_boundaries = [int(line_no) for line_no in boundaries_csv.split(",")]

raise SystemExit(run_one_file(argv[1], chunk_boundaries=chunk_boundaries))
