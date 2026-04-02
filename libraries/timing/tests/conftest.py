"""Test configuration for the Chumicro timing package."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
SRC_PATH = _HERE.parents[0] / "src"
for _p in (str(SRC_PATH), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

