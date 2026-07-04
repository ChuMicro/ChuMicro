"""Worker entry point that runs every bench on one unix-port runtime.

Invoked as ``<runtime-binary> scripts/benches/run_bench.py`` by
``run.py bench``, from the workspace root.  Mirrors
``support/test_harness/run_cross_runtime.py``: it bootstraps ``sys.path``
so library sources and the bench harness resolve, imports every
``bench_*.py`` module (each registers its cases at import), then runs them
all and prints one ``BENCH ...`` line per case to stdout.

Run standalone to eyeball the numbers::

    .tools/.../micropython scripts/benches/run_bench.py
"""

import sys

# The harness support package isn't importable until its src/ is on the
# path; add it first, then let ``setup_source_paths`` add every
# ``libraries/*/src`` + ``support/*/src`` so bench modules' library
# imports resolve.  Same bootstrap the cross-runtime test worker uses.
sys.path.insert(0, "support/test_harness/src")

from chumicro_test_harness.discovery import setup_source_paths  # noqa: E402

setup_source_paths(".")

# The bench harness and the bench modules themselves live here.
sys.path.insert(0, "scripts/benches")

# Importing a bench module registers its cases as a side effect.  List
# them explicitly (rather than globbing) so the two first consumers are
# named and ordered; add a line here when a library grows a bench.
import bench_runner  # noqa: E402, F401
import bench_websockets  # noqa: E402, F401
from _harness import run_all  # noqa: E402

raise SystemExit(run_all())
