"""CLI entry point for CircuitPython unix-port preparation.

Delegates to ``scripts/_prepare.prepare_circuitpython_main()``.
Run via ``python ci/prepare_circuitpython.py`` or use
``python scripts/run.py prepare-circuitpython``.
"""

import sys
from pathlib import Path

# Allow importing from scripts/ regardless of how this file is invoked.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from _prepare import prepare_circuitpython_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(prepare_circuitpython_main())
