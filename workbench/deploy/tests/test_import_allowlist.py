"""Tests for the device-built-in module allowlist."""

from __future__ import annotations

from chumicro_deploy.import_allowlist import (
    DEVICE_BUILTIN_MODULES,
    is_device_builtin,
)


def test_core_stdlib_builtins_present() -> None:
    """The always-present runtime built-ins are on the allowlist."""
    for name in ("sys", "gc", "struct", "json", "time", "os", "micropython"):
        assert name in DEVICE_BUILTIN_MODULES


def test_platform_builtins_present_for_both_runtimes() -> None:
    """Platform built-ins from both runtimes are accepted in the union."""
    # CircuitPython side.
    for name in ("wifi", "board", "microcontroller", "socketpool"):
        assert name in DEVICE_BUILTIN_MODULES
    # MicroPython side.
    for name in ("machine", "network", "uos", "utime"):
        assert name in DEVICE_BUILTIN_MODULES


def test_chumicro_library_names_are_not_builtins() -> None:
    """A chumicro library must never be mistaken for a runtime built-in."""
    assert not is_device_builtin("chumicro_sockets")
    assert not is_device_builtin("chumicro_timing")
    assert "chumicro_config" not in DEVICE_BUILTIN_MODULES


def test_is_device_builtin_resolves_top_level_of_dotted_name() -> None:
    """A dotted import is a built-in when its top-level package is one.

    A built-in package owns its whole subtree, so ``collections.deque`` is a
    built-in via ``collections`` while ``chumicro_x.sub`` stays a non-built-in.
    """
    assert is_device_builtin("collections.deque")
    assert is_device_builtin("os.path")
    assert not is_device_builtin("chumicro_x.sub")


def test_allowlist_names_are_lowercase_top_level() -> None:
    """Every entry is a bare lowercase-ish module name, no dotted submodules."""
    for name in DEVICE_BUILTIN_MODULES:
        assert "." not in name
        assert name == name.strip()
