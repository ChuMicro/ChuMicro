"""``python -m chumicro_workspace`` entrypoint.

Delegates straight to :func:`chumicro_workspace.cli.main`.
"""

import sys

from chumicro_workspace.cli import main

if __name__ == "__main__":
    sys.exit(main())
