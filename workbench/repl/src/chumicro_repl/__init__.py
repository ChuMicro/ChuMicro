"""chumicro-repl — host-side serial REPL for embedded boards.

Publishable workbench tool (Decision 0032) that talks to CircuitPython
and MicroPython boards over pyserial.  Three surfaces:

- :func:`interactive` / ``python -m chumicro_repl`` — interactive TUI
  that forwards keystrokes to the board, with the same core
  keybindings (Ctrl-C / Ctrl-D / Ctrl-X / Ctrl-E) as mpremote's
  ``repl`` subcommand.
- :func:`tail` — one-shot "stream output for N seconds" follow-up used
  by deploy orchestration; highlights tracebacks as they arrive and
  returns an :class:`ExitCode`.
- :class:`ReplSession` — programmatic context manager with
  :meth:`~ReplSession.exec`, :meth:`~ReplSession.call`, and
  :meth:`~ReplSession.read_until` for headless fixtures.

Imports are resolved lazily through ``__getattr__`` (PEP 562) — a
``chumicro-repl --help`` invocation pays the cost of parsing argparse,
not the cost of importing pyserial + the full pattern-detector graph.
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # Re-imports for static analysis only.  Runtime resolution goes
    # through the lazy ``__getattr__`` hook below; this block exists
    # so pyright / mypy can see every name declared in ``__all__``
    # without eagerly loading every submodule.
    from ._follow import ExitCode, tail
    from .framing import Utf8StreamDecoder
    from .highlight import Theme, colorize, strip_ansi_sequences
    from .patterns import PatternKind, PatternMatch, detect_patterns
    from .session import ReplSession, ReplSessionError
    from .tui import interactive

#: Map of public attribute -> submodule.  ``__getattr__`` below walks
#: this table to defer each submodule import until the attribute is
#: first read.
_LAZY_ATTRS: dict[str, str] = {
    "ExitCode": "_follow",
    "PatternKind": "patterns",
    "PatternMatch": "patterns",
    "ReplSession": "session",
    "ReplSessionError": "session",
    "Theme": "highlight",
    "Utf8StreamDecoder": "framing",
    "colorize": "highlight",
    "detect_patterns": "patterns",
    "interactive": "tui",
    "strip_ansi_sequences": "highlight",
    "tail": "_follow",
}

#: Public API surface.  Spelled as a literal list so static type
#: checkers (pyright in particular) can see every exported name.
#: Keep alphabetized; a sorted assertion below catches drift.
__all__ = [
    "ExitCode",
    "PatternKind",
    "PatternMatch",
    "ReplSession",
    "ReplSessionError",
    "Theme",
    "Utf8StreamDecoder",
    "colorize",
    "detect_patterns",
    "interactive",
    "strip_ansi_sequences",
    "tail",
]
assert sorted(__all__) == __all__, "__all__ must be alphabetized"
assert set(__all__) == set(_LAZY_ATTRS), "__all__ must match _LAZY_ATTRS"


def __getattr__(name: str) -> Any:
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(
            f"module 'chumicro_repl' has no attribute {name!r}"
        )
    module = importlib.import_module(f".{module_name}", __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return [*globals().keys(), *_LAZY_ATTRS.keys()]
