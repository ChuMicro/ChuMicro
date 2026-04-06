"""Tests for the runtime detection helpers."""

from __future__ import annotations

import chumicro_runtime.platform as platform


def test_runtime_name_matches_cpython() -> None:
    """The current host interpreter should report itself as CPython in these tests."""
    assert platform.runtime_name() == "cpython"
    assert platform.is_cpython() is True
    assert platform.is_micropython() is False
    assert platform.is_circuitpython() is False


def test_runtime_name_can_report_micropython(monkeypatch) -> None:
    """MicroPython detection should come from the implementation name when present."""
    monkeypatch.setattr(platform, "_implementation_name", lambda: "micropython")
    monkeypatch.setattr(platform, "_platform_name", lambda: "esp32")

    assert platform.runtime_name() == "micropython"
    assert platform.is_micropython() is True
    assert platform.is_cpython() is False


def test_runtime_name_can_report_circuitpython(monkeypatch) -> None:
    """CircuitPython detection should come from the implementation name when present."""
    monkeypatch.setattr(platform, "_implementation_name", lambda: "circuitpython")
    monkeypatch.setattr(platform, "_platform_name", lambda: "samd51")

    assert platform.runtime_name() == "circuitpython"
    assert platform.is_circuitpython() is True
    assert platform.is_cpython() is False


def test_runtime_name_falls_back_to_pyboard_platform(monkeypatch) -> None:
    """A pyboard platform without an implementation name is treated as MicroPython."""
    monkeypatch.setattr(platform, "_implementation_name", lambda: "")
    monkeypatch.setattr(platform, "_platform_name", lambda: "pyboard")

    assert platform.runtime_name() == "micropython"


def test_runtime_name_returns_unknown_when_no_signal_exists(monkeypatch) -> None:
    """Unknown runtimes should report an explicit unknown value."""
    monkeypatch.setattr(platform, "_implementation_name", lambda: "")
    monkeypatch.setattr(platform, "_platform_name", lambda: "")

    assert platform.runtime_name() == "unknown"
