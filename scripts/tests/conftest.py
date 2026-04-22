"""Test configuration for scripts/ infrastructure tests.

Adds the scripts/ directory to sys.path so test modules can import
the scripts the same way they import each other (bare module names).
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
ROOT = SCRIPTS_DIR.parent

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

# Also add package src/ dirs so imports that discovery triggers work.
for parent in [ROOT / "support", ROOT / "libraries", ROOT / "workbench"]:
    if not parent.is_dir():
        continue
    for child in sorted(parent.iterdir()):
        source = child / "src"
        if source.is_dir() and str(source) not in sys.path:
            sys.path.insert(0, str(source))
