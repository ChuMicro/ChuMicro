"""Device-facing tests for msgpack serialization on real hardware.

Validates packb/unpackb roundtrips for all supported types across
CPython, MicroPython, and CircuitPython runtimes.
"""

from chumicro_msgpack import packb, unpackb


def test_roundtrip_none() -> None:
    """None should survive a pack/unpack roundtrip."""
    assert unpackb(packb(None)) is None


def test_roundtrip_booleans() -> None:
    """True and False should survive roundtrips."""
    assert unpackb(packb(True)) is True
    assert unpackb(packb(False)) is False


def test_roundtrip_positive_fixint() -> None:
    """Small positive integers (0-127) use fixint encoding."""
    for value in [0, 1, 42, 127]:
        assert unpackb(packb(value)) == value


def test_roundtrip_negative_fixint() -> None:
    """Small negative integers (-1 to -32) use negative fixint encoding."""
    for value in [-1, -16, -32]:
        assert unpackb(packb(value)) == value


def test_roundtrip_uint8() -> None:
    """Integers 128-255 use uint8 encoding."""
    assert unpackb(packb(128)) == 128
    assert unpackb(packb(255)) == 255


def test_roundtrip_uint16() -> None:
    """Integers 256-65535 use uint16 encoding."""
    assert unpackb(packb(256)) == 256
    assert unpackb(packb(65535)) == 65535


def test_roundtrip_int16() -> None:
    """Negative integers beyond fixint range use int8/int16."""
    assert unpackb(packb(-33)) == -33
    assert unpackb(packb(-128)) == -128
    assert unpackb(packb(-129)) == -129


def test_roundtrip_string() -> None:
    """Strings should roundtrip correctly."""
    assert unpackb(packb("")) == ""
    assert unpackb(packb("hello")) == "hello"
    assert unpackb(packb("chumicro")) == "chumicro"


def test_roundtrip_bytes() -> None:
    """Bytes should roundtrip correctly."""
    data = b"\x00\x01\x02\xff"
    assert unpackb(packb(data)) == data


def test_roundtrip_list() -> None:
    """Lists should roundtrip with correct element types."""
    original = [1, "two", True, None]
    result = unpackb(packb(original))
    assert result == original


def test_roundtrip_dict() -> None:
    """Dicts with string keys should roundtrip correctly."""
    original = {"name": "sensor", "value": 42, "active": True}
    result = unpackb(packb(original))
    assert result == original


def test_roundtrip_nested() -> None:
    """Nested structures should survive roundtrips."""
    original = {"readings": [1, 2, 3], "meta": {"unit": "ms"}}
    result = unpackb(packb(original))
    assert result == original


def test_roundtrip_empty_containers() -> None:
    """Empty list, dict, string, and bytes should roundtrip."""
    assert unpackb(packb([])) == []
    assert unpackb(packb({})) == {}
    assert unpackb(packb("")) == ""
    assert unpackb(packb(b"")) == b""


def test_roundtrip_float() -> None:
    """32-bit floats should survive roundtrip (with float32 precision)."""
    import struct

    value = 3.14
    # Round to float32 precision for comparison.
    expected = struct.unpack(">f", struct.pack(">f", value))[0]
    result = unpackb(packb(value))
    # Compare within float32 precision.
    assert abs(result - expected) < 1e-6


def test_roundtrip_large_string() -> None:
    """A string longer than 31 chars should use str8 or str16 encoding."""
    long_string = "a" * 100
    assert unpackb(packb(long_string)) == long_string
