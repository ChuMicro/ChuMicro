"""CPython-only msgpack tests that allocate large structures.

These tests exercise overflow paths in the encoder that require 65536+
element structures.  They are excluded from cross-runtime tests
(MicroPython / CircuitPython) because the allocations exceed the
available heap on constrained runtimes.  See Decision 0016.
"""

from chumicro_msgpack import packb
from chumicro_test_harness import raises


def test_string_too_long_raises():
    """Strings exceeding 65535 bytes should raise OverflowError."""
    with raises(OverflowError):
        packb("a" * 65536)


def test_bytes_too_long_raises():
    """Bytes exceeding 65535 should raise OverflowError."""
    with raises(OverflowError):
        packb(b"\x00" * 65536)


def test_array_too_long_raises():
    """Arrays exceeding 65535 elements should raise OverflowError."""
    with raises(OverflowError):
        packb([None] * 65536)


def test_map_too_long_raises():
    """Maps exceeding 65535 entries should raise OverflowError."""
    with raises(OverflowError):
        packb({i: None for i in range(65536)})

