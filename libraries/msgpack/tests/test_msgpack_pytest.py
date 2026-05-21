"""CPython-only msgpack tests that allocate large structures.

These tests exercise overflow paths in the encoder that require 65536+
element structures.  They are excluded from cross-runtime tests
(MicroPython / CircuitPython) because the allocations exceed the
available heap on constrained runtimes.  The file is named
``_pytest.py`` (CPython-only) rather than the bare ``test_`` form
picked up by the cross-runtime harness.

This file also pins the wire-compatibility contract with PyPI
``msgpack`` (see ``test_byte_identity_*`` below).  That contract is
load-bearing for ``chumicro-workspace`` — its host-side writer uses
``msgpack.packb(obj, use_single_float=True)`` to produce bytes the
device-side ``chumicro_msgpack.unpackb`` must read.  If the contract
breaks, host-encoded runtime configs become unreadable on the board.
"""

#: CPython-only lane (pytest fixtures / host stdlib); not cross-runtime.
__chumicro_runtimes__ = ("cpython",)

import pytest
from chumicro_msgpack import packb
from chumicro_test_harness import raises


def test_string_too_long_raises() -> None:
    """Strings exceeding 65535 bytes should raise OverflowError."""
    with raises(OverflowError):
        packb("a" * 65536)


def test_bytes_too_long_raises() -> None:
    """Bytes exceeding 65535 should raise OverflowError."""
    with raises(OverflowError):
        packb(b"\x00" * 65536)


def test_array_too_long_raises() -> None:
    """Arrays exceeding 65535 elements should raise OverflowError."""
    with raises(OverflowError):
        packb([None] * 65536)


def test_map_too_long_raises() -> None:
    """Maps exceeding 65535 entries should raise OverflowError."""
    with raises(OverflowError):
        packb({index: None for index in range(65536)})


# ---------------------------------------------------------------------------
# Wire-compatibility contract — see module docstring.
# ---------------------------------------------------------------------------

def _payloads() -> list[object]:
    """Return a representative set of subset-conforming payloads."""
    return [
        # Singletons
        None, True, False,
        # Integers — every encoder branch
        0, 1, 127,                              # positive fixint
        -1, -32,                                # negative fixint
        128, 255,                               # uint8
        256, 65535,                             # uint16
        65536, 2**32 - 1,                       # uint32
        -33, -128,                              # int8
        -129, -32768,                           # int16
        -32769, -(2**31),                       # int32
        # Floats (float32 round-trippable)
        0.0, -1.5, 0.5,
        # Strings
        "", "a" * 31, "b" * 32, "c" * 255, "d" * 256,
        # Bytes
        b"", b"\x01\x02", bytes(255), bytes(256),
        # Arrays
        [], [1, 2, 3], list(range(15)), list(range(16)),
        # Maps
        {}, {0: "ssid", 1: "pw"}, {"a": 1, "b": 2},
        # Realistic runtime-config shape
        {
            "wifi": {"ssid": "MyNet", "password": "x"},
            "app": {"flags": {"new_ui": True}, "list": [1, 2, 3]},
        },
    ]


@pytest.mark.parametrize("payload", _payloads())
def test_byte_identity_with_pypi_msgpack(payload: object) -> None:
    """chumicro_msgpack.packb must match msgpack.packb(use_single_float=True).

    Pins the wire-compatibility contract that lets workbench/workspace
    produce runtime-config bytes the device-side reader can decode.
    """
    pypi_msgpack = pytest.importorskip("msgpack")
    chumicro_bytes = packb(payload)
    pypi_bytes = pypi_msgpack.packb(payload, use_single_float=True)
    assert chumicro_bytes == pypi_bytes, (
        f"wire-format drift for {payload!r}: "
        f"chumicro={chumicro_bytes!r} vs pypi={pypi_bytes!r}"
    )
