"""Module entrypoint: ``python -m chumicro_workspace_template ...``."""

from __future__ import annotations

import sys

from chumicro_workspace_template.cli import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
