"""ANSI colorization for detected REPL patterns.

Renders :class:`~chumicro_repl.patterns.PatternMatch` spans into
terminal escape sequences.  A small :class:`Theme` dataclass maps
each :class:`~chumicro_repl.patterns.PatternKind` to an ANSI SGR
string; the default theme uses the same color choices as
``mpremote`` + ``rich.traceback``: red/bold for tracebacks and hard
faults, yellow for safe mode, dim/cyan for soft-reboot banners.

Emits raw ANSI escape sequences only, with no ``rich`` dependency.
Output destined for a non-TTY stream can be passed through
:func:`strip_ansi_sequences` downstream to recover plain text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .patterns import (
    PatternKind,
    PatternMatch,
    StreamingPatternDetector,
    detect_patterns,
)

#: ANSI CSI reset: ``\x1b[0m``.  Clears every SGR attribute.
_ANSI_RESET = "\x1b[0m"

#: Regex for stripping ANSI escape sequences back out of a string.
#: Conservative: matches the ``CSI .* <final byte>`` shape used by
#: SGR styling; does not try to handle the full VT100 vocabulary.
_ANSI_SEQUENCE_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass(frozen=True)
class Theme:
    """ANSI styles for each recognized pattern kind.

    Each field is the SGR parameter string (the digits between
    ``\\x1b[`` and ``m``).  Default values chosen to read cleanly on
    both light and dark terminal backgrounds:

    - ``traceback``: bold red (``1;31``).
    - ``safe_mode``: bold yellow (``1;33``), distinct from errors
      but still attention-grabbing.
    - ``hard_fault``: bold red background (``1;41``), maximum
      attention since hard faults mean the chip is unhappy at a
      level below Python.
    - ``soft_reboot``: dim cyan (``2;36``), informational only.
      The user asked for it.
    """

    traceback: str = "1;31"
    safe_mode: str = "1;33"
    hard_fault: str = "1;41"
    soft_reboot: str = "2;36"

    def style_for(self, kind: PatternKind) -> str:
        """Return the ANSI SGR parameter string for *kind*."""
        if kind == PatternKind.TRACEBACK:
            return self.traceback
        if kind == PatternKind.SAFE_MODE:
            return self.safe_mode
        if kind == PatternKind.HARD_FAULT:
            return self.hard_fault
        if kind == PatternKind.SOFT_REBOOT:
            return self.soft_reboot
        # Enum is closed; an unknown kind means a future pattern was
        # added without wiring a style.  Fall back to no styling
        # rather than crash.  The highlighter should never be the cause
        # of a REPL session ending.
        return ""  # pragma: no cover - defensive, enum is closed today


#: Default theme used by :func:`colorize` and the TUI when no theme
#: is specified.  Exposed as a module-level singleton so callers can
#: reference a stable instance for comparison / tests.
DEFAULT_THEME = Theme()


def colorize(
    text: str,
    *,
    theme: Theme | None = None,
    matches: list[PatternMatch] | None = None,
) -> str:
    """Return *text* with ANSI escapes around each detected pattern.

    When *matches* is ``None`` the detector runs over *text*
    directly; pre-compute matches and pass them explicitly for
    streaming callers that already know where the patterns start.

    Overlapping matches are handled by walking in start-index order
    and skipping any match whose start falls inside a previously-emitted
    span.  This keeps the escape sequences balanced (one reset per style).

    Args:
        text: Decoded REPL output.
        theme: Color theme.  Defaults to :data:`DEFAULT_THEME`.
        matches: Pre-computed matches.  Defaults to running the
            detector over *text*.

    Returns:
        *text* with ANSI SGR sequences wrapping each pattern.  When
        no patterns match the original string is returned unchanged.
    """
    active_theme = theme if theme is not None else DEFAULT_THEME
    resolved_matches = (
        matches if matches is not None else detect_patterns(text)
    )
    if not resolved_matches:
        return text

    output_parts: list[str] = []
    cursor = 0
    for pattern_match in resolved_matches:
        if pattern_match.start < cursor:
            # Overlapping or out-of-order: skip to keep escapes balanced.
            continue
        output_parts.append(text[cursor:pattern_match.start])
        sgr = active_theme.style_for(pattern_match.kind)
        output_parts.append(f"\x1b[{sgr}m")
        output_parts.append(text[pattern_match.start:pattern_match.end])
        output_parts.append(_ANSI_RESET)
        cursor = pattern_match.end
    output_parts.append(text[cursor:])
    return "".join(output_parts)


def strip_ansi_sequences(text: str) -> str:
    """Return *text* with every ANSI escape sequence removed.

    Intended for tests that assert on highlighted output, where the ANSI
    bytes are noise in an ``assert "Traceback" in output`` context.
    Also useful when piping colorized output into a log file without
    losing human-readable content.
    """
    return _ANSI_SEQUENCE_PATTERN.sub("", text)


def colorize_stream_chunk(
    text: str,
    matches: list[PatternMatch],
    detector: StreamingPatternDetector,
    *,
    theme: Theme | None = None,
) -> str:
    """Render *text* with ANSI highlighting using stream-coordinate *matches*.

    A :class:`~chumicro_repl.patterns.StreamingPatternDetector` fed
    chunk by chunk returns matches whose ``start`` / ``end`` are
    absolute offsets from the start of the logical stream.  This
    helper translates those offsets back into indices within the
    most-recently-fed chunk and wraps each in-range span via
    :func:`colorize`.  Matches whose translated coordinates fall
    entirely outside *text* are skipped.
    """
    if not matches:
        return text
    stream_start = detector.total_fed - len(text)
    local_matches: list[PatternMatch] = []
    for pattern_match in matches:
        local_start = pattern_match.start - stream_start
        local_end = pattern_match.end - stream_start
        if local_end <= 0 or local_start >= len(text):
            continue
        local_start = max(0, local_start)
        local_end = min(len(text), local_end)
        local_matches.append(
            PatternMatch(
                kind=pattern_match.kind,
                start=local_start,
                end=local_end,
                text=text[local_start:local_end],
            )
        )
    return colorize(text, theme=theme, matches=local_matches)
