"""Core implementation for chumicro-logging."""

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

    Args:
        name: Logger name; appears in formatted records.
        level: Minimum level emitted. Defaults to ``INFO``.
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
        """Attach a handler, unless it is already attached.

        Args:
            handler: An object exposing ``emit(level, name, message)``.
        """
        if handler not in self._handlers:
            self._handlers.append(handler)

    def remove_handler(self, handler: object) -> None:
        """Detach a handler if it is currently attached.

        Args:
            handler: A previously attached handler.
        """
        if handler in self._handlers:
            self._handlers.remove(handler)

    def is_enabled(self, level: int) -> bool:
        """Return ``True`` if *level* would be emitted by this logger."""
        return level >= self.level

    def log(self, level: int, message: str, *args: object) -> None:
        """Emit *message* at *level* to every attached handler."""
        if level < self.level:
            return
        if args:
            try:
                message = message % args
            except Exception as format_error:  # noqa: BLE001
                message = (
                    f"{message!r} % {args!r} "
                    f"(log-format error: {format_error})"
                )
                self.handler_errors += 1
        # Snapshot so a handler that mutates the list mid-emit can't skip the next one.
        for handler in tuple(self._handlers):
            try:
                handler.emit(level, self.name, message)
            except Exception:  # noqa: BLE001
                self.handler_errors += 1

    def debug(self, message: str, *args: object) -> None:
        """Emit at ``DEBUG``, interpolating ``message % args`` past the gate."""
        self.log(DEBUG, message, *args)

    def info(self, message: str, *args: object) -> None:
        """Emit at ``INFO``, interpolating ``message % args`` past the gate."""
        self.log(INFO, message, *args)

    def warning(self, message: str, *args: object) -> None:
        """Emit at ``WARNING``, interpolating ``message % args`` past the gate."""
        self.log(WARNING, message, *args)

    def error(self, message: str, *args: object) -> None:
        """Emit at ``ERROR``, interpolating ``message % args`` past the gate."""
        self.log(ERROR, message, *args)

    def critical(self, message: str, *args: object) -> None:
        """Emit at ``CRITICAL``, interpolating ``message % args`` past the gate."""
        self.log(CRITICAL, message, *args)


class StreamHandler:
    """Synchronous handler writing formatted records to a writable stream.

    Args:
        stream: A writable stream. Defaults to ``sys.stdout``.
        level: Minimum level emitted. Defaults to ``DEBUG``.
        formatter: Renders ``(level, name, message)`` to a string; defaults to ``default_formatter``.
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
        """Format the record and write it to the stream."""
        if level < self.level:
            return
        # Two writes avoid allocating a ``line + "\n"`` string per record.
        self._stream.write(self._formatter(level, name, message))
        self._stream.write("\n")
        if self._flush is not None:
            self._flush()


class BufferedHandler:
    """Runner-shaped handler that buffers records and flushes on ``handle``.

    Args:
        downstream: A handler exposing ``emit(level, name, message)``, typically a ``StreamHandler``.
        capacity: Maximum buffered records. Must be >= 1.
        level: Minimum level buffered. Defaults to ``DEBUG``.

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
        self._capacity = capacity
        self.level = level
        self._buffer = deque((), capacity)
        self.dropped = 0
        self.handler_errors = 0

    @property
    def buffered(self) -> int:
        """Records currently buffered, awaiting flush."""
        return len(self._buffer)

    @property
    def capacity(self) -> int:
        """Maximum buffered records; read-only."""
        return self._capacity

    def emit(self, level: int, name: str, message: str) -> None:
        """Buffer the record, dropping the oldest if full."""
        if level < self.level:
            return
        if len(self._buffer) >= self._capacity:
            self.dropped += 1
        self._buffer.append((level, name, message))

    def check(self, now_ms: int) -> bool:
        """Return ``True`` when the buffer has records to flush.

        Args:
            now_ms: Current tick value; unused but required by the runner contract.
        """
        return len(self._buffer) > 0

    def handle(self, now_ms: int) -> int:
        """Drain the buffer to the downstream handler and return the count flushed.

        Args:
            now_ms: Current tick value; unused but required by the runner contract.
        """
        buffer = self._buffer
        emit = self._downstream.emit
        flushed = 0
        while buffer:
            level, name, message = buffer.popleft()
            try:
                emit(level, name, message)
            except Exception:  # noqa: BLE001 - a misbehaving handler can't crash the app
                self.handler_errors += 1
            flushed += 1
        return flushed
