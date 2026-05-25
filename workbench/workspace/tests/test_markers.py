"""Unit tests for the stdout-marker parser and the thread-safe MarkerQueue."""

from __future__ import annotations

import threading
import time

import pytest
from chumicro_workspace.markers import (
    Marker,
    MarkerQueue,
    MarkerTimeoutError,
    parse_marker,
)


class TestParseMarker:
    """Lines accepted and rejected by :func:`parse_marker`."""

    def test_accepts_marker_with_key_value_pairs(self) -> None:
        marker = parse_marker("SERVER_READY ip=192.168.1.50 port=8765")
        assert marker == Marker(
            name="SERVER_READY",
            values={"ip": "192.168.1.50", "port": "8765"},
        )

    def test_accepts_marker_with_no_values(self) -> None:
        marker = parse_marker("READY")
        assert marker == Marker(name="READY", values={})

    def test_accepts_single_letter_marker_name(self) -> None:
        marker = parse_marker("X key=value")
        assert marker == Marker(name="X", values={"key": "value"})

    def test_rejects_empty_line(self) -> None:
        assert parse_marker("") is None

    def test_rejects_lowercase_first_word(self) -> None:
        assert parse_marker("server_ready ip=...") is None

    def test_rejects_leading_whitespace(self) -> None:
        # Markers must sit at the start of the line; leading whitespace
        # disqualifies, so accidental indented prints don't fire host
        # fixtures.
        assert parse_marker("  SERVER_READY ip=...") is None

    def test_rejects_first_word_starting_with_digit(self) -> None:
        assert parse_marker("1FOO bar=baz") is None

    def test_rejects_name_with_lowercase_letter(self) -> None:
        # The regex pins the name to uppercase + digits + underscores.
        # A mixed-case name like ``ServerReady`` would shadow free-form
        # board prose and is disallowed.
        assert parse_marker("ServerReady ip=1") is None

    @pytest.mark.parametrize("reserved", ["PASS", "FAIL", "SKIP", "SUMMARY", "HEAP"])
    def test_rejects_result_parser_reserved_names(self, reserved: str) -> None:
        # `SUMMARY total=N failed=N time=N.Ns` is shaped exactly like a
        # marker; the reserved-name filter is what keeps the marker
        # parser and the result parser from fighting over those lines.
        assert parse_marker(f"{reserved} total=5 failed=0 time=1.234s") is None

    def test_rejects_value_token_without_equals(self) -> None:
        # A trailing free-form word disqualifies the whole line —
        # partial parsing is not the contract.
        assert parse_marker("READY hello world") is None

    def test_rejects_value_token_with_uppercase_key(self) -> None:
        assert parse_marker("READY Key=value") is None

    def test_rejects_value_token_with_embedded_equals(self) -> None:
        # Values are URL-safe (no spaces, no `=`).
        assert parse_marker("READY key=one=two") is None

    def test_pass_fail_lines_do_not_parse_as_markers(self) -> None:
        # Even ignoring the reserved-name filter, the result-parser
        # `PASS test_name (0.123s)` shape isn't `key=value` after the
        # first word and would fail parsing anyway.  Belt-and-suspenders.
        assert parse_marker("PASS test_streaming_ok (0.001s)") is None
        assert parse_marker("FAIL test_x (0.002s, heap +12)") is None


class TestMarkerQueueWaitFor:
    """``wait_for`` returns the matching marker, drops the rest, times out cleanly."""

    def test_returns_marker_already_pushed(self) -> None:
        queue = MarkerQueue()
        marker = Marker(name="SERVER_READY", values={"ip": "10.0.0.1"})
        queue.push(marker)
        assert queue.wait_for("SERVER_READY", timeout_s=1.0) == marker

    def test_drops_non_matching_markers_before_returning_match(self) -> None:
        queue = MarkerQueue()
        queue.push(Marker(name="OTHER", values={"a": "1"}))
        queue.push(Marker(name="ALSO_OTHER"))
        queue.push(Marker(name="SERVER_READY", values={"port": "9001"}))
        result = queue.wait_for("SERVER_READY", timeout_s=1.0)
        assert result.name == "SERVER_READY"
        assert result.values == {"port": "9001"}

    def test_raises_marker_timeout_when_no_match_arrives(self) -> None:
        queue = MarkerQueue()
        queue.push(Marker(name="OTHER"))
        with pytest.raises(MarkerTimeoutError, match=r"SERVER_READY"):
            queue.wait_for("SERVER_READY", timeout_s=0.1)

    def test_raises_marker_timeout_when_queue_stays_empty(self) -> None:
        queue = MarkerQueue()
        with pytest.raises(MarkerTimeoutError, match=r"NEVER_FIRES"):
            queue.wait_for("NEVER_FIRES", timeout_s=0.1)

    def test_blocks_then_returns_when_producer_pushes_late(self) -> None:
        # Concurrent producer (background thread) + consumer (main
        # thread): the queue's thread safety is what the streaming
        # transport's on_line callback relies on when it pushes from
        # the serial-read thread while the test body is waiting.
        queue = MarkerQueue()
        target_marker = Marker(name="SERVER_READY", values={"port": "8080"})

        def producer() -> None:
            time.sleep(0.05)
            queue.push(target_marker)

        producer_thread = threading.Thread(target=producer)
        producer_thread.start()
        try:
            result = queue.wait_for("SERVER_READY", timeout_s=1.0)
        finally:
            producer_thread.join(timeout=1.0)

        assert result == target_marker

    def test_concurrent_producer_can_drown_non_matching_markers(self) -> None:
        # The producer fires three non-matching markers before the one
        # the consumer cares about, all from a different thread.
        # Verifies wait_for keeps pulling and dropping until the match
        # lands, not just looking once.
        queue = MarkerQueue()

        def producer() -> None:
            queue.push(Marker(name="STARTUP"))
            queue.push(Marker(name="HEALTHCHECK"))
            queue.push(Marker(name="HEALTHCHECK"))
            time.sleep(0.02)
            queue.push(Marker(name="SERVER_READY", values={"port": "8000"}))

        producer_thread = threading.Thread(target=producer)
        producer_thread.start()
        try:
            result = queue.wait_for("SERVER_READY", timeout_s=1.0)
        finally:
            producer_thread.join(timeout=1.0)

        assert result.name == "SERVER_READY"
        assert result.values == {"port": "8000"}
