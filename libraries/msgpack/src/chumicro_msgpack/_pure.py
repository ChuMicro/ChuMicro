"""Pure-Python msgpack encoder/decoder.

Selected when the native ``msgpack`` C module is not available.
Supports None, bool, int (32-bit), float (32-bit), str, bytes,
bytearray, list, tuple, and dict.
"""

import struct

# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

# Zero-byte scratch literals reused by _append_packed. Module-level so each
# pack call extends a constant instead of allocating fresh zero bytes.
_ZERO2 = b"\x00\x00"
_ZERO4 = b"\x00\x00\x00\x00"


def _append_packed(buffer: bytearray, fmt: str, value: object, zero: bytes) -> None:
    """Append ``struct.pack(fmt, value)`` to *buffer* with no intermediate bytes object."""
    offset = len(buffer)
    buffer.extend(zero)
    struct.pack_into(fmt, buffer, offset, value)


def _encode(obj: object, buffer: bytearray, depth: int = 0) -> None:
    # Mirror the decoder's depth guard so the encoder refuses nesting the
    # decoder could not read back (which would silently lose persisted data).
    if depth > _MAX_DEPTH:
        raise ValueError("msgpack nesting too deep")
    if obj is True:
        buffer.append(0xc3)
    elif obj is False:
        buffer.append(0xc2)
    elif obj is None:
        buffer.append(0xc0)
    elif isinstance(obj, int):
        _encode_int(obj, buffer)
    elif isinstance(obj, float):
        buffer.append(0xca)
        _append_packed(buffer, ">f", obj, _ZERO4)
    elif isinstance(obj, str):
        _encode_str(obj, buffer)
    elif isinstance(obj, (bytes, bytearray)):
        _encode_bin(obj, buffer)
    elif isinstance(obj, (list, tuple)):
        _encode_array(obj, buffer, depth)
    elif isinstance(obj, dict):
        _encode_map(obj, buffer, depth)
    else:
        raise TypeError(f"unsupported type: {type(obj).__name__}")


def _encode_int(value: int, buffer: bytearray) -> None:
    if 0 <= value <= 0x7f:
        buffer.append(value)
    elif -32 <= value < 0:
        buffer.append(value & 0xff)
    elif 0 <= value <= 0xff:
        buffer.append(0xcc)
        buffer.append(value)
    elif 0 <= value <= 0xffff:
        buffer.append(0xcd)
        _append_packed(buffer, ">H", value, _ZERO2)
    elif 0 <= value <= 0xffffffff:
        buffer.append(0xce)
        _append_packed(buffer, ">I", value, _ZERO4)
    elif -128 <= value < -32:
        buffer.append(0xd0)
        buffer.append(value & 0xff)
    elif -32768 <= value < -128:
        buffer.append(0xd1)
        _append_packed(buffer, ">h", value, _ZERO2)
    elif -2147483648 <= value < -32768:
        buffer.append(0xd2)
        _append_packed(buffer, ">i", value, _ZERO4)
    else:
        raise OverflowError(f"integer out of range for 32-bit msgpack: {value}")


def _encode_str(value: str, buffer: bytearray) -> None:
    encoded = value.encode("utf-8")
    length = len(encoded)
    if length <= 31:
        buffer.append(0xa0 | length)
    elif length <= 0xff:
        buffer.append(0xd9)
        buffer.append(length)
    elif length <= 0xffff:
        buffer.append(0xda)
        _append_packed(buffer, ">H", length, _ZERO2)
    else:
        raise OverflowError(f"string too long for msgpack: {length} bytes")
    buffer.extend(encoded)


def _encode_bin(value: bytes | bytearray, buffer: bytearray) -> None:
    length = len(value)
    if length <= 0xff:
        buffer.append(0xc4)
        buffer.append(length)
    elif length <= 0xffff:
        buffer.append(0xc5)
        _append_packed(buffer, ">H", length, _ZERO2)
    else:
        raise OverflowError(f"bytes too long for msgpack: {length} bytes")
    buffer.extend(value)


def _encode_array(value: list | tuple, buffer: bytearray, depth: int) -> None:
    length = len(value)
    if length <= 15:
        buffer.append(0x90 | length)
    elif length <= 0xffff:
        buffer.append(0xdc)
        _append_packed(buffer, ">H", length, _ZERO2)
    else:
        raise OverflowError(f"array too long for msgpack: {length} elements")
    for item in value:
        _encode(item, buffer, depth + 1)


def _encode_map(value: dict, buffer: bytearray, depth: int) -> None:
    length = len(value)
    if length <= 15:
        buffer.append(0x80 | length)
    elif length <= 0xffff:
        buffer.append(0xde)
        _append_packed(buffer, ">H", length, _ZERO2)
    else:
        raise OverflowError(f"map too long for msgpack: {length} entries")
    for key, val in value.items():
        _encode(key, buffer, depth + 1)
        _encode(val, buffer, depth + 1)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

# Decoder recursion cap. MicroPython on a Pi Pico W exhausts pystack near
# 17 nested containers, so 8 stays clear while covering real payloads (2-4 deep).
_MAX_DEPTH = 8
_MALFORMED = "malformed msgpack: truncated or over-length framing"

# Short reads raise IndexError everywhere, plus struct.error on CPython only
# (MicroPython / CircuitPython raise ValueError and expose no struct.error).
_FRAMING_ERRORS = (IndexError,)
if hasattr(struct, "error"):
    _FRAMING_ERRORS = (IndexError, struct.error)


def _bounded_end(data: memoryview, start: int, length: int) -> int:
    """Return ``start + length``, or raise ValueError if it runs past *data*."""
    end = start + length
    # A memoryview slice truncates silently, so an over-length claim would
    # read short instead of erroring without this check.
    if end > len(data):
        raise ValueError(_MALFORMED)
    return end


def _decode(data: memoryview, offset: int, depth: int) -> tuple:
    """Decode one msgpack value from *data* at *offset*; return ``(value, new_offset)``."""
    if depth > _MAX_DEPTH:
        raise ValueError("msgpack nesting too deep")
    byte = data[offset]

    # positive fixint  (0x00 - 0x7f)
    if byte <= 0x7f:
        return byte, offset + 1

    # fixmap  (0x80 - 0x8f)
    if byte <= 0x8f:
        return _decode_map(data, offset + 1, byte & 0x0f, depth)

    # fixarray  (0x90 - 0x9f)
    if byte <= 0x9f:
        return _decode_array(data, offset + 1, byte & 0x0f, depth)

    # fixstr  (0xa0 - 0xbf)
    if byte <= 0xbf:
        length = byte & 0x1f
        start = offset + 1
        end = _bounded_end(data, start, length)
        return str(data[start:end], "utf-8"), end

    # nil
    if byte == 0xc0:
        return None, offset + 1

    # false / true
    if byte == 0xc2:
        return False, offset + 1
    if byte == 0xc3:
        return True, offset + 1

    # bin8
    if byte == 0xc4:
        length = data[offset + 1]
        start = offset + 2
        end = _bounded_end(data, start, length)
        return bytes(data[start:end]), end

    # bin16
    if byte == 0xc5:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        start = offset + 3
        end = _bounded_end(data, start, length)
        return bytes(data[start:end]), end

    # float32
    if byte == 0xca:
        return struct.unpack_from(">f", data, offset + 1)[0], offset + 5

    # uint8
    if byte == 0xcc:
        return data[offset + 1], offset + 2

    # uint16
    if byte == 0xcd:
        return struct.unpack_from(">H", data, offset + 1)[0], offset + 3

    # uint32
    if byte == 0xce:
        return struct.unpack_from(">I", data, offset + 1)[0], offset + 5

    # int8
    if byte == 0xd0:
        return struct.unpack_from(">b", data, offset + 1)[0], offset + 2

    # int16
    if byte == 0xd1:
        return struct.unpack_from(">h", data, offset + 1)[0], offset + 3

    # int32
    if byte == 0xd2:
        return struct.unpack_from(">i", data, offset + 1)[0], offset + 5

    # str8
    if byte == 0xd9:
        length = data[offset + 1]
        start = offset + 2
        end = _bounded_end(data, start, length)
        return str(data[start:end], "utf-8"), end

    # str16
    if byte == 0xda:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        start = offset + 3
        end = _bounded_end(data, start, length)
        return str(data[start:end], "utf-8"), end

    # array16
    if byte == 0xdc:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        return _decode_array(data, offset + 3, length, depth)

    # map16
    if byte == 0xde:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        return _decode_map(data, offset + 3, length, depth)

    # negative fixint  (0xe0 - 0xff)
    if byte >= 0xe0:
        return byte - 256, offset + 1

    raise _unsupported_byte_error(byte)


def _unsupported_byte_error(byte: int) -> ValueError:
    """Return the ValueError for a *byte* that no decode branch matched."""
    # Local, not module-level, so the table costs no import-time RAM on the
    # healthy path that never hits an out-of-subset byte.
    out_of_subset = {
        0xcb: ("float64", "encode with msgpack.packb(obj, use_single_float=True)"),
        0xcf: ("uint64", "keep integers in [-2**31, 2**32-1]"),
        0xd3: ("int64", "keep integers in [-2**31, 2**32-1]"),
        0xc6: ("bin32", "bytes payloads must be under 65 536 bytes"),
        0xdb: ("str32", "strings must be under 65 536 bytes"),
        0xdd: ("array32", "arrays must be under 65 536 elements"),
        0xdf: ("map32", "maps must be under 65 536 entries"),
    }
    guidance = out_of_subset.get(byte)
    if guidance is not None:
        name, fix = guidance
        return ValueError(f"{name} (0x{byte:02x}) not in chumicro msgpack subset; {fix}")
    return ValueError(f"unsupported msgpack type byte: 0x{byte:02x}")


def _decode_array(data: memoryview, offset: int, length: int, depth: int) -> tuple:
    """Decode *length* array elements starting at *offset*; return ``(list, new_offset)``."""
    # Each element is at least one byte, so a length past the remaining buffer
    # is malformed. Reject before the loop allocates a huge list from garbage.
    if length > len(data) - offset:
        raise ValueError(_MALFORMED)
    result = []
    for _ in range(length):
        value, offset = _decode(data, offset, depth + 1)
        result.append(value)
    return result, offset


def _decode_map(data: memoryview, offset: int, length: int, depth: int) -> tuple:
    """Decode *length* map key/value pairs starting at *offset*; return ``(dict, new_offset)``."""
    # Each pair is at least two bytes, so a length past the remaining buffer
    # (using a conservative 1-byte bound) is malformed. Reject before allocating.
    if length > len(data) - offset:
        raise ValueError(_MALFORMED)
    result = {}
    for _ in range(length):
        key, offset = _decode(data, offset, depth + 1)
        value, offset = _decode(data, offset, depth + 1)
        # A container key is valid msgpack but unhashable; raise the documented
        # ValueError instead of letting result[key]'s TypeError escape.
        if isinstance(key, (list, dict)):
            raise ValueError("msgpack map key is not hashable")
        result[key] = value
    return result, offset


# ---------------------------------------------------------------------------
# Public API: bytes-based
# ---------------------------------------------------------------------------

def packb(obj: object) -> bytes:
    """Pack *obj* to msgpack bytes.

    Args:
        obj: Python object to serialize.

    Returns:
        Msgpack-encoded data.
    """
    buffer = bytearray()
    _encode(obj, buffer)
    return bytes(buffer)


def unpackb(data: bytes | bytearray | memoryview) -> object:
    """Unpack msgpack *data* to a Python object.

    This decoder trusts the payload's type shape but is safe against
    malformed framing (bad framing and over-deep nesting raise
    ``ValueError``). An array or map length is checked only against the
    remaining buffer, so do not unpack an unbounded peer-supplied blob
    (an MQTT payload, an HTTP body) without first bounding its length.

    Args:
        data: Msgpack-encoded data.

    Returns:
        Deserialized Python object.

    Raises:
        ValueError: On truncated or over-length framing, nesting beyond
            the decoder's depth bound, or bytes left over after one
            complete object.
    """
    if not isinstance(data, memoryview):
        data = memoryview(data)
    try:
        result, end = _decode(data, 0, 0)
    except _FRAMING_ERRORS as framing_error:
        # A truncated multi-byte length header read past the buffer end.
        raise ValueError(_MALFORMED) from framing_error
    # Trailing bytes are rejected at the top level only. The recursive
    # core legitimately stops mid-buffer inside a container.
    if end != len(data):
        raise ValueError("trailing bytes after msgpack value")
    return result


# ---------------------------------------------------------------------------
# Public API: stream-based
# ---------------------------------------------------------------------------

def pack(obj: object, stream: object) -> None:
    """Pack *obj* to *stream* in msgpack format.

    Args:
        obj: Python object to serialize.
        stream: Writable stream with a ``write()`` method.
    """
    stream.write(packb(obj))


def unpack(stream: object) -> object:
    """Unpack a single object from *stream*.

    Reads the entire stream and decodes it as exactly one object, so
    trailing bytes raise ``ValueError`` and it cannot read one record
    from a multi-object or still-open stream. For framed or multi-object
    data, bound a slice yourself and use :func:`unpackb`.

    Args:
        stream: Readable stream with a ``read()`` method.

    Returns:
        Deserialized Python object.

    Raises:
        ValueError: Truncated framing, or bytes past the first object.
    """
    return unpackb(stream.read())
