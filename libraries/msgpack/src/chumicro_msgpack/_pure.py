"""Pure-Python msgpack encoder/decoder.

Selected when the native ``msgpack`` C module is not available.
Supports None, bool, int (32-bit), float (32-bit), str, bytes,
bytearray, list, tuple, and dict.
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

    ``struct.pack`` returns a fresh ``bytes`` object per call. ``pack_into``
    writes into a pre-extended slice instead. *zero* is a module-level
    zero-byte literal of the right size for *fmt*.
    """
    offset = len(buffer)
    buffer.extend(zero)
    struct.pack_into(fmt, buffer, offset, value)


def _encode(obj: object, buffer: bytearray, depth: int = 0) -> None:
    """Append the msgpack encoding of *obj* to *buffer*.

    *depth* mirrors the decoder's recursion counter so the encoder
    refuses nesting the decoder would later reject.  Without this guard
    ``packb`` accepts data ``unpackb`` cannot read back, and a store
    that persisted it loses it silently on the next load.
    """
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


def _encode_array(value: list | tuple, buffer: bytearray, depth: int) -> None:
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
        _encode(item, buffer, depth + 1)


def _encode_map(value: dict, buffer: bytearray, depth: int) -> None:
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
        _encode(key, buffer, depth + 1)
        _encode(val, buffer, depth + 1)


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

# Cap on decoder recursion depth. A Pi Pico W under MicroPython
# exhausts pystack at 17 nested containers, so the guard has to trip
# well below that on the smallest supported board. 8 leaves room for
# realistic persisted config / kvstore payloads (which nest 2-4 deep)
# while staying safely under the stack ceiling.
_MAX_DEPTH = 8
_MALFORMED = "malformed msgpack: truncated or over-length framing"

# A truncated multi-byte header reads past the buffer.  ``data[offset+1]``
# raises IndexError on every runtime; ``struct.unpack_from`` on a short
# buffer raises struct.error on CPython but ValueError on MicroPython /
# CircuitPython, which expose no ``struct.error`` attribute.  The tuple is
# built to match only the types that exist so unpackb can translate the
# CPython case to the ValueError the contract promises; the MP / CP
# ValueError already satisfies it.
_FRAMING_ERRORS = (IndexError,)
if hasattr(struct, "error"):
    _FRAMING_ERRORS = (IndexError, struct.error)


def _bounded_end(data: memoryview, start: int, length: int) -> int:
    """Return ``start + length``, or raise if it runs past *data*.

    A ``memoryview`` slice silently truncates instead of erroring, so
    without this an over-length claim returns a short read rather than
    failing.
    """
    end = start + length
    if end > len(data):
        raise ValueError(_MALFORMED)
    return end


def _decode(data: memoryview, offset: int, depth: int) -> tuple:
    """Decode one msgpack value from *data* at *offset*; return ``(value, new_offset)``."""
    if depth > _MAX_DEPTH:
        raise ValueError("msgpack nesting too deep")
    byte = data[offset]

    # positive fixint  (0x00 – 0x7f)
    if byte <= 0x7f:
        return byte, offset + 1

    # fixmap  (0x80 – 0x8f)
    if byte <= 0x8f:
        return _decode_map(data, offset + 1, byte & 0x0f, depth)

    # fixarray  (0x90 – 0x9f)
    if byte <= 0x9f:
        return _decode_array(data, offset + 1, byte & 0x0f, depth)

    # fixstr  (0xa0 – 0xbf)
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

    # negative fixint  (0xe0 – 0xff)
    if byte >= 0xe0:
        return byte - 256, offset + 1

    out_of_subset = _OUT_OF_SUBSET.get(byte)
    if out_of_subset is not None:
        name, fix = out_of_subset
        raise ValueError(f"{name} (0x{byte:02x}) not in chumicro msgpack subset; {fix}")

    raise ValueError(f"unsupported msgpack type byte: 0x{byte:02x}")


def _decode_array(data: memoryview, offset: int, length: int, depth: int) -> tuple:
    """Decode *length* array elements starting at *offset*; return ``(list, new_offset)``."""
    # Every element is at least one byte, so a claimed length past the
    # remaining buffer is malformed framing. Reject before the loop
    # allocates a giant list from corrupt input.
    if length > len(data) - offset:
        raise ValueError(_MALFORMED)
    result = []
    for _ in range(length):
        value, offset = _decode(data, offset, depth + 1)
        result.append(value)
    return result, offset


def _decode_map(data: memoryview, offset: int, length: int, depth: int) -> tuple:
    """Decode *length* map key/value pairs starting at *offset*; return ``(dict, new_offset)``."""
    # Each pair is at least two bytes, so a claimed length past the
    # remaining buffer (using the conservative 1-byte-per-entry bound)
    # is malformed framing. Reject before the loop allocates from
    # corrupt input.
    if length > len(data) - offset:
        raise ValueError(_MALFORMED)
    result = {}
    for _ in range(length):
        key, offset = _decode(data, offset, depth + 1)
        value, offset = _decode(data, offset, depth + 1)
        # A map key that decoded to a container is structurally valid
        # msgpack but unusable as a dict key; surface it as the
        # documented ValueError rather than letting the raw TypeError
        # from result[key] escape the untrusted-input contract.
        if isinstance(key, (list, dict)):
            raise ValueError("msgpack map key is not hashable")
        result[key] = value
    return result, offset


# ---------------------------------------------------------------------------
# Public API — bytes-based
# ---------------------------------------------------------------------------

def packb(obj: object) -> bytes:
    """Pack *obj* to msgpack bytes.

    Allocates a temporary ``bytearray`` that grows during encoding,
    then copies to ``bytes``.  On this pure-Python path ``pack(obj,
    stream)`` does not avoid that allocation — it calls ``packb`` and
    writes the result — so there is no allocation reason to prefer it
    here; the no-intermediate-buffer property holds only on the native
    CircuitPython encoder.

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

    This is a *trusting* decoder, not a spec validator.  It is safe
    against malformed framing (truncated, over-length, or
    trailing-garbage input, and unbounded nesting, all raise
    ``ValueError`` rather than returning a silently-wrong result).
    It does not check that a structurally-valid payload has the type
    shape the caller expects.  Code persisting corruption- or
    attacker-reachable bytes (e.g. flash-backed config) still owns
    type-shape validation of what comes back.  It also owns a size
    bound on attacker-controlled input: an array / map element count
    is checked only against the remaining buffer, so an N-byte payload
    can allocate an N-element container (roughly 8N bytes of pointers
    on a 256 KB board).  Do not ``unpackb`` an unbounded peer-supplied
    blob — an MQTT payload, an HTTP body — without first bounding its
    length.

    Args:
        data: Msgpack-encoded data.

    Returns:
        Deserialized Python object.

    Raises:
        ValueError: On truncated / over-length framing, nesting beyond
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
# Public API — stream-based
# ---------------------------------------------------------------------------

def pack(obj: object, stream: object) -> None:
    """Pack *obj* to *stream* in msgpack format.

    On this pure-Python path the whole object is encoded to a ``bytes``
    first and then written in one call, so it allocates the same as
    ``packb`` (plus the write); it is not the lower-allocation option
    the native encoder makes it.

    Args:
        obj: Python object to serialize.
        stream: Writable stream with a ``write()`` method.
    """
    stream.write(packb(obj))


def unpack(stream: object) -> object:
    """Unpack a single object from *stream*.

    On this pure-Python path the ENTIRE stream is read and decoded as
    exactly one object: trailing bytes past the first object raise
    ``ValueError``, and the read consumes everything (so it can't unpack
    one object from a multi-object or still-open stream, and blocks on a
    live socket until close).  The native CircuitPython decoder instead
    reads incrementally and leaves the rest in the stream — so a
    multi-record stream only works on the native path.  For framed or
    multi-object data, drive :func:`unpackb` over an explicitly-bounded
    slice instead.

    Args:
        stream: Readable stream with a ``read()`` method.

    Returns:
        Deserialized Python object.

    Raises:
        ValueError: Truncated framing, or bytes past the first object.
    """
    return unpackb(stream.read())
