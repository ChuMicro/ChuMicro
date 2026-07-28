"""chumicro-repl: host-side serial REPL for embedded boards.

Publishable workbench tool that talks to CircuitPython and MicroPython
boards over pyserial.  Four surfaces:

- :func:`interactive_line` / ``python -m chumicro_repl``: line-mode
  REPL with line editing, Tab completion, persistent history, and
  ``:commands``.  What the bare command opens on a terminal.
- :func:`interactive`: passthrough TUI that forwards keystrokes to the
  board, with core keybindings (Ctrl-C / Ctrl-D / Ctrl-X / Ctrl-E).
  Opt in with ``--mode passthrough``; also the automatic choice when
  stdin is not a terminal.
- :func:`tail`: one-shot "stream output for N seconds" follow-up used
  by deploy orchestration; highlights tracebacks as they arrive and
  returns an :class:`ExitCode`.
- :class:`ReplSession`: programmatic context manager with
  :meth:`~ReplSession.exec`, :meth:`~ReplSession.call`, and
  :meth:`~ReplSession.read_until` for headless fixtures.

The heavy third-party deps (pyserial, prompt_toolkit) are imported
lazily inside ``default_port_factory`` and ``_build_prompt_session``,
so ``import chumicro_repl`` stays cheap.
"""

from __future__ import annotations

from ._follow import ExitCode, tail
from .completion import (
    CompletionCache,
    build_default_completer,
    fetch_device_names,
)
from .highlight import Theme, colorize
from .line_mode import (
    BUILTIN_COMMANDS,
    CommandHandler,
    LineModeContext,
)
from .patterns import PatternKind, PatternMatch, detect_patterns
from .recovery import (
    InteractiveReplSession,
    RecoveryPlan,
    ReplFailureKind,
    classify_session_failure,
    coached_session_start,
    recovery_plan_for,
)
from .session import ReplSession, ReplSessionDisconnected, ReplSessionError
from .tui import interactive, interactive_line

#: Public API surface.  Submodule-only helpers
#: (``chumicro_repl.highlight.strip_ansi_sequences``,
#: ``chumicro_repl.framing.Utf8StreamDecoder``,
#: ``chumicro_repl.line_mode.run_line_mode``, etc.) stay reachable
#: at their submodule path but are not re-exported here.
__all__ = [
    "BUILTIN_COMMANDS",
    "CommandHandler",
    "CompletionCache",
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
    "build_default_completer",
    "classify_session_failure",
    "coached_session_start",
    "colorize",
    "detect_patterns",
    "fetch_device_names",
    "interactive",
    "interactive_line",
    "recovery_plan_for",
    "tail",
]
