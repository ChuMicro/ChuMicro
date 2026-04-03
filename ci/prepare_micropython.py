"""CLI entry point for MicroPython unix-port preparation.

Delegates to ``scripts/_prepare.prepare_micropython_main()``.
Run via ``python ci/prepare_micropython.py`` or use
``python scripts/run.py prepare-micropython``.
"""

import sys
from pathlib import Path

# Allow importing from scripts/ regardless of how this file is invoked.
_SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if _SCRIPTS not in sys.path:
    sys.path.insert(0, _SCRIPTS)

from _prepare import prepare_micropython_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(prepare_micropython_main())
