"""Tests for the cross-runtime tick helpers."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

import chumicro_timing.ticks as ticks_module

# -- _try_import_supervisor --


def test_try_import_supervisor_returns_none_when_unavailable(monkeypatch) -> None:
    """The helper should return None when CircuitPython is not present."""
    monkeypatch.delitem(sys.modules, "supervisor", raising=False)

    assert ticks_module._try_import_supervisor() is None


def test_try_import_supervisor_returns_module_when_available(monkeypatch) -> None:
    """The helper should return an already-importable supervisor module."""
    fake_supervisor = SimpleNamespace(ticks_ms=lambda: 123)
    monkeypatch.setitem(sys.modules, "supervisor", fake_supervisor)

    assert ticks_module._try_import_supervisor() is fake_supervisor


# -- _resolve_ticks_ms --


def test_resolve_prefers_supervisor_ticks_ms(monkeypatch) -> None:
    """supervisor.ticks_ms should be chosen first when available."""
    monkeypatch.setattr(
        ticks_module,
        "_try_import_supervisor",
        lambda: SimpleNamespace(ticks_ms=lambda: 5678),
    )

    resolved = ticks_module._resolve_ticks_ms()
    assert resolved() == 5678


def test_resolve_falls_back_to_time_ticks_ms(monkeypatch) -> None:
    """time.ticks_ms should be used when supervisor is unavailable."""
    monkeypatch.setattr(ticks_module, "_try_import_supervisor", lambda: None)
    monkeypatch.setattr(
        ticks_module,
        "time",
        SimpleNamespace(ticks_ms=lambda: 1234, monotonic=lambda: 0.0),
    )

    resolved = ticks_module._resolve_ticks_ms()
    assert resolved() == 1234


def test_resolve_falls_back_to_monotonic_ns(monkeypatch) -> None:
    """monotonic_ns should be converted to milliseconds when available."""
    monkeypatch.setattr(ticks_module, "_try_import_supervisor", lambda: None)
    monkeypatch.setattr(
        ticks_module,
        "time",
        SimpleNamespace(monotonic_ns=lambda: 9_876_543_210),
    )

    resolved = ticks_module._resolve_ticks_ms()
    assert resolved() == 9876


def test_resolve_falls_back_to_monotonic(monkeypatch) -> None:
    """time.monotonic should be the final fallback."""
    monkeypatch.setattr(ticks_module, "_try_import_supervisor", lambda: None)
    monkeypatch.setattr(
        ticks_module,
        "time",
        SimpleNamespace(monotonic=lambda: 1.234),
    )

    resolved = ticks_module._resolve_ticks_ms()
    assert resolved() == 1234


# -- ticks_ms masking --


def test_ticks_ms_masks_to_period(monkeypatch) -> None:
    """Values from the raw source should be masked to 2**29."""
    monkeypatch.setattr(ticks_module, "_raw_ticks_ms", lambda: (1 << 29) + 42)

    assert ticks_module.ticks_ms() == 42


# -- ticks_diff ring arithmetic --


def test_ticks_diff_forward() -> None:
    """A normal forward difference should return the expected positive value."""
    assert ticks_module.ticks_diff(150, 100) == 50


def test_ticks_diff_handles_wraparound() -> None:
    """A difference across the wrap boundary should be computed correctly."""
    period = 1 << 29
    start = period - 10
    end = 5

    assert ticks_module.ticks_diff(end, start) == 15


# -- ticks_add --


def test_ticks_add_normal() -> None:
    """Adding a delta within range should return a plain sum."""
    assert ticks_module.ticks_add(100, 50) == 150


def test_ticks_add_wraps() -> None:
    """Adding past the period boundary should wrap correctly."""
    period = 1 << 29
    assert ticks_module.ticks_add(period - 10, 20) == 10


def test_ticks_add_rejects_overflow() -> None:
    """Deltas at or beyond the half-period should raise OverflowError."""
    halfperiod = 1 << 28

    with pytest.raises(OverflowError):
        ticks_module.ticks_add(0, halfperiod)

    with pytest.raises(OverflowError):
        ticks_module.ticks_add(0, -halfperiod)


# -- _SystemTicks delegation --


def test_system_ticks_delegates_to_module_helpers(monkeypatch) -> None:
    """_SystemTicks should delegate to the module-level functions."""
    monkeypatch.setattr(ticks_module, "ticks_ms", lambda: 4321)
    monkeypatch.setattr(ticks_module, "ticks_diff", lambda end, start: end - start + 1)

    system_ticks = ticks_module._SystemTicks()

    assert system_ticks.ticks_ms() == 4321
    assert system_ticks.ticks_diff(10, 3) == 8

