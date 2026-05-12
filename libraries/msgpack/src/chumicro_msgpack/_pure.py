"""Pure-Python msgpack encoder/decoder.

Used by all runtimes when the native ``msgpack`` C module isn't
available — `__init__.py` handles dispatch.  Supports None, bool,
int (32-bit), float (32-bit), str, bytes, bytearray, list, tuple,
and dict.
"""

import struct

# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

# Pre-allocated zero-byte literals used as scratch space by ``_append_packed``.
# Module-level so each pack call extends a constant rather than allocating
# fresh zero bytes.
_ZERO2 = b"\x00\x00"
_ZERO4 = b"\x00\x00\x00\x00"


def _append_packed(buffer: bytearray, fmt: str, value: object, zero: bytes) -> None:
    """Append ``struct.pack(fmt, value)`` to *buffer* without allocating intermediate bytes.

    ``struct.pack`` returns a fresh ``bytes`` object per call; ``pack_into``
    writes into a pre-extended slice instead.  Bench-validated to halve
    per-call heap allocation on MicroPython 1.26 unix-port (64 vs 128 bytes
    per pack).  *zero* is a module-level zero-byte literal of the right
    size for *fmt*.
    """
    offset = len(buffer)
    buffer.extend(zero)
    struct.pack_into(fmt, buffer, offset, value)


def _encode(obj: object, buffer: bytearray) -> None:
    """Append the msgpack encoding of *obj* to *buffer*."""
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
        _encode_array(obj, buffer)
    elif isinstance(obj, dict):
        _encode_map(obj, buffer)
    else:
        raise TypeError(f"unsupported type: {type(obj).__name__}")


def _encode_int(value: int, buffer: bytearray) -> None:
    """Append the msgpack encoding of integer *value* to *buffer*."""
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
    """Append the msgpack encoding of string *value* to *buffer*."""
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
    """Append the msgpack encoding of bytes/bytearray *value* to *buffer*."""
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


def _encode_array(value: list | tuple, buffer: bytearray) -> None:
    """Append *value* to *buffer* as a msgpack array."""
    length = len(value)
    if length <= 15:
        buffer.append(0x90 | length)
    elif length <= 0xffff:
        buffer.append(0xdc)
        _append_packed(buffer, ">H", length, _ZERO2)
    else:
        raise OverflowError(f"array too long for msgpack: {length} elements")
    for item in value:
        _encode(item, buffer)


def _encode_map(value: dict, buffer: bytearray) -> None:
    """Append *value* to *buffer* as a msgpack map."""
    length = len(value)
    if length <= 15:
        buffer.append(0x80 | length)
    elif length <= 0xffff:
        buffer.append(0xde)
        _append_packed(buffer, ">H", length, _ZERO2)
    else:
        raise OverflowError(f"map too long for msgpack: {length} entries")
    for key, val in value.items():
        _encode(key, buffer)
        _encode(val, buffer)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

# Tag bytes that are valid msgpack but outside the chumicro 32-bit /
# 16-bit subset.  Decoding one points the producer at the fix instead
# of saying "unsupported byte".
_OUT_OF_SUBSET = {
    0xcb: ("float64", "encode with msgpack.packb(obj, use_single_float=True)"),
    0xcf: ("uint64", "keep integers in [-2**31, 2**32-1]"),
    0xd3: ("int64", "keep integers in [-2**31, 2**32-1]"),
    0xc6: ("bin32", "bytes payloads must be under 65 536 bytes"),
    0xdb: ("str32", "strings must be under 65 536 bytes"),
    0xdd: ("array32", "arrays must be under 65 536 elements"),
    0xdf: ("map32", "maps must be under 65 536 entries"),
}


def _decode(data: memoryview, offset: int) -> tuple:
    """Decode one msgpack value from *data* at *offset*; return ``(value, new_offset)``."""
    byte = data[offset]

    # positive fixint  (0x00 – 0x7f)
    if byte <= 0x7f:
        return byte, offset + 1

    # fixmap  (0x80 – 0x8f)
    if byte <= 0x8f:
        return _decode_map(data, offset + 1, byte & 0x0f)

    # fixarray  (0x90 – 0x9f)
    if byte <= 0x9f:
        return _decode_array(data, offset + 1, byte & 0x0f)

    # fixstr  (0xa0 – 0xbf)
    if byte <= 0xbf:
        length = byte & 0x1f
        start = offset + 1
        end = start + length
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
        return bytes(data[start:start + length]), start + length

    # bin16
    if byte == 0xc5:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        start = offset + 3
        return bytes(data[start:start + length]), start + length

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
        return str(data[start:start + length], "utf-8"), start + length

    # str16
    if byte == 0xda:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        start = offset + 3
        return str(data[start:start + length], "utf-8"), start + length

    # array16
    if byte == 0xdc:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        return _decode_array(data, offset + 3, length)

    # map16
    if byte == 0xde:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        return _decode_map(data, offset + 3, length)

    # negative fixint  (0xe0 – 0xff)
    if byte >= 0xe0:
        return byte - 256, offset + 1

    out_of_subset = _OUT_OF_SUBSET.get(byte)
    if out_of_subset is not None:
        name, fix = out_of_subset
        raise ValueError(f"{name} (0x{byte:02x}) not in chumicro msgpack subset; {fix}")

    raise ValueError(f"unsupported msgpack type byte: 0x{byte:02x}")


def _decode_array(data: memoryview, offset: int, length: int) -> tuple:
    """Decode *length* array elements starting at *offset*; return ``(list, new_offset)``."""
    result = []
    for _ in range(length):
        value, offset = _decode(data, offset)
        result.append(value)
    return result, offset


def _decode_map(data: memoryview, offset: int, length: int) -> tuple:
    """Decode *length* map key/value pairs starting at *offset*; return ``(dict, new_offset)``."""
    result = {}
    for _ in range(length):
        key, offset = _decode(data, offset)
        value, offset = _decode(data, offset)
        result[key] = value
    return result, offset


# ---------------------------------------------------------------------------
# Public API — bytes-based
# ---------------------------------------------------------------------------

def packb(obj: object) -> bytes:
    """Pack *obj* to msgpack bytes.

    Allocates a temporary ``bytearray`` that grows during encoding,
    then copies to ``bytes``.  For small payloads this is fine; for
    larger data or tight loops, prefer ``pack(obj, stream)`` to write
    directly to a destination without the intermediate allocation.

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

    Args:
        data: Msgpack-encoded data.

    Returns:
        Deserialized Python object.
    """
    if not isinstance(data, memoryview):
        data = memoryview(data)
    result, _ = _decode(data, 0)
    return result


# ---------------------------------------------------------------------------
# Public API — stream-based
# ---------------------------------------------------------------------------
# On CircuitPython with the native ``msgpack`` C module, ``__init__.py``
# imports ``pack`` / ``unpack`` from it directly and never reaches this
# file — so the definitions below are always the pure-Python ones.

def pack(obj: object, stream: object) -> None:
    """Pack *obj* to *stream* in msgpack format.

    Args:
        obj: Python object to serialize.
        stream: Writable stream with a ``write()`` method.
    """
    stream.write(packb(obj))


def unpack(stream: object) -> object:
    """Unpack one object from *stream*.

    Args:
        stream: Readable stream with a ``read()`` method.

    Returns:
        Deserialized Python object.
    """
    return unpackb(stream.read())
