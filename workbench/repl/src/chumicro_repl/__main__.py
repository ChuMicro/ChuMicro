"""``python -m chumicro_repl`` entry point: delegates to :mod:`cli`."""

from __future__ import annotations

import sys

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
