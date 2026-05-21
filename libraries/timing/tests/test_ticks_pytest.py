"""CPython-only tests for tick resolution and runtime simulation.

These tests use ``monkeypatch`` to simulate MicroPython/CircuitPython
runtime environments on CPython.  They do NOT run on MP/CP, since those
runtimes provide the real behavior.

Cross-runtime arithmetic tests live in ``test_ticks.py``.
"""

from __future__ import annotations

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import sys
from types import SimpleNamespace

import chumicro_timing.ticks as ticks_module

# -- _resolve_ticks_ms --


def test_resolve_prefers_supervisor_ticks_ms(monkeypatch) -> None:
    """supervisor.ticks_ms should be chosen first when available."""
    monkeypatch.setitem(
        sys.modules, "supervisor", SimpleNamespace(ticks_ms=lambda: 5678)
    )

    resolved = ticks_module._resolve_ticks_ms()
    assert resolved() == 5678


def test_resolve_skips_non_callable_supervisor_ticks_ms(monkeypatch) -> None:
    """supervisor.ticks_ms should be skipped when it exists but is not callable."""
    monkeypatch.setitem(
        sys.modules, "supervisor", SimpleNamespace(ticks_ms=42)
    )  # int, not callable
    monkeypatch.setattr(
        ticks_module,
        "time",
        SimpleNamespace(ticks_ms=lambda: 9999, monotonic=lambda: 0.0),
    )

    resolved = ticks_module._resolve_ticks_ms()
    assert resolved() == 9999


def test_resolve_falls_back_to_time_ticks_ms(monkeypatch) -> None:
    """time.ticks_ms should be used when supervisor is unavailable."""
    monkeypatch.delitem(sys.modules, "supervisor", raising=False)
    # Block re-import: ImportError raised inside _resolve_ticks_ms.
    monkeypatch.setattr(sys, "path", [])
    monkeypatch.setattr(
        ticks_module,
        "time",
        SimpleNamespace(ticks_ms=lambda: 1234, monotonic=lambda: 0.0),
    )

    resolved = ticks_module._resolve_ticks_ms()
    assert resolved() == 1234


def test_resolve_falls_back_to_monotonic_ns(monkeypatch) -> None:
    """monotonic_ns should be converted to milliseconds when available."""
    monkeypatch.delitem(sys.modules, "supervisor", raising=False)
    monkeypatch.setattr(sys, "path", [])
    monkeypatch.setattr(
        ticks_module,
        "time",
        SimpleNamespace(monotonic_ns=lambda: 9_876_543_210),
    )

    resolved = ticks_module._resolve_ticks_ms()
    assert resolved() == 9876


def test_resolve_falls_back_to_monotonic(monkeypatch) -> None:
    """time.monotonic should be the final fallback."""
    monkeypatch.delitem(sys.modules, "supervisor", raising=False)
    monkeypatch.setattr(sys, "path", [])
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
