"""Workspace command shim — `python run.py <command>`.

Forwards every invocation to ``chumicro_workspace_runtime``'s CLI.
This file is tool-owned: ``chumicro-workspace-template update`` will
overwrite it.  Don't edit it; add custom commands by extending
``chumicro_workspace_runtime`` upstream or adding pyproject scripts.
"""

from __future__ import annotations

import sys

from chumicro_workspace_runtime.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
