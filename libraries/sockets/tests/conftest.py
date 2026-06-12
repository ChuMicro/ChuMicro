"""Test configuration for the chumicro-sockets package.

Puts this directory on ``sys.path`` so test files can import the
sibling ``_swap_helpers`` module under pytest's ``importlib`` import
mode, which — unlike ``prepend`` mode — does not add a test file's own
directory to the path.  The cross-runtime harness and the on-device
collector resolve sibling helpers through their own staging paths.
"""

import sys
from pathlib import Path

_tests_dir = str(Path(__file__).resolve().parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)
