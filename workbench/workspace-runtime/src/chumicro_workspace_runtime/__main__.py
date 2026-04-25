"""``python -m chumicro_workspace_runtime`` entrypoint.

Delegates straight to :func:`chumicro_workspace_runtime.cli.main`.
"""

import sys

from chumicro_workspace_runtime.cli import main

if __name__ == "__main__":
    sys.exit(main())
