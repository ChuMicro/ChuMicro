"""Tests for the pure-Python msgpack encoder/decoder."""

from io import BytesIO

from chumicro_msgpack import pack, packb, unpack, unpackb
from chumicro_test_harness import raises

# ---------------------------------------------------------------------------
# None / bool
# ---------------------------------------------------------------------------

def test_none_roundtrip():
    assert unpackb(packb(None)) is None


def test_true_roundtrip():
    assert unpackb(packb(True)) is True


def test_false_roundtrip():
    assert unpackb(packb(False)) is False


def test_none_encoding():
    assert packb(None) == b"\xc0"


def test_true_encoding():
    assert packb(True) == b"\xc3"


def test_false_encoding():
    assert packb(False) == b"\xc2"


# ---------------------------------------------------------------------------
# Integers — positive fixint  (0 – 127)
# ---------------------------------------------------------------------------

def test_zero():
    assert packb(0) == b"\x00"
    assert unpackb(packb(0)) == 0


def test_positive_fixint_boundary():
    assert unpackb(packb(127)) == 127
    assert packb(127) == b"\x7f"


# ---------------------------------------------------------------------------
# Integers — negative fixint  (-32 – -1)
# ---------------------------------------------------------------------------

def test_negative_one():
    assert unpackb(packb(-1)) == -1


def test_negative_fixint_boundary():
    assert unpackb(packb(-32)) == -32


# ---------------------------------------------------------------------------
# Integers — uint8  (128 – 255)
# ---------------------------------------------------------------------------

def test_uint8_low():
    assert unpackb(packb(128)) == 128
    assert packb(128) == b"\xcc\x80"


def test_uint8_high():
    assert unpackb(packb(255)) == 255


# ---------------------------------------------------------------------------
# Integers — uint16  (256 – 65535)
# ---------------------------------------------------------------------------

def test_uint16_low():
    assert unpackb(packb(256)) == 256


def test_uint16_high():
    assert unpackb(packb(65535)) == 65535


# ---------------------------------------------------------------------------
# Integers — uint32  (65536 – 2^32-1)
# ---------------------------------------------------------------------------

def test_uint32_low():
    assert unpackb(packb(65536)) == 65536


def test_uint32_high():
    value = 2**32 - 1
    assert unpackb(packb(value)) == value


# ---------------------------------------------------------------------------
# Integers — int8  (-128 – -33)
# ---------------------------------------------------------------------------

def test_int8_low():
    assert unpackb(packb(-33)) == -33


def test_int8_high():
    assert unpackb(packb(-128)) == -128


# ---------------------------------------------------------------------------
# Integers — int16  (-32768 – -129)
# ---------------------------------------------------------------------------

def test_int16_low():
    assert unpackb(packb(-129)) == -129


def test_int16_high():
    assert unpackb(packb(-32768)) == -32768


# ---------------------------------------------------------------------------
# Integers — int32  (-2^31 – -32769)
# ---------------------------------------------------------------------------

def test_int32_low():
    assert unpackb(packb(-32769)) == -32769


def test_int32_high():
    value = -(2**31)
    assert unpackb(packb(value)) == value


# ---------------------------------------------------------------------------
# Integer overflow
# ---------------------------------------------------------------------------

def test_int_too_large_raises():
    with raises(OverflowError):
        packb(2**32)


def test_int_too_negative_raises():
    with raises(OverflowError):
        packb(-(2**31) - 1)


# ---------------------------------------------------------------------------
# Float32
# ---------------------------------------------------------------------------

def test_float_roundtrip():
    # float32 has limited precision, so compare after pack/unpack
    packed = packb(3.14)
    result = unpackb(packed)
    assert abs(result - 3.14) < 0.001


def test_float_zero():
    assert unpackb(packb(0.0)) == 0.0


def test_float_negative():
    result = unpackb(packb(-1.5))
    assert result == -1.5


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------

def test_empty_string():
    assert unpackb(packb("")) == ""


def test_short_string():
    assert unpackb(packb("hello")) == "hello"


def test_fixstr_boundary():
    """fixstr supports up to 31 bytes."""
    value = "a" * 31
    assert unpackb(packb(value)) == value


def test_str8():
    """str8 for strings 32–255 bytes."""
    value = "b" * 100
    assert unpackb(packb(value)) == value


def test_str8_boundary():
    value = "c" * 255
    assert unpackb(packb(value)) == value


def test_str16():
    """str16 for strings 256–65535 bytes."""
    value = "d" * 300
    assert unpackb(packb(value)) == value


def test_unicode_string():
    value = "héllo wörld"
    assert unpackb(packb(value)) == value


# ---------------------------------------------------------------------------
# Bytes / bytearray
# ---------------------------------------------------------------------------

def test_empty_bytes():
    assert unpackb(packb(b"")) == b""


def test_short_bytes():
    assert unpackb(packb(b"\x01\x02\x03")) == b"\x01\x02\x03"


def test_bytearray_encoded_as_bin():
    value = bytearray(b"\xaa\xbb")
    result = unpackb(packb(value))
    assert result == b"\xaa\xbb"


def test_bin8_boundary():
    """bin8 supports up to 255 bytes."""
    value = bytes(255)
    assert unpackb(packb(value)) == value


def test_bin16():
    value = bytes(256)
    assert unpackb(packb(value)) == value


# ---------------------------------------------------------------------------
# Lists / tuples
# ---------------------------------------------------------------------------

def test_empty_list():
    assert unpackb(packb([])) == []


def test_short_list():
    assert unpackb(packb([1, 2, 3])) == [1, 2, 3]


def test_fixarray_boundary():
    value = list(range(15))
    assert unpackb(packb(value)) == value


def test_array16():
    value = list(range(16))
    assert unpackb(packb(value)) == value


def test_tuple_encoded_as_array():
    """Tuples are encoded as arrays; decoding always returns lists."""
    result = unpackb(packb((1, "two", 3)))
    assert result == [1, "two", 3]


def test_mixed_type_list():
    value = [None, True, 42, -7, 3.14, "hello", b"\x00"]
    result = unpackb(packb(value))
    assert result[0] is None
    assert result[1] is True
    assert result[2] == 42
    assert result[3] == -7
    assert abs(result[4] - 3.14) < 0.001
    assert result[5] == "hello"
    assert result[6] == b"\x00"


# ---------------------------------------------------------------------------
# Dicts
# ---------------------------------------------------------------------------

def test_empty_dict():
    assert unpackb(packb({})) == {}


def test_string_key_dict():
    value = {"name": "lamp", "on": True}
    assert unpackb(packb(value)) == value


def test_int_key_dict():
    value = {0: "ssid", 1: "password", 2: True}
    assert unpackb(packb(value)) == value


def test_fixmap_boundary():
    value = {i: i * 10 for i in range(15)}
    assert unpackb(packb(value)) == value


def test_map16():
    value = {i: i * 10 for i in range(16)}
    assert unpackb(packb(value)) == value


# ---------------------------------------------------------------------------
# Nested structures
# ---------------------------------------------------------------------------

def test_nested_dict():
    value = {"settings": {"ssid": "MyNet", "configured": True}, "version": 1}
    assert unpackb(packb(value)) == value


def test_nested_list_in_dict():
    value = {"items": [1, 2, 3], "count": 3}
    assert unpackb(packb(value)) == value


def test_dict_in_list():
    value = [{"a": 1}, {"b": 2}]
    assert unpackb(packb(value)) == value


# ---------------------------------------------------------------------------
# Bool is not int
# ---------------------------------------------------------------------------

def test_bool_not_encoded_as_int():
    """True/False must encode as msgpack bool, not as int 1/0."""
    assert packb(True) == b"\xc3"
    assert packb(False) == b"\xc2"
    assert packb(1) == b"\x01"
    assert packb(0) == b"\x00"


# ---------------------------------------------------------------------------
# Stream API  (pack / unpack)
# ---------------------------------------------------------------------------

def test_stream_pack_unpack():
    obj = {"key": [1, 2, 3]}
    buf = BytesIO()
    pack(obj, buf)
    buf.seek(0)
    assert unpack(buf) == obj


def test_stream_roundtrip_simple():
    buf = BytesIO()
    pack("hello", buf)
    buf.seek(0)
    assert unpack(buf) == "hello"


# ---------------------------------------------------------------------------
# unpackb accepts various buffer types
# ---------------------------------------------------------------------------

def test_unpackb_bytes():
    data = packb(42)
    assert unpackb(data) == 42


def test_unpackb_bytearray():
    data = bytearray(packb(42))
    assert unpackb(data) == 42


def test_unpackb_memoryview():
    data = memoryview(packb(42))
    assert unpackb(data) == 42


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_unsupported_type_raises():
    with raises(TypeError):
        packb(object())


def test_unsupported_decode_byte_raises():
    # 0xc1 is never-used in msgpack spec
    with raises(ValueError):
        unpackb(b"\xc1")



# ---------------------------------------------------------------------------
# Realistic embedded scenario
# ---------------------------------------------------------------------------

def test_settings_dict_roundtrip():
    """Simulate a typical device settings dict stored via msgpack."""
    settings = {
        0: "MyNetwork",
        1: "secret123",
        2: "lamp",
        3: "192.168.1.100",
        4: True,
    }
    packed = packb(settings)
    assert unpackb(packed) == settings
    # Verify it's much smaller than JSON
    import json
    json_size = len(json.dumps(settings))
    assert len(packed) < json_size
