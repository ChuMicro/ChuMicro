"""Core implementation for chumicro-logging.

See ``__init__`` for the public API summary.  This module is pure-Python,
imports ``sys`` and ``collections.deque``, and is identical on every
supported runtime.

``BufferedHandler``'s queue is a ``deque(iterable, maxlen)`` rather than
a list — ``append`` and ``popleft`` are O(1) and the deque's native
``maxlen`` enforcement gives drop-oldest behavior without the O(n)
shift cost of ``list.pop(0)`` on small VMs.
"""

import sys
from collections import deque

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

DEBUG = const(10)
INFO = const(20)
WARNING = const(30)
ERROR = const(40)
CRITICAL = const(50)

_LEVEL_NAMES = {
    DEBUG: "DEBUG",
    INFO: "INFO",
    WARNING: "WARNING",
    ERROR: "ERROR",
    CRITICAL: "CRITICAL",
}


def level_name(level: int) -> str:
    """Return the human name for *level*, or ``"LEVEL<n>"`` if unknown."""
    name = _LEVEL_NAMES.get(level)
    if name is not None:
        return name
    return f"LEVEL{level}"


def default_formatter(level: int, name: str, message: str) -> str:
    """Render a record as ``LEVEL:name:message`` on a single line."""
    return f"{level_name(level)}:{name}:{message}"


class Logger:
    """A named logger with a level threshold and a list of handlers.

    Loggers are not registered globally — the caller owns the instance
    and passes it explicitly to subsystems that want to emit.  This
    avoids import-order surprises and keeps the library stateless.

    Records below the configured level are dropped before any handler
    is consulted.  Each handler decides independently whether to emit.

    Handler exceptions never escape the logger — they increment
    ``handler_errors`` and are otherwise swallowed.  Logging must
    not crash the application that uses it.

    Args:
        name: Logger name; appears in formatted records.
        level: Minimum level emitted.  Defaults to ``INFO``.
        handlers: Initial handlers; copied into an internal list.
    """

    def __init__(
        self,
        name: str,
        level: int = INFO,
        handlers: list | None = None,
    ) -> None:
        self.name = name
        self.level = level
        self._handlers: list = list(handlers) if handlers is not None else []
        self.handler_errors = 0

    @property
    def handlers(self) -> tuple:
        """Snapshot of attached handlers as a tuple."""
        return tuple(self._handlers)

    def add_handler(self, handler: object) -> None:
        """Attach a handler.  No-op if already attached.

        Args:
            handler: An object exposing ``emit(level, name, message)``.
        """
        if handler not in self._handlers:
            self._handlers.append(handler)

    def remove_handler(self, handler: object) -> None:
        """Detach a handler.  No-op if not attached.

        Args:
            handler: A previously attached handler.
        """
        if handler in self._handlers:
            self._handlers.remove(handler)

    def is_enabled(self, level: int) -> bool:
        """Return ``True`` if *level* would be emitted by this logger.

        Useful for skipping expensive message construction when the
        record would be dropped anyway.
        """
        return level >= self.level

    def log(self, level: int, message: str) -> None:
        """Emit *message* at *level* to every attached handler."""
        if level < self.level:
            return
        for handler in self._handlers:
            try:
                handler.emit(level, self.name, message)
            except Exception:  # noqa: BLE001
                self.handler_errors += 1

    def debug(self, message: str) -> None:
        """Emit at ``DEBUG``."""
        self.log(DEBUG, message)

    def info(self, message: str) -> None:
        """Emit at ``INFO``."""
        self.log(INFO, message)

    def warning(self, message: str) -> None:
        """Emit at ``WARNING``."""
        self.log(WARNING, message)

    def error(self, message: str) -> None:
        """Emit at ``ERROR``."""
        self.log(ERROR, message)

    def critical(self, message: str) -> None:
        """Emit at ``CRITICAL``."""
        self.log(CRITICAL, message)


class StreamHandler:
    """Synchronous handler writing formatted records to a writable stream.

    Calls ``stream.write(line + "\\n")`` and ``stream.flush()`` (when
    available) for every emitted record.  On microcontrollers this
    typically resolves to the serial console via ``sys.stdout``; on
    CPython any file-like object works.

    The handler keeps no buffer of its own — every call to ``emit``
    hits the stream.  Use ``BufferedHandler`` to decouple emission
    from a hot path.

    Args:
        stream: A writable stream.  Defaults to ``sys.stdout``.
        level: Minimum level emitted.  Defaults to ``DEBUG``.
        formatter: Callable rendering ``(level, name, message)`` to
            a string.  Defaults to ``default_formatter``.
    """

    def __init__(
        self,
        stream: object | None = None,
        level: int = DEBUG,
        formatter: object | None = None,
    ) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self.level = level
        self._formatter = formatter if formatter is not None else default_formatter
        self._flush = getattr(self._stream, "flush", None)

    def emit(self, level: int, name: str, message: str) -> None:
        """Format the record and write it to the stream.

        Records below the handler's level are dropped silently.
        """
        if level < self.level:
            return
        self._stream.write(self._formatter(level, name, message))
        self._stream.write("\n")
        if self._flush is not None:
            self._flush()


class BufferedHandler:
    """Runner-shaped handler buffering records and flushing on ``handle``.

    Drop-in front of any other handler.  ``emit`` is cheap — it appends
    to a bounded buffer — so libraries on a hot tick can log freely
    without paying for I/O.  ``check(now_ms)`` returns ``True`` when
    the buffer is non-empty; ``handle(now_ms)`` drains it to the
    downstream handler.  Wire the buffered handler into a
    ``chumicro-runner`` instance for automatic draining.

    When the buffer is full, the **oldest** record is dropped and
    ``dropped`` is incremented.  The newest record always wins on the
    assumption the operator wants to see *recent* activity when the
    rate exceeds the flush cadence.

    Args:
        downstream: A handler exposing ``emit(level, name, message)``
            (typically a ``StreamHandler``).
        capacity: Maximum buffered records.  Must be >= 1.
        level: Minimum level buffered.  Defaults to ``DEBUG``.

    Raises:
        ValueError: If *capacity* < 1.
    """

    def __init__(
        self,
        downstream: object,
        capacity: int = 32,
        level: int = DEBUG,
    ) -> None:
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        self._downstream = downstream
        self.capacity = capacity
        self.level = level
        self._buffer = deque((), capacity)
        self.dropped = 0

    @property
    def buffered(self) -> int:
        """Records currently buffered, awaiting flush."""
        return len(self._buffer)

    def emit(self, level: int, name: str, message: str) -> None:
        """Buffer the record.  Drop the oldest if full."""
        if level < self.level:
            return
        if len(self._buffer) >= self.capacity:
            self.dropped += 1
        # deque(maxlen=capacity) drops the oldest record automatically.
        self._buffer.append((level, name, message))

    def check(self, now_ms: int) -> bool:
        """Return ``True`` when the buffer has records to flush.

        Args:
            now_ms: Current tick value (unused; required by the
                runner contract).
        """
        return len(self._buffer) > 0

    def handle(self, now_ms: int) -> int:
        """Drain the buffer to the downstream handler.  Returns flushed count.

        Args:
            now_ms: Current tick value (unused; required by the
                runner contract).
        """
        buffer = self._buffer
        emit = self._downstream.emit
        flushed = 0
        while buffer:
            level, name, message = buffer.popleft()
            emit(level, name, message)
            flushed += 1
        return flushed
