"""Allow ``python -m chumicro_checks`` to run the CLI."""

from __future__ import annotations

import sys

from chumicro_checks.cli import main

if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
