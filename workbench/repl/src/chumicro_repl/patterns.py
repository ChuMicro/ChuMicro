"""Pattern detectors for CircuitPython and MicroPython REPL output.

Detects the banners and blocks that mean "something noteworthy
happened on the board" so the TUI can colorize them and so ``tail()``
can fail a deploy when a traceback arrives.

Recognized kinds:

- :attr:`PatternKind.TRACEBACK`: the ``Traceback (most recent call
  last):`` header that both runtimes emit at the start of an uncaught
  exception block.  Spans from the header line through the blank line
  that follows the exception summary.
- :attr:`PatternKind.SAFE_MODE`: CircuitPython's ``safe mode`` block,
  printed when the supervisor drops into safe mode after repeated
  crashes or after ``supervisor.reload()`` into a broken state.
- :attr:`PatternKind.HARD_FAULT`: the CircuitPython ``Hard fault``
  message and the register dump that follows it.
- :attr:`PatternKind.SOFT_REBOOT`: the MicroPython ``MPY: soft
  reboot`` banner that follows a ``machine.soft_reset()`` or a
  Ctrl-D in the interactive REPL.

The detector is line-oriented.  Pass a decoded string of lines (or a
single complete line) to :func:`detect_patterns` and get back a list
of :class:`PatternMatch` records, each carrying a span into the
input string plus the detected kind.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class PatternKind(StrEnum):
    """The kinds of noteworthy output the detector recognizes.

    Inherits from :class:`enum.StrEnum` so ``kind.value`` is
    interchangeable with ``str(kind)``, which keeps JSON / dict
    serialization trivial.
    """

    TRACEBACK = "traceback"
    SAFE_MODE = "safe_mode"
    HARD_FAULT = "hard_fault"
    SOFT_REBOOT = "soft_reboot"


@dataclass(frozen=True)
class PatternMatch:
    """One pattern detected in the streamed output.

    Attributes:
        kind: The :class:`PatternKind` of this match.
        start: Start index into the input string (inclusive).
        end: End index into the input string (exclusive).
        text: The matched substring.
    """

    kind: PatternKind
    start: int
    end: int
    text: str


#: ``Traceback (most recent call last):`` header followed by the
#: indented frame block.  Shared between CP and MP, because both runtimes
#: emit the CPython-compatible traceback format.  We match the header
#: line, the indented frames, and the final ``<ExceptionClass>: ...``
#: summary line (which is not indented).  The block terminates at the
#: first fully-blank line or at a non-indented line that is not a
#: frame header, whichever comes first.
_TRACEBACK_PATTERN = re.compile(
    r"Traceback \(most recent call last\):\n"
    r"(?:  .*\n)+"            # one or more indented frame lines
    r"[^\s].*(?:\n|\Z)"       # final "ExceptionClass: message" line
)

#: CircuitPython's safe-mode banner.  Observed forms:
#:
#: - ``Auto-reload is on. ...``  (not safe mode, ignored)
#: - ``You are in safe mode because: ...\nPress reset to exit safe mode.\n``
#:
#: The banner is multi-line, ends at the "Press reset" line.  We match
#: the whole block so highlighting covers the reason line the user
#: actually needs to read.
_SAFE_MODE_PATTERN = re.compile(
    r"You are in safe mode because:.*?Press reset to exit safe mode\.\n?",
    re.DOTALL,
)

#: CircuitPython hard-fault banner.  Emitted by the supervisor before
#: safe-mode entry on a crash that bypasses Python-level exception
#: handling.  Includes a register dump on some ports; we match from
#: the header through the next blank line so the dump stays colorized
#: as part of the event.
_HARD_FAULT_PATTERN = re.compile(
    r"Hard fault.*?(?:\n\n|\Z)",
    re.DOTALL,
)

#: MicroPython soft-reboot banner.  Emitted on Ctrl-D or
#: ``machine.soft_reset()`` once the REPL comes back up.  Single line;
#: colorized so users can see where the VM cycled when watching a
#: tail.
_SOFT_REBOOT_PATTERN = re.compile(
    r"MPY: soft reboot\n?",
)


_PATTERNS: tuple[tuple[PatternKind, re.Pattern[str]], ...] = (
    (PatternKind.TRACEBACK, _TRACEBACK_PATTERN),
    (PatternKind.SAFE_MODE, _SAFE_MODE_PATTERN),
    (PatternKind.HARD_FAULT, _HARD_FAULT_PATTERN),
    (PatternKind.SOFT_REBOOT, _SOFT_REBOOT_PATTERN),
)


def detect_patterns(text: str) -> list[PatternMatch]:
    """Return every pattern match in *text*, sorted by start index.

    Overlapping matches are possible in principle (a traceback inside
    a safe-mode block, say) but the three non-traceback patterns all
    terminate cleanly, so in practice matches are disjoint.

    Args:
        text: Decoded REPL output to scan.

    Returns:
        A list of :class:`PatternMatch` records in order of first
        byte.  Empty list when no pattern matches.
    """
    matches: list[PatternMatch] = []
    for kind, pattern in _PATTERNS:
        for match in pattern.finditer(text):
            matches.append(
                PatternMatch(
                    kind=kind,
                    start=match.start(),
                    end=match.end(),
                    text=match.group(0),
                )
            )
    matches.sort(key=lambda pattern_match: pattern_match.start)
    return matches


class StreamingPatternDetector:
    """Scan an unbounded byte stream for noteworthy patterns.

    Feed decoded text into :meth:`feed` as it arrives.  The detector
    buffers a trailing window of *buffer_limit* characters so a
    pattern that spans a chunk boundary still matches, yields every
    match contained entirely within that window, and drops older
    content as new text arrives.

    Args:
        buffer_limit: Soft cap on buffered characters.  Patterns
            longer than this limit are not detected; the default
            (8 KiB) comfortably covers any realistic traceback.
    """

    __slots__ = ("_buffer", "_offset", "_buffer_limit", "_total_fed")

    def __init__(self, buffer_limit: int = 8 * 1024) -> None:
        self._buffer = ""
        self._offset = 0  # running start of _buffer inside the logical stream
        self._buffer_limit = buffer_limit
        self._total_fed = 0  # total chars ever passed through feed()

    @property
    def total_fed(self) -> int:
        """Total characters ever passed through :meth:`feed`.

        Lets a streaming consumer translate an absolute match offset
        back into the most-recently-fed chunk:
        ``chunk_start = total_fed - len(chunk)``.
        """
        return self._total_fed

    def feed(self, text: str) -> list[PatternMatch]:
        """Append *text* and return every newly-detected match.

        Matches are emitted once: subsequent :meth:`feed` calls will
        not re-emit a pattern that was already returned.  The returned
        :attr:`PatternMatch.start` / :attr:`~PatternMatch.end` indices
        are positions in the logical stream (total bytes fed), so a
        caller tracking the stream can index back into its own log.
        """
        if not text:
            return []
        self._total_fed += len(text)
        self._buffer += text
        raw_matches = detect_patterns(self._buffer)
        if not raw_matches:
            self._trim_buffer()
            return []
        absolute_matches = [
            PatternMatch(
                kind=match.kind,
                start=match.start + self._offset,
                end=match.end + self._offset,
                text=match.text,
            )
            for match in raw_matches
        ]
        # Drop buffer up to the end of the last match so the same
        # pattern is not re-detected on the next feed().
        last_local_end = raw_matches[-1].end
        self._offset += last_local_end
        self._buffer = self._buffer[last_local_end:]
        self._trim_buffer()
        return absolute_matches

    def _trim_buffer(self) -> None:
        """Bound the buffer so streams that never match stay small."""
        if len(self._buffer) <= self._buffer_limit:
            return
        excess = len(self._buffer) - self._buffer_limit
        self._offset += excess
        self._buffer = self._buffer[excess:]
