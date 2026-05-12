"""Tests for chumicro_logging.

Cross-runtime: pure-Python, no third-party deps, no hardware.  Runs on
CPython under pytest, and the same assertions hold under the
chumicro-test-harness on MicroPython and CircuitPython unix ports.
"""

import io
import sys

import chumicro_logging
from chumicro_logging import (
    CRITICAL,
    DEBUG,
    ERROR,
    INFO,
    WARNING,
    BufferedHandler,
    Logger,
    StreamHandler,
    default_formatter,
    level_name,
)
from chumicro_logging.testing import FailingHandler, RecordingHandler
from chumicro_test_harness.assertions import raises

# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_public_exports_present() -> None:
    """Every documented export is importable from the top-level package."""
    for name in (
        "BufferedHandler",
        "CRITICAL",
        "DEBUG",
        "ERROR",
        "INFO",
        "Logger",
        "StreamHandler",
        "WARNING",
        "default_formatter",
        "level_name",
    ):
        assert hasattr(chumicro_logging, name), f"missing export: {name}"


def test_level_constants_are_stdlib_compatible() -> None:
    """Level integers match stdlib logging so callers can interop."""
    assert DEBUG == 10
    assert INFO == 20
    assert WARNING == 30
    assert ERROR == 40
    assert CRITICAL == 50


# ---------------------------------------------------------------------------
# level_name
# ---------------------------------------------------------------------------


def test_level_name_known_levels() -> None:
    assert level_name(DEBUG) == "DEBUG"
    assert level_name(INFO) == "INFO"
    assert level_name(WARNING) == "WARNING"
    assert level_name(ERROR) == "ERROR"
    assert level_name(CRITICAL) == "CRITICAL"


def test_level_name_unknown_level_renders_with_prefix() -> None:
    assert level_name(15) == "LEVEL15"
    assert level_name(0) == "LEVEL0"
    assert level_name(99) == "LEVEL99"


# ---------------------------------------------------------------------------
# default_formatter
# ---------------------------------------------------------------------------


def test_default_formatter_known_level() -> None:
    assert default_formatter(INFO, "boot", "ready") == "INFO:boot:ready"


def test_default_formatter_unknown_level() -> None:
    assert default_formatter(15, "x", "y") == "LEVEL15:x:y"


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------


def test_logger_default_level_is_info() -> None:
    logger = Logger("root")
    assert logger.level == INFO
    assert not logger.is_enabled(DEBUG)
    assert logger.is_enabled(INFO)
    assert logger.is_enabled(WARNING)


def test_logger_initial_handlers_copied_into_internal_list() -> None:
    handler = RecordingHandler()
    handlers_arg = [handler]
    logger = Logger("root", handlers=handlers_arg)
    handlers_arg.append("extra")
    assert logger.handlers == (handler,)


def test_logger_starts_with_no_handlers_when_none_passed() -> None:
    logger = Logger("root")
    assert logger.handlers == ()


def test_logger_add_handler_idempotent() -> None:
    logger = Logger("root")
    handler = RecordingHandler()
    logger.add_handler(handler)
    logger.add_handler(handler)
    assert logger.handlers == (handler,)


def test_logger_remove_handler() -> None:
    logger = Logger("root")
    handler = RecordingHandler()
    logger.add_handler(handler)
    logger.remove_handler(handler)
    assert logger.handlers == ()


def test_logger_remove_handler_when_absent_is_noop() -> None:
    logger = Logger("root")
    handler = RecordingHandler()
    logger.remove_handler(handler)
    assert logger.handlers == ()


def test_logger_emits_to_attached_handlers() -> None:
    handler_a = RecordingHandler()
    handler_b = RecordingHandler()
    logger = Logger("root", level=DEBUG, handlers=[handler_a, handler_b])
    logger.info("up")
    assert handler_a.records == [(INFO, "root", "up")]
    assert handler_b.records == [(INFO, "root", "up")]


def test_logger_drops_records_below_level() -> None:
    handler = RecordingHandler()
    logger = Logger("root", level=WARNING, handlers=[handler])
    logger.debug("d")
    logger.info("i")
    logger.warning("w")
    logger.error("e")
    logger.critical("c")
    assert [record[0] for record in handler.records] == [WARNING, ERROR, CRITICAL]


def test_logger_level_setter_changes_threshold() -> None:
    handler = RecordingHandler()
    logger = Logger("root", level=ERROR, handlers=[handler])
    logger.info("dropped")
    logger.level = INFO
    logger.info("kept")
    assert handler.records == [(INFO, "root", "kept")]


def test_logger_level_methods_each_route_to_correct_level() -> None:
    handler = RecordingHandler()
    logger = Logger("root", level=DEBUG, handlers=[handler])
    logger.debug("d")
    logger.info("i")
    logger.warning("w")
    logger.error("e")
    logger.critical("c")
    assert [record[0] for record in handler.records] == [
        DEBUG,
        INFO,
        WARNING,
        ERROR,
        CRITICAL,
    ]


def test_logger_log_with_arbitrary_integer_level() -> None:
    handler = RecordingHandler()
    logger = Logger("root", level=15, handlers=[handler])
    logger.log(15, "intermediate")
    assert handler.records == [(15, "root", "intermediate")]


def test_logger_swallows_handler_exceptions() -> None:
    failing = FailingHandler()
    recorder = RecordingHandler()
    logger = Logger("root", level=DEBUG, handlers=[failing, recorder])
    logger.info("survive")
    assert failing.calls == 1
    assert logger.handler_errors == 1
    assert recorder.records == [(INFO, "root", "survive")]


def test_logger_swallows_multiple_distinct_handler_exceptions() -> None:
    handler = FailingHandler()
    logger = Logger("root", level=DEBUG, handlers=[handler])
    for _ in range(5):
        logger.info("boom")
    assert logger.handler_errors == 5


def test_logger_name_is_exposed() -> None:
    logger = Logger("subsystem.alpha")
    assert logger.name == "subsystem.alpha"


# ---------------------------------------------------------------------------
# StreamHandler
# ---------------------------------------------------------------------------


def test_stream_handler_writes_formatted_line() -> None:
    stream = io.StringIO()
    handler = StreamHandler(stream=stream)
    handler.emit(INFO, "boot", "ready")
    assert stream.getvalue() == "INFO:boot:ready\n"


def test_stream_handler_default_stream_is_stdout() -> None:
    """``StreamHandler()`` (no ``stream=``) captures ``sys.stdout``.

    Verified by checking the handler's internal stream attribute
    rather than swapping ``sys.stdout`` for an in-memory buffer:
    MicroPython's ``sys`` module is read-only (no ``__setattr__``),
    so the swap-and-restore pattern raises ``AttributeError`` on the
    unix-port.  Asserting the reference identity is what we actually
    care about anyway — that no copy / wrapper sneaks in between.
    """
    handler = StreamHandler()
    assert handler._stream is sys.stdout  # noqa: SLF001


def test_stream_handler_drops_below_level() -> None:
    stream = io.StringIO()
    handler = StreamHandler(stream=stream, level=WARNING)
    handler.emit(INFO, "boot", "ignored")
    assert stream.getvalue() == ""


def test_stream_handler_level_property_round_trips() -> None:
    handler = StreamHandler(level=WARNING)
    assert handler.level == WARNING
    handler.level = DEBUG
    assert handler.level == DEBUG


def test_stream_handler_custom_formatter() -> None:
    stream = io.StringIO()

    def upper(level: int, name: str, message: str) -> str:
        return f"{level_name(level).lower()} {name} {message}".upper()

    handler = StreamHandler(stream=stream, formatter=upper)
    handler.emit(INFO, "boot", "ready")
    assert stream.getvalue() == "INFO BOOT READY\n"


def test_stream_handler_calls_flush_when_available() -> None:
    flushes = {"count": 0}

    class _FlushingStream:
        def __init__(self) -> None:
            self._buffer: list = []

        def write(self, text: str) -> None:
            self._buffer.append(text)

        def flush(self) -> None:
            flushes["count"] += 1

        @property
        def value(self) -> str:
            return "".join(self._buffer)

    stream = _FlushingStream()
    handler = StreamHandler(stream=stream)
    handler.emit(INFO, "x", "y")
    assert stream.value == "INFO:x:y\n"
    assert flushes["count"] == 1


def test_stream_handler_skips_flush_when_unavailable() -> None:
    class _NoFlushStream:
        def __init__(self) -> None:
            self.text = ""

        def write(self, value: str) -> None:
            self.text += value

    stream = _NoFlushStream()
    handler = StreamHandler(stream=stream)
    handler.emit(INFO, "x", "y")
    assert stream.text == "INFO:x:y\n"


# ---------------------------------------------------------------------------
# BufferedHandler
# ---------------------------------------------------------------------------


def test_buffered_handler_capacity_must_be_positive() -> None:
    downstream = RecordingHandler()
    with raises(ValueError):
        BufferedHandler(downstream=downstream, capacity=0)


def test_buffered_handler_starts_empty() -> None:
    downstream = RecordingHandler()
    handler = BufferedHandler(downstream=downstream, capacity=4)
    assert handler.buffered == 0
    assert handler.dropped == 0
    assert handler.capacity == 4
    assert handler.check(now_ms=0) is False


def test_buffered_handler_buffers_records_without_emitting() -> None:
    downstream = RecordingHandler()
    handler = BufferedHandler(downstream=downstream, capacity=4)
    handler.emit(INFO, "x", "a")
    handler.emit(INFO, "x", "b")
    assert handler.buffered == 2
    assert handler.check(now_ms=0) is True
    assert downstream.records == []


def test_buffered_handler_handle_drains_buffer_to_downstream() -> None:
    downstream = RecordingHandler()
    handler = BufferedHandler(downstream=downstream, capacity=4)
    handler.emit(INFO, "x", "a")
    handler.emit(INFO, "x", "b")
    flushed = handler.handle(now_ms=0)
    assert flushed == 2
    assert handler.buffered == 0
    assert handler.check(now_ms=0) is False
    assert downstream.records == [(INFO, "x", "a"), (INFO, "x", "b")]


def test_buffered_handler_drops_oldest_when_full() -> None:
    downstream = RecordingHandler()
    handler = BufferedHandler(downstream=downstream, capacity=2)
    handler.emit(INFO, "x", "a")
    handler.emit(INFO, "x", "b")
    handler.emit(INFO, "x", "c")
    assert handler.dropped == 1
    handler.handle(now_ms=0)
    assert downstream.records == [(INFO, "x", "b"), (INFO, "x", "c")]


def test_buffered_handler_drops_below_level_silently() -> None:
    downstream = RecordingHandler()
    handler = BufferedHandler(downstream=downstream, capacity=4, level=WARNING)
    handler.emit(INFO, "x", "low")
    assert handler.buffered == 0
    handler.emit(WARNING, "x", "high")
    assert handler.buffered == 1


def test_buffered_handler_level_property_round_trips() -> None:
    downstream = RecordingHandler()
    handler = BufferedHandler(downstream=downstream, capacity=4, level=WARNING)
    assert handler.level == WARNING
    handler.level = DEBUG
    assert handler.level == DEBUG
    handler.emit(INFO, "x", "ok")
    assert handler.buffered == 1


def test_buffered_handler_handle_on_empty_buffer_is_noop() -> None:
    downstream = RecordingHandler()
    handler = BufferedHandler(downstream=downstream, capacity=4)
    flushed = handler.handle(now_ms=0)
    assert flushed == 0
    assert downstream.records == []


def test_buffered_handler_runner_shape_via_logger() -> None:
    """End-to-end: Logger -> BufferedHandler -> downstream RecordingHandler."""
    downstream = RecordingHandler()
    buffered = BufferedHandler(downstream=downstream, capacity=8)
    logger = Logger("root", level=DEBUG, handlers=[buffered])
    logger.info("a")
    logger.warning("b")
    assert downstream.records == []
    assert buffered.check(now_ms=0) is True
    buffered.handle(now_ms=0)
    assert downstream.records == [
        (INFO, "root", "a"),
        (WARNING, "root", "b"),
    ]


# ---------------------------------------------------------------------------
# RecordingHandler / FailingHandler (testing helpers cover their own surface)
# ---------------------------------------------------------------------------


def test_recording_handler_respects_level_filter() -> None:
    handler = RecordingHandler(level=WARNING)
    handler.emit(INFO, "x", "low")
    handler.emit(ERROR, "x", "high")
    assert handler.records == [(ERROR, "x", "high")]


def test_recording_handler_clear_drops_buffered_records() -> None:
    handler = RecordingHandler()
    handler.emit(INFO, "x", "a")
    handler.clear()
    assert handler.records == []


def test_recording_handler_records_property_returns_copy() -> None:
    handler = RecordingHandler()
    handler.emit(INFO, "x", "a")
    snapshot = handler.records
    handler.emit(INFO, "x", "b")
    assert snapshot == [(INFO, "x", "a")]


def test_recording_handler_level_property_round_trips() -> None:
    handler = RecordingHandler(level=WARNING)
    assert handler.level == WARNING
    handler.level = DEBUG
    assert handler.level == DEBUG
    handler.emit(INFO, "x", "y")
    assert handler.records == [(INFO, "x", "y")]


def test_failing_handler_uses_default_exception() -> None:
    handler = FailingHandler()
    with raises(RuntimeError, match="handler boom"):
        handler.emit(INFO, "x", "y")
    assert handler.calls == 1


def test_failing_handler_uses_supplied_exception() -> None:
    handler = FailingHandler(exception=ValueError("nope"))
    with raises(ValueError, match="nope"):
        handler.emit(INFO, "x", "y")
