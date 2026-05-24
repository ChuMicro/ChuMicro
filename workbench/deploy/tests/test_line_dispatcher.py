"""Unit tests for the streaming-line dispatcher shared by both transports."""

from __future__ import annotations

from chumicro_deploy._line_dispatcher import StreamingLineDispatcher


class TestStreamingLineDispatcher:
    """Behavior of the per-line dispatcher fed bytes incrementally."""

    def test_dispatches_one_call_per_complete_line(self) -> None:
        """A chunk with two ``\\n``-terminated lines fires on_line twice."""
        lines: list[str] = []
        dispatcher = StreamingLineDispatcher(lines.append)

        dispatcher.feed(b"first\nsecond\n")

        assert lines == ["first", "second"]

    def test_strips_carriage_return_before_newline(self) -> None:
        """Raw REPL ``\\r\\n`` is normalized to ``\\n`` on dispatched lines."""
        lines: list[str] = []
        dispatcher = StreamingLineDispatcher(lines.append)

        dispatcher.feed(b"hello\r\nworld\r\n")

        assert lines == ["hello", "world"]

    def test_buffers_partial_line_across_feeds(self) -> None:
        """A line split across two feeds dispatches once on the closing ``\\n``."""
        lines: list[str] = []
        dispatcher = StreamingLineDispatcher(lines.append)

        dispatcher.feed(b"par")
        dispatcher.feed(b"tial\n")

        assert lines == ["partial"]

    def test_partial_tail_without_newline_holds_until_flush(self) -> None:
        """Trailing bytes without ``\\n`` are buffered until flush is called."""
        lines: list[str] = []
        dispatcher = StreamingLineDispatcher(lines.append)

        dispatcher.feed(b"one\ntwo")
        assert lines == ["one"]

        dispatcher.flush()
        assert lines == ["one", "two"]

    def test_skips_prefix_bytes_across_feeds(self) -> None:
        """``prefix_bytes_to_skip`` is honored even when split across feeds."""
        lines: list[str] = []
        dispatcher = StreamingLineDispatcher(
            lines.append, prefix_bytes_to_skip=2,
        )

        dispatcher.feed(b"O")
        dispatcher.feed(b"Khello\n")

        assert lines == ["hello"]

    def test_stops_dispatch_at_terminator(self) -> None:
        """Bytes after the terminator are ignored, and the pre-terminator
        tail is dispatched as a final partial line."""
        lines: list[str] = []
        dispatcher = StreamingLineDispatcher(
            lines.append, terminator=b"\x04",
        )

        dispatcher.feed(b"line\nhello\x04ignored")
        dispatcher.feed(b"\nstill-ignored")

        assert lines == ["line", "hello"]

    def test_prefix_and_terminator_together_match_cp_raw_repl_envelope(self) -> None:
        """A CircuitPython ``OK<stdout>\\x04<stderr>\\x04>`` frame dispatches
        only the stdout lines between ``OK`` and the first ``\\x04``."""
        lines: list[str] = []
        dispatcher = StreamingLineDispatcher(
            lines.append, prefix_bytes_to_skip=2, terminator=b"\x04",
        )

        dispatcher.feed(b"OKfirst\nsecond\n\x04stderr-bytes\x04>")

        assert lines == ["first", "second"]

    def test_empty_chunk_is_a_noop(self) -> None:
        """Feeding zero bytes neither errors nor dispatches."""
        lines: list[str] = []
        dispatcher = StreamingLineDispatcher(lines.append)

        dispatcher.feed(b"")

        assert lines == []

    def test_flush_after_terminator_is_a_noop(self) -> None:
        """Once the terminator has been seen, later feeds and flush
        dispatch nothing — the partial tail before ``\\x04`` was
        already dispatched at terminator time."""
        lines: list[str] = []
        dispatcher = StreamingLineDispatcher(
            lines.append, terminator=b"\x04",
        )

        dispatcher.feed(b"hello\x04")
        assert lines == ["hello"]

        dispatcher.feed(b"more\n")
        dispatcher.flush()

        assert lines == ["hello"]

    def test_decodes_malformed_utf8_with_replacement(self) -> None:
        """A line containing an invalid UTF-8 byte dispatches with U+FFFD
        rather than raising :class:`UnicodeDecodeError`."""
        lines: list[str] = []
        dispatcher = StreamingLineDispatcher(lines.append)

        dispatcher.feed(b"ok-\xff\n")

        assert lines == ["ok-�"]
