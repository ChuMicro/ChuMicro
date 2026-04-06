"""Helpers for detecting the active Python runtime."""

import sys


def _implementation_name():
    """Return the implementation name reported by the active interpreter."""
    implementation = getattr(sys, "implementation", None)
    return getattr(implementation, "name", "")


def _platform_name():
    """Return the platform string reported by the active interpreter."""
    return getattr(sys, "platform", "")


def runtime_name():
    """Return a stable runtime name for CPython, MicroPython, or CircuitPython."""
    implementation_name = _implementation_name()
    if implementation_name:
        return implementation_name

    if _platform_name() == "pyboard":
        return "micropython"

    return "unknown"


def is_cpython():
    """Return whether the active runtime is CPython."""
    return runtime_name() == "cpython"


def is_micropython():
    """Return whether the active runtime is MicroPython."""
    return runtime_name() == "micropython"


def is_circuitpython():
    """Return whether the active runtime is CircuitPython."""
    return runtime_name() == "circuitpython"
