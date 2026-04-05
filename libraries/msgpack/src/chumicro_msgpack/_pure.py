"""Pure-Python msgpack encoder/decoder with native CircuitPython fallback.

Supports: None, bool, int (32-bit), float (32-bit), str, bytes,
bytearray, list, tuple, and dict.
"""

import struct

# ---------------------------------------------------------------------------
# Encoding
# ---------------------------------------------------------------------------

def _encode(obj, buffer):
    """Encode *obj* into msgpack format, appending bytes to *buffer*."""
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
        buffer.extend(struct.pack(">f", obj))
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


def _encode_int(value, buffer):
    """Encode an integer value."""
    if 0 <= value <= 0x7f:
        buffer.append(value)
    elif -32 <= value < 0:
        buffer.append(value & 0xff)
    elif 0 <= value <= 0xff:
        buffer.append(0xcc)
        buffer.append(value)
    elif 0 <= value <= 0xffff:
        buffer.append(0xcd)
        buffer.extend(struct.pack(">H", value))
    elif 0 <= value <= 0xffffffff:
        buffer.append(0xce)
        buffer.extend(struct.pack(">I", value))
    elif -128 <= value < -32:
        buffer.append(0xd0)
        buffer.extend(struct.pack(">b", value))
    elif -32768 <= value < -128:
        buffer.append(0xd1)
        buffer.extend(struct.pack(">h", value))
    elif -2147483648 <= value < -32768:
        buffer.append(0xd2)
        buffer.extend(struct.pack(">i", value))
    else:
        raise OverflowError(f"integer out of range for 32-bit msgpack: {value}")


def _encode_str(value, buffer):
    """Encode a string value."""
    encoded = value.encode("utf-8")
    length = len(encoded)
    if length <= 31:
        buffer.append(0xa0 | length)
    elif length <= 0xff:
        buffer.append(0xd9)
        buffer.append(length)
    elif length <= 0xffff:
        buffer.append(0xda)
        buffer.extend(struct.pack(">H", length))
    else:
        raise OverflowError(f"string too long for msgpack: {length} bytes")
    buffer.extend(encoded)


def _encode_bin(value, buffer):
    """Encode a bytes or bytearray value."""
    length = len(value)
    if length <= 0xff:
        buffer.append(0xc4)
        buffer.append(length)
    elif length <= 0xffff:
        buffer.append(0xc5)
        buffer.extend(struct.pack(">H", length))
    else:
        raise OverflowError(f"bytes too long for msgpack: {length} bytes")
    buffer.extend(value)


def _encode_array(value, buffer):
    """Encode a list or tuple as a msgpack array."""
    length = len(value)
    if length <= 15:
        buffer.append(0x90 | length)
    elif length <= 0xffff:
        buffer.append(0xdc)
        buffer.extend(struct.pack(">H", length))
    else:
        raise OverflowError(f"array too long for msgpack: {length} elements")
    for item in value:
        _encode(item, buffer)


def _encode_map(value, buffer):
    """Encode a dict as a msgpack map."""
    length = len(value)
    if length <= 15:
        buffer.append(0x80 | length)
    elif length <= 0xffff:
        buffer.append(0xde)
        buffer.extend(struct.pack(">H", length))
    else:
        raise OverflowError(f"map too long for msgpack: {length} entries")
    for key, val in value.items():
        _encode(key, buffer)
        _encode(val, buffer)


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def _decode(data, offset):
    """Decode one msgpack value from *data* at *offset*.

    Returns ``(value, new_offset)``.
    """
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
        return bytes(data[start:end]).decode("utf-8"), end

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
        return bytes(data[start:start + length]).decode("utf-8"), start + length

    # str16
    if byte == 0xda:
        length = struct.unpack_from(">H", data, offset + 1)[0]
        start = offset + 3
        return bytes(data[start:start + length]).decode("utf-8"), start + length

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

    raise ValueError(f"unsupported msgpack type byte: 0x{byte:02x}")


def _decode_array(data, offset, length):
    """Decode *length* array elements starting at *offset*."""
    result = []
    for _ in range(length):
        value, offset = _decode(data, offset)
        result.append(value)
    return result, offset


def _decode_map(data, offset, length):
    """Decode *length* map key-value pairs starting at *offset*."""
    result = {}
    for _ in range(length):
        key, offset = _decode(data, offset)
        value, offset = _decode(data, offset)
        result[key] = value
    return result, offset


# ---------------------------------------------------------------------------
# Public API — bytes-based
# ---------------------------------------------------------------------------

def packb(obj):
    """Pack *obj* to msgpack bytes.

    Allocates a temporary ``bytearray`` that grows during encoding,
    then copies to ``bytes``.  For small payloads this is fine; for
    larger data or tight loops, prefer ``pack(obj, stream)`` to write
    directly to a destination without the intermediate allocation.
    """
    buffer = bytearray()
    _encode(obj, buffer)
    return bytes(buffer)


def unpackb(data):
    """Unpack msgpack *data* (bytes, bytearray, or memoryview) to a Python object."""
    if not isinstance(data, memoryview):
        data = memoryview(data)
    result, _ = _decode(data, 0)
    return result


# ---------------------------------------------------------------------------
# Public API — stream-based (native CircuitPython when available)
# ---------------------------------------------------------------------------

try:
    from msgpack import pack, unpack  # CircuitPython C built-in
except ImportError:
    def pack(obj, stream):
        """Pack *obj* to *stream* in msgpack format."""
        stream.write(packb(obj))

    def unpack(stream):
        """Unpack one object from *stream*."""
        return unpackb(stream.read())

