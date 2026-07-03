"""Tests for the pure-Python msgpack encoder/decoder."""

from io import BytesIO

from chumicro_msgpack import pack, packb, unpack, unpackb

# Tests that pin the pure-subset contract (exact wire bytes, overflow
# rejection, out-of-subset decode rejection) assert against ``_pure``
# directly.  On a CircuitPython board the public ``packb`` /
# ``unpackb`` resolve to the firmware's native ``msgpack`` C module,
# which implements the full spec (not subset-constrained) by design.
# ``_pure`` owns the subset contract and behaves identically on every
# runtime, so these checks stay meaningful on real hardware too.
from chumicro_msgpack._pure import packb as _pure_packb
from chumicro_msgpack._pure import unpackb as _pure_unpackb
from chumicro_test_harness import raises

# ---------------------------------------------------------------------------
# None / bool
# ---------------------------------------------------------------------------

def test_none_roundtrip() -> None:
    """None should survive a pack/unpack roundtrip."""
    assert unpackb(packb(None)) is None


def test_true_roundtrip() -> None:
    """True should survive a pack/unpack roundtrip."""
    assert unpackb(packb(True)) is True


def test_false_roundtrip() -> None:
    """False should survive a pack/unpack roundtrip."""
    assert unpackb(packb(False)) is False


def test_none_encoding() -> None:
    """None should encode to the msgpack nil byte 0xc0."""
    assert packb(None) == b"\xc0"


def test_true_encoding() -> None:
    """True should encode to the msgpack true byte 0xc3."""
    assert packb(True) == b"\xc3"


def test_false_encoding() -> None:
    """False should encode to the msgpack false byte 0xc2."""
    assert packb(False) == b"\xc2"


# ---------------------------------------------------------------------------
# Integers — positive fixint  (0 – 127)
# ---------------------------------------------------------------------------

def test_zero() -> None:
    """Zero should encode to a single 0x00 byte and roundtrip."""
    assert packb(0) == b"\x00"
    assert unpackb(packb(0)) == 0


def test_positive_fixint_boundary() -> None:
    """127 is the upper bound of positive fixint encoding."""
    assert unpackb(packb(127)) == 127
    assert packb(127) == b"\x7f"


# ---------------------------------------------------------------------------
# Integers — negative fixint  (-32 – -1)
# ---------------------------------------------------------------------------

def test_negative_one() -> None:
    """-1 should roundtrip through negative fixint encoding."""
    assert unpackb(packb(-1)) == -1


def test_negative_fixint_boundary() -> None:
    """-32 is the lower bound of negative fixint encoding."""
    assert unpackb(packb(-32)) == -32


# ---------------------------------------------------------------------------
# Integers — uint8  (128 – 255)
# ---------------------------------------------------------------------------

def test_uint8_low() -> None:
    """128 should encode as uint8 (0xcc prefix)."""
    assert _pure_unpackb(_pure_packb(128)) == 128
    assert _pure_packb(128) == b"\xcc\x80"


def test_uint8_high() -> None:
    """255 is the upper bound of uint8 encoding."""
    assert unpackb(packb(255)) == 255


# ---------------------------------------------------------------------------
# Integers — uint16  (256 – 65535)
# ---------------------------------------------------------------------------

def test_uint16_low() -> None:
    """256 should encode as uint16."""
    assert unpackb(packb(256)) == 256


def test_uint16_high() -> None:
    """65535 is the upper bound of uint16 encoding."""
    assert unpackb(packb(65535)) == 65535


# ---------------------------------------------------------------------------
# Integers — uint32  (65536 – 2^32-1)
# ---------------------------------------------------------------------------

def test_uint32_low() -> None:
    """65536 should encode as uint32."""
    assert unpackb(packb(65536)) == 65536


def test_uint32_high() -> None:
    """2^32 - 1 is the upper bound of uint32 encoding."""
    value = 2**32 - 1
    assert _pure_unpackb(_pure_packb(value)) == value


# ---------------------------------------------------------------------------
# Integers — int8  (-128 – -33)
# ---------------------------------------------------------------------------

def test_int8_low() -> None:
    """-33 should encode as int8 (first value below negative fixint range)."""
    assert unpackb(packb(-33)) == -33


def test_int8_high() -> None:
    """-128 is the lower bound of int8 encoding."""
    assert unpackb(packb(-128)) == -128


# ---------------------------------------------------------------------------
# Integers — int16  (-32768 – -129)
# ---------------------------------------------------------------------------

def test_int16_low() -> None:
    """-129 should encode as int16 (first value below int8 range)."""
    assert unpackb(packb(-129)) == -129


def test_int16_high() -> None:
    """-32768 is the lower bound of int16 encoding."""
    assert unpackb(packb(-32768)) == -32768


# ---------------------------------------------------------------------------
# Integers — int32  (-2^31 – -32769)
# ---------------------------------------------------------------------------

def test_int32_low() -> None:
    """-32769 should encode as int32 (first value below int16 range)."""
    assert unpackb(packb(-32769)) == -32769


def test_int32_high() -> None:
    """-2^31 is the lower bound of int32 encoding."""
    value = -(2**31)
    assert _pure_unpackb(_pure_packb(value)) == value


# ---------------------------------------------------------------------------
# Integer overflow
# ---------------------------------------------------------------------------

def test_int_too_large_raises() -> None:
    """Integers above 2^32 - 1 should raise OverflowError."""
    with raises(OverflowError):
        _pure_packb(2**32)


def test_int_too_negative_raises() -> None:
    """Integers below -2^31 should raise OverflowError."""
    with raises(OverflowError):
        _pure_packb(-(2**31) - 1)


# ---------------------------------------------------------------------------
# Float32
# ---------------------------------------------------------------------------

def test_float_roundtrip() -> None:
    """Floats should survive a pack/unpack roundtrip within float32 precision."""
    # float32 has limited precision, so compare after pack/unpack
    packed = packb(3.14)
    result = unpackb(packed)
    assert abs(result - 3.14) < 0.001


def test_float_zero() -> None:
    """Zero float should roundtrip exactly."""
    assert unpackb(packb(0.0)) == 0.0


def test_float_negative() -> None:
    """Negative floats should roundtrip correctly."""
    result = unpackb(packb(-1.5))
    assert result == -1.5


# ---------------------------------------------------------------------------
# Strings
# ---------------------------------------------------------------------------

def test_empty_string() -> None:
    """Empty string should roundtrip."""
    assert unpackb(packb("")) == ""


def test_short_string() -> None:
    """Short strings should roundtrip through fixstr encoding."""
    assert unpackb(packb("hello")) == "hello"


def test_fixstr_boundary() -> None:
    """fixstr supports up to 31 bytes."""
    value = "a" * 31
    assert unpackb(packb(value)) == value


def test_str8() -> None:
    """str8 for strings 32–255 bytes."""
    value = "b" * 100
    assert unpackb(packb(value)) == value


def test_str8_boundary() -> None:
    """255-byte string is the upper bound of str8 encoding."""
    value = "c" * 255
    assert unpackb(packb(value)) == value


def test_str16() -> None:
    """str16 for strings 256–65535 bytes."""
    value = "d" * 300
    assert unpackb(packb(value)) == value


def test_unicode_string() -> None:
    """Multi-byte UTF-8 strings should roundtrip correctly."""
    value = "héllo wörld"
    assert unpackb(packb(value)) == value


# ---------------------------------------------------------------------------
# Bytes / bytearray
# ---------------------------------------------------------------------------

def test_empty_bytes() -> None:
    """Empty bytes should roundtrip."""
    assert unpackb(packb(b"")) == b""


def test_short_bytes() -> None:
    """Short byte sequences should roundtrip."""
    assert unpackb(packb(b"\x01\x02\x03")) == b"\x01\x02\x03"


def test_bytearray_encoded_as_bin() -> None:
    """Bytearrays should encode identically to bytes."""
    value = bytearray(b"\xaa\xbb")
    result = unpackb(packb(value))
    assert result == b"\xaa\xbb"


def test_bin8_boundary() -> None:
    """bin8 supports up to 255 bytes."""
    value = bytes(255)
    assert unpackb(packb(value)) == value


def test_bin16() -> None:
    """Byte sequences exceeding 255 bytes should use bin16 encoding."""
    value = bytes(256)
    assert unpackb(packb(value)) == value


# ---------------------------------------------------------------------------
# Lists / tuples
# ---------------------------------------------------------------------------

def test_empty_list() -> None:
    """Empty list should roundtrip."""
    assert unpackb(packb([])) == []


def test_short_list() -> None:
    """Short lists should roundtrip through fixarray encoding."""
    assert unpackb(packb([1, 2, 3])) == [1, 2, 3]


def test_fixarray_boundary() -> None:
    """15-element list is the upper bound of fixarray encoding."""
    value = list(range(15))
    assert unpackb(packb(value)) == value


def test_array16() -> None:
    """16-element list should use array16 encoding."""
    value = list(range(16))
    assert unpackb(packb(value)) == value


def test_tuple_encoded_as_array() -> None:
    """Tuples are encoded as arrays; decoding always returns lists."""
    result = unpackb(packb((1, "two", 3)))
    assert result == [1, "two", 3]


def test_mixed_type_list() -> None:
    """Lists with mixed types should roundtrip correctly."""
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

def test_empty_dict() -> None:
    """Empty dict should roundtrip."""
    assert unpackb(packb({})) == {}


def test_string_key_dict() -> None:
    """Dicts with string keys should roundtrip."""
    value = {"name": "lamp", "on": True}
    assert unpackb(packb(value)) == value


def test_int_key_dict() -> None:
    """Dicts with integer keys should roundtrip."""
    value = {0: "ssid", 1: "password", 2: True}
    assert unpackb(packb(value)) == value


def test_fixmap_boundary() -> None:
    """15-entry dict is the upper bound of fixmap encoding."""
    value = {index: index * 10 for index in range(15)}
    assert unpackb(packb(value)) == value


def test_map16() -> None:
    """16-entry dict should use map16 encoding."""
    value = {index: index * 10 for index in range(16)}
    assert unpackb(packb(value)) == value


# ---------------------------------------------------------------------------
# Nested structures
# ---------------------------------------------------------------------------

def test_nested_dict() -> None:
    """Nested dicts should roundtrip correctly."""
    value = {"settings": {"ssid": "MyNet", "configured": True}, "version": 1}
    assert unpackb(packb(value)) == value


def test_nested_list_in_dict() -> None:
    """Lists nested inside dicts should roundtrip correctly."""
    value = {"items": [1, 2, 3], "count": 3}
    assert unpackb(packb(value)) == value


def test_dict_in_list() -> None:
    """Dicts nested inside lists should roundtrip correctly."""
    value = [{"a": 1}, {"b": 2}]
    assert unpackb(packb(value)) == value


# ---------------------------------------------------------------------------
# Bool is not int
# ---------------------------------------------------------------------------

def test_bool_not_encoded_as_int() -> None:
    """True/False must encode as msgpack bool, not as int 1/0."""
    assert packb(True) == b"\xc3"
    assert packb(False) == b"\xc2"
    assert packb(1) == b"\x01"
    assert packb(0) == b"\x00"


# ---------------------------------------------------------------------------
# Stream API  (pack / unpack)
# ---------------------------------------------------------------------------

def test_stream_pack_unpack() -> None:
    """Stream-based pack/unpack should roundtrip a dict with nested list."""
    obj = {"key": [1, 2, 3]}
    stream = BytesIO()
    pack(obj, stream)
    stream.seek(0)
    assert unpack(stream) == obj


def test_stream_roundtrip_simple() -> None:
    """Stream-based pack/unpack should roundtrip a simple string."""
    stream = BytesIO()
    pack("hello", stream)
    stream.seek(0)
    assert unpack(stream) == "hello"


# ---------------------------------------------------------------------------
# unpackb accepts various buffer types
# ---------------------------------------------------------------------------

def test_unpackb_bytes() -> None:
    """unpackb should accept bytes input."""
    data = packb(42)
    assert unpackb(data) == 42


def test_unpackb_bytearray() -> None:
    """unpackb should accept bytearray input."""
    data = bytearray(packb(42))
    assert unpackb(data) == 42


def test_unpackb_memoryview() -> None:
    """unpackb should accept memoryview input."""
    data = memoryview(packb(42))
    assert unpackb(data) == 42


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_unsupported_type_raises() -> None:
    """Packing an unsupported type should raise TypeError."""
    with raises(TypeError):
        _pure_packb(object())


def test_unknown_decode_byte_raises() -> None:
    """Decoding a tag byte the decoder doesn't recognize should raise ValueError.

    0xc1 is reserved-and-never-used in the msgpack spec, so it has no
    branch in the decoder. It falls through to the generic
    "unsupported msgpack type byte" raise.
    """
    with raises(ValueError):
        unpackb(b"\xc1")


# ---------------------------------------------------------------------------
# Out-of-subset decode errors — valid msgpack bytes the chumicro subset
# does not accept.  Verifies the decoder names the offending tag in its
# error so producers can fix the upstream encoder.
# ---------------------------------------------------------------------------

def test_float64_decode_raises() -> None:
    """Decoding float64 (0xcb) should raise ValueError naming float64."""
    # 0xcb + 8 bytes of IEEE 754 binary64 for 1.0
    encoded = b"\xcb\x3f\xf0\x00\x00\x00\x00\x00\x00"
    with raises(ValueError, match="float64"):
        _pure_unpackb(encoded)


def test_uint64_decode_raises() -> None:
    """Decoding uint64 (0xcf) should raise ValueError naming uint64."""
    encoded = b"\xcf\x00\x00\x00\x01\x00\x00\x00\x00"  # 2**32
    with raises(ValueError, match="uint64"):
        _pure_unpackb(encoded)


def test_int64_decode_raises() -> None:
    """Decoding int64 (0xd3) should raise ValueError naming int64."""
    encoded = b"\xd3\xff\xff\xff\xfe\xff\xff\xff\xff"  # -(2**32 + 1)
    with raises(ValueError):
        _pure_unpackb(encoded)


def test_bin32_decode_raises() -> None:
    """Decoding bin32 (0xc6) should raise ValueError naming bin32."""
    encoded = b"\xc6\x00\x00\x00\x00"  # zero-length bin32 header
    with raises(ValueError):
        _pure_unpackb(encoded)


def test_str32_decode_raises() -> None:
    """Decoding str32 (0xdb) should raise ValueError naming str32."""
    encoded = b"\xdb\x00\x00\x00\x00"  # zero-length str32 header
    with raises(ValueError):
        _pure_unpackb(encoded)


def test_array32_decode_raises() -> None:
    """Decoding array32 (0xdd) should raise ValueError naming array32."""
    encoded = b"\xdd\x00\x00\x00\x00"  # zero-length array32 header
    with raises(ValueError):
        _pure_unpackb(encoded)


def test_map32_decode_raises() -> None:
    """Decoding map32 (0xdf) should raise ValueError naming map32."""
    encoded = b"\xdf\x00\x00\x00\x00"  # zero-length map32 header
    with raises(ValueError):
        _pure_unpackb(encoded)


# ---------------------------------------------------------------------------
# Malformed framing — the trusting-decoder hardening.
# unpackb must raise ValueError, never return a silently-wrong result,
# on truncation / over-length / trailing-garbage / unbounded nesting.
# Asserted against _pure (the contract owner on every runtime).
# ---------------------------------------------------------------------------

def test_truncated_bin8_raises() -> None:
    """A bin8 claiming more bytes than remain raises, not a short read.

    Wire bytes: 0xc4 (bin8 tag) + length 0xc8 (200) + 2 payload bytes.
    """
    with raises(ValueError):
        _pure_unpackb(b"\xc4\xc8\x01\x02")


def test_truncated_str8_raises() -> None:
    """A str8 claiming more bytes than remain raises."""
    with raises(ValueError):
        _pure_unpackb(b"\xd9\x10ab")  # claims 16 bytes, supplies 2


def test_truncated_fixstr_raises() -> None:
    """A fixstr claiming more bytes than remain raises."""
    with raises(ValueError):
        _pure_unpackb(b"\xa5ab")  # fixstr length 5, supplies 2


def test_truncated_bin16_raises() -> None:
    """A bin16 whose payload is short raises (length prefix is intact)."""
    with raises(ValueError):
        _pure_unpackb(b"\xc5\x00\x10ab")  # claims 16 bytes, supplies 2


def test_truncated_uint16_header_raises() -> None:
    """A uint16 tag with one of its two value bytes missing raises ValueError.

    The multi-byte header itself is truncated (not a payload): on CPython
    struct.unpack_from raises struct.error, which the contract translates
    to ValueError so a caller's ``except ValueError`` catches it.
    """
    with raises(ValueError):
        _pure_unpackb(b"\xcd\x00")  # uint16 tag, 1 of 2 bytes


def test_truncated_bin8_length_header_raises() -> None:
    """A bin8 tag with its length byte missing raises ValueError.

    data[offset + 1] reads past the buffer (IndexError on every runtime).
    """
    with raises(ValueError):
        _pure_unpackb(b"\xc4")  # bin8 tag, no length byte


def test_truncated_str16_header_raises() -> None:
    """A str16 tag with a short length header raises ValueError."""
    with raises(ValueError):
        _pure_unpackb(b"\xda\x00")  # str16 tag, 1 of 2 length bytes


def test_truncated_uint32_header_raises() -> None:
    """A uint32 tag with a short value header raises ValueError."""
    with raises(ValueError):
        _pure_unpackb(b"\xce\x00\x00")  # uint32 tag, 2 of 4 bytes


def test_trailing_bytes_raises() -> None:
    """Bytes left after one complete object raise at the top level.

    Wire bytes: 0x01 decodes as int 1, leaving 3 trailing bytes.
    """
    with raises(ValueError):
        _pure_unpackb(b"\x01\xff\xff\xff")


def test_overlong_fixarray_raises() -> None:
    """A fixarray claiming more elements than bytes remain raises."""
    with raises(ValueError):
        _pure_unpackb(b"\x9f")  # fixarray length 15, no element bytes


def test_overlong_fixmap_raises() -> None:
    """A fixmap claiming more pairs than bytes remain raises."""
    with raises(ValueError):
        _pure_unpackb(b"\x8f")  # fixmap length 15, no pair bytes


def test_overlong_array16_raises() -> None:
    """An array16 claiming more elements than bytes remain raises."""
    with raises(ValueError):
        _pure_unpackb(b"\xdc\xff\xff")  # array16 length 65535, no elements


def test_nesting_too_deep_raises() -> None:
    """Nesting past the decoder's depth bound raises ValueError, not a stack fault.

    The bound (8) is well below where a Pi Pico W under MicroPython
    exhausts pystack (17 nested), so the guard fires first on every
    supported board.
    """
    # 9 nested single-element arrays, one past _MAX_DEPTH (8).
    with raises(ValueError):
        _pure_unpackb(b"\x91" * 9 + b"\x00")


def test_moderate_nesting_still_roundtrips() -> None:
    """The depth bound is above realistic nesting. 4 levels deep roundtrips fine."""
    value = 0
    for _ in range(4):
        value = [value]
    assert _pure_unpackb(_pure_packb(value)) == [[[[0]]]]


def test_encode_refuses_nesting_the_decoder_would_reject() -> None:
    """packb enforces the same depth bound as unpackb, so it never emits
    bytes the same library cannot read back (which a store would persist
    and then lose silently on the next load)."""
    deep = 0
    for _ in range(9):  # one past _MAX_DEPTH (8)
        deep = [deep]
    with raises(ValueError):
        _pure_packb(deep)
    # The deepest value packb DOES accept round-trips cleanly.
    ok = 0
    for _ in range(8):
        ok = [ok]
    assert _pure_unpackb(_pure_packb(ok)) == ok


def test_container_map_key_raises_value_error_not_type_error() -> None:
    """A structurally-valid map with a container key surfaces as ValueError
    (the untrusted-input contract), not a raw TypeError."""
    # {[]: 0} — fixmap len 1, fixarray len 0 (key), 0 (value).
    with raises(ValueError):
        _pure_unpackb(b"\x81\x90\x00")


def test_exact_buffer_no_trailing_roundtrips() -> None:
    """A buffer holding exactly one object (no slack) still decodes."""
    assert _pure_unpackb(_pure_packb({"a": [1, 2], "b": "x"})) == {
        "a": [1, 2], "b": "x",
    }


# ---------------------------------------------------------------------------
# Realistic embedded scenario
# ---------------------------------------------------------------------------

def test_settings_dict_roundtrip() -> None:
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
