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
    from .line_mode import (
        BUILTIN_COMMANDS,
        DEFAULT_HISTORY_ROOT,
        DEFAULT_SNIPPETS_ROOT,
        CommandHandler,
        LineModeContext,
        history_path_for,
        run_line_mode,
        sanitize_address,
    )
    from .patterns import PatternKind, PatternMatch, detect_patterns
    from .recovery import (
        InteractiveReplSession,
        RecoveryPlan,
        ReplFailureKind,
        classify_session_failure,
        recovery_plan_for,
    )
    from .session import ReplSession, ReplSessionDisconnected, ReplSessionError
    from .tui import interactive, interactive_line

#: Map of public attribute -> submodule.  ``__getattr__`` below walks
#: this table to defer each submodule import until the attribute is
#: first read.
_LAZY_ATTRS: dict[str, str] = {
    "BUILTIN_COMMANDS": "line_mode",
    "CommandHandler": "line_mode",
    "DEFAULT_HISTORY_ROOT": "line_mode",
    "DEFAULT_SNIPPETS_ROOT": "line_mode",
    "ExitCode": "_follow",
    "InteractiveReplSession": "recovery",
    "LineModeContext": "line_mode",
    "PatternKind": "patterns",
    "PatternMatch": "patterns",
    "RecoveryPlan": "recovery",
    "ReplFailureKind": "recovery",
    "ReplSession": "session",
    "ReplSessionDisconnected": "session",
    "ReplSessionError": "session",
    "Theme": "highlight",
    "Utf8StreamDecoder": "framing",
    "classify_session_failure": "recovery",
    "colorize": "highlight",
    "detect_patterns": "patterns",
    "history_path_for": "line_mode",
    "interactive": "tui",
    "interactive_line": "tui",
    "recovery_plan_for": "recovery",
    "run_line_mode": "line_mode",
    "sanitize_address": "line_mode",
    "strip_ansi_sequences": "highlight",
    "tail": "_follow",
}

#: Public API surface.  Spelled as a literal list so static type
#: checkers (pyright in particular) can see every exported name.
#: Keep alphabetized; a sorted assertion below catches drift.
__all__ = [
    "BUILTIN_COMMANDS",
    "CommandHandler",
    "DEFAULT_HISTORY_ROOT",
    "DEFAULT_SNIPPETS_ROOT",
    "ExitCode",
    "InteractiveReplSession",
    "LineModeContext",
    "PatternKind",
    "PatternMatch",
    "RecoveryPlan",
    "ReplFailureKind",
    "ReplSession",
    "ReplSessionDisconnected",
    "ReplSessionError",
    "Theme",
    "Utf8StreamDecoder",
    "classify_session_failure",
    "colorize",
    "detect_patterns",
    "history_path_for",
    "interactive",
    "interactive_line",
    "recovery_plan_for",
    "run_line_mode",
    "sanitize_address",
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
