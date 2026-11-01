"""MessagePack encoder and decoder in pure Python, for runtimes without a built-in ``msgpack`` module."""

import struct

try:
    from micropython import const
except ImportError:
    def const(value):
        return value

_ZERO2 = b"\x00\x00"
_ZERO4 = b"\x00\x00\x00\x00"

# MicroPython on a Pi Pico W runs out of pystack near 17 nested containers.
# A cap of 8 stays clear of it. The encoder and decoder share the cap, so
# packb refuses any value unpackb could not read back.
_MAX_DEPTH = const(8)


def _append_packed(buffer: bytearray, fmt: str, value: object, zero: bytes) -> None:
    offset = len(buffer)
    buffer.extend(zero)
    struct.pack_into(fmt, buffer, offset, value)


def _encode(obj: object, buffer: bytearray, depth: int = 0) -> None:
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


# One decoder contract across the native and pure paths: chumicro_msgpack's
# package __init__ raises this same text verbatim on its native branch.
_MALFORMED = "malformed msgpack: truncated or over-length framing"

# CPython adds struct.error on short reads; MicroPython/CircuitPython lack it.
_FRAMING_ERRORS = (
    (IndexError, struct.error) if hasattr(struct, "error") else (IndexError,)
)


def _bounded_end(data: memoryview, start: int, length: int) -> int:
    end = start + length
    # A memoryview slice truncates silently, so an over-length claim reads short without this check.
    if end > len(data):
        raise ValueError(_MALFORMED)
    return end


def _decode(data: memoryview, offset: int, depth: int) -> tuple:
    if depth > _MAX_DEPTH:
        raise ValueError("msgpack nesting too deep")
    byte = data[offset]

    if byte <= 0x7f:
        return byte, offset + 1

    if byte <= 0x8f:
        return _decode_map(data, offset + 1, byte & 0x0f, depth)

    if byte <= 0x9f:
        return _decode_array(data, offset + 1, byte & 0x0f, depth)

    if byte <= 0xbf:
        length = byte & 0x1f
        start = offset + 1
        end = _bounded_end(data, start, length)
        return str(data[start:end], "utf-8"), end

    if byte == 0xc0:
        return None, offset + 1

    if byte == 0xc2:
        return False, offset + 1
    if byte == 0xc3:
        return True, offset + 1

    if byte == 0xc4:
        length = data[offset + 1]
        start = offset + 2
        end = _bounded_end(data, start, length)
        return bytes(data[start:end]), end

    if byte == 0xc5:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        start = offset + 3
        end = _bounded_end(data, start, length)
        return bytes(data[start:end]), end

    if byte == 0xca:
        return struct.unpack_from(">f", data, offset + 1)[0], offset + 5

    if byte == 0xcc:
        return data[offset + 1], offset + 2

    if byte == 0xcd:
        return struct.unpack_from(">H", data, offset + 1)[0], offset + 3

    if byte == 0xce:
        return struct.unpack_from(">I", data, offset + 1)[0], offset + 5

    if byte == 0xd0:
        return struct.unpack_from(">b", data, offset + 1)[0], offset + 2

    if byte == 0xd1:
        return struct.unpack_from(">h", data, offset + 1)[0], offset + 3

    if byte == 0xd2:
        return struct.unpack_from(">i", data, offset + 1)[0], offset + 5

    if byte == 0xd9:
        length = data[offset + 1]
        start = offset + 2
        end = _bounded_end(data, start, length)
        return str(data[start:end], "utf-8"), end

    if byte == 0xda:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        start = offset + 3
        end = _bounded_end(data, start, length)
        return str(data[start:end], "utf-8"), end

    if byte == 0xdc:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        return _decode_array(data, offset + 3, length, depth)

    if byte == 0xde:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        return _decode_map(data, offset + 3, length, depth)

    if byte >= 0xe0:
        return byte - 256, offset + 1

    raise _unsupported_byte_error(byte)


_OUT_OF_SUBSET = {
    0xcb: ("float64", "encode with msgpack.packb(obj, use_single_float=True)"),
    0xcf: ("uint64", "keep integers in [-2**31, 2**32-1]"),
    0xd3: ("int64", "keep integers in [-2**31, 2**32-1]"),
    0xc6: ("bin32", "bytes payloads must be under 65 536 bytes"),
    0xdb: ("str32", "strings must be under 65 536 bytes"),
    0xdd: ("array32", "arrays must be under 65 536 elements"),
    0xdf: ("map32", "maps must be under 65 536 entries"),
}


def _unsupported_byte_error(byte: int) -> ValueError:
    guidance = _OUT_OF_SUBSET.get(byte)
    if guidance is not None:
        name, fix = guidance
        return ValueError(f"{name} (0x{byte:02x}) not in chumicro msgpack subset; {fix}")
    return ValueError(f"unsupported msgpack type byte: 0x{byte:02x}")


def _decode_array(data: memoryview, offset: int, length: int, depth: int) -> tuple:
    # Each element is at least one byte, so a count past the remaining bytes is malformed.
    if length > len(data) - offset:
        raise ValueError(_MALFORMED)
    result = []
    for _ in range(length):
        value, offset = _decode(data, offset, depth + 1)
        result.append(value)
    return result, offset


def _decode_map(data: memoryview, offset: int, length: int, depth: int) -> tuple:
    # Each pair is at least two bytes (a one-byte key and a one-byte value).
    if length * 2 > len(data) - offset:
        raise ValueError(_MALFORMED)
    result = {}
    for _ in range(length):
        key, offset = _decode(data, offset, depth + 1)
        value, offset = _decode(data, offset, depth + 1)
        # A list or dict key is valid msgpack but unhashable in Python. ValueError
        # keeps every decode failure one exception type.
        if isinstance(key, (list, dict)):
            raise ValueError("msgpack map key is not hashable")
        result[key] = value
    return result, offset


def packb(obj: object) -> bytes:
    """Pack ``obj`` into MessagePack bytes and return them.

    ``packb`` packs ``None``, ``bool``, ``int``, ``float``, ``str``,
    ``bytes``, ``bytearray``, ``list``, ``tuple``, and ``dict``, with each
    value inside at most 8 nested lists, tuples, or dicts. A ``float`` packs
    as 32 bits and keeps about 7 significant digits. A ``tuple`` packs as an
    array and unpacks as a ``list``.

    Args:
        obj: Value to pack.

    Returns:
        The packed bytes.

    Raises:
        TypeError: ``obj`` holds a type outside that list, such as a ``set``.
        OverflowError: An integer lies outside ``-2**31`` to ``2**32 - 1``,
            a ``str`` or ``bytes`` is longer than 65535 bytes, or a list or
            dict holds more than 65535 items.
        ValueError: A value sits inside more than 8 nested lists, tuples,
            or dicts.
    """
    buffer = bytearray()
    _encode(obj, buffer)
    return bytes(buffer)


def unpackb(data: bytes | bytearray | memoryview) -> object:
    """Unpack the one MessagePack value in ``data`` and return it.

    ``unpackb`` reads ``data`` in place through a ``memoryview``. Only the
    ``str`` and ``bytes`` values it returns take new memory. It reads the
    types ``packb`` writes and returns every array as a ``list``.

    Args:
        data: The packed bytes, holding exactly one value.

    Returns:
        The unpacked value.

    Raises:
        ValueError: ``data`` ends inside a value, a length claims more bytes
            than ``data`` holds, bytes remain after the value, a value sits
            inside more than 8 nested arrays or maps, a map key is an array
            or map, or a type byte lies outside what ``packb`` writes, such
            as a 64-bit integer or float.
    """
    if not isinstance(data, memoryview):
        data = memoryview(data)
    try:
        result, end = _decode(data, 0, 0)
    except _FRAMING_ERRORS as framing_error:
        raise ValueError(_MALFORMED) from framing_error
    if end != len(data):
        raise ValueError("trailing bytes after msgpack value")
    return result


def pack(obj: object, stream: object) -> None:
    """Pack ``obj`` and write the bytes to ``stream`` in one ``write()`` call.

    ``pack`` builds the whole packed value in memory first, so it needs as
    much heap as ``packb``. It raises the errors ``packb`` raises.

    Args:
        obj: Value to pack.
        stream: Object with a ``write(bytes)`` method, such as a file opened
            ``"wb"`` or an ``io.BytesIO``.
    """
    stream.write(packb(obj))


def unpack(stream: object) -> object:
    """Read the rest of ``stream`` and unpack the one MessagePack value it holds.

    ``unpack`` calls ``stream.read()`` once and passes the bytes to
    ``unpackb``. The stream holds exactly one value from its current
    position to its end.

    Args:
        stream: Object with a ``read()`` method that returns the remaining
            bytes, such as a file opened ``"rb"`` or an ``io.BytesIO``.

    Returns:
        The unpacked value.

    Raises:
        ValueError: The bytes fail any ``unpackb`` check, including bytes
            left after the value.
    """
    return unpackb(stream.read())
