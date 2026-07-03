"""Cross-runtime tests for the board-side marker() print helper.

Plain asserts, no pytest — runs on CPython + MP / CP unix-port + real
silicon like every harness test.  Output capture uses a swapped-in
recorder because MP has no redirect_stdout; marker() takes no stream
parameter (its one job is stdout), so the tests monkeypatch print via
the module's own global.
"""

import chumicro_test_harness.markers as markers_module
from chumicro_test_harness.assertions import raises
from chumicro_test_harness.markers import marker


class _PrintRecorder:
    def __init__(self):
        self.lines = []

    def __call__(self, text):
        self.lines.append(text)


def _capture():
    recorder = _PrintRecorder()
    original = markers_module.print if hasattr(markers_module, "print") else print
    markers_module.print = recorder
    return recorder, original


def _restore(original):
    markers_module.print = original


def test_bare_marker_prints_name_only():
    recorder, original = _capture()
    try:
        marker("CONNECTED")
    finally:
        _restore(original)
    assert recorder.lines == ["CONNECTED"]


def test_values_sorted_and_formatted():
    recorder, original = _capture()
    try:
        marker("WIFI_OK", ip="10.0.0.9", channel=6)
    finally:
        _restore(original)
    assert recorder.lines == ["WIFI_OK channel=6 ip=10.0.0.9"]


def test_bytes_value_rides_as_hex():
    # The exact shape that used to vanish: a payload with a space.
    recorder, original = _capture()
    try:
        marker("ECHO_RECEIVED", bytes=14, payload=b"hello chumicro")
    finally:
        _restore(original)
    assert recorder.lines == [
        "ECHO_RECEIVED bytes=14 payload=68656c6c6f206368756d6963726f",
    ]


def test_whitespace_value_raises():
    with raises(ValueError):
        marker("STATUS", detail="two words")


def test_equals_in_value_raises():
    with raises(ValueError):
        marker("STATUS", detail="a=b")


def test_empty_value_raises():
    with raises(ValueError):
        marker("STATUS", detail="")


def test_reserved_name_raises():
    with raises(ValueError):
        marker("SUMMARY", total=3)


def test_lowercase_name_raises():
    with raises(ValueError):
        marker("ready")
