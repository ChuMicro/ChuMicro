"""``python -m chumicro_deploy`` entry point, delegating to :mod:`cli`."""

from __future__ import annotations

import sys  # pragma: no cover - module body runs only under ``python -m``

from .cli import main  # pragma: no cover - module body runs only under ``python -m``

if __name__ == "__main__":  # pragma: no cover - guarded entry point
    raise SystemExit(main(sys.argv[1:]))
