"""MessagePack serialization for CircuitPython, MicroPython, and CPython.

Implements a subset of the `msgpack specification <https://msgpack.org>`_
suitable for embedded use: integers (up to 32-bit), floats (32-bit),
strings, bytes, booleans, None, lists, tuples, and dicts.

64-bit integers and floats are not supported, matching CircuitPython's
built-in ``msgpack`` module limitation.

Public API
----------
- ``packb(obj)`` — pack a Python object to msgpack bytes.
- ``unpackb(data)`` — unpack msgpack bytes to a Python object.
- ``pack(obj, stream)`` — pack to a writable stream.
- ``unpack(stream)`` — unpack one object from a readable stream.

On CircuitPython boards that include the native ``msgpack`` module,
all four functions delegate to the C implementation.  The pure-Python
encoder in ``_pure`` is never imported, saving ~700 bytes of heap RAM.
"""

from io import BytesIO

try:
    # CircuitPython C built-in — stream-based API.

    from msgpack import pack, unpack  # noqa: F401

    def packb(obj):
        """Pack *obj* to msgpack bytes using the native encoder.

        Allocates a ``BytesIO`` buffer internally.  For small payloads
        this is fine; for larger data or tight loops, prefer
        ``pack(obj, stream)`` to write directly to a destination.
        """
        buffer = BytesIO()
        pack(obj, buffer)
        return buffer.getvalue()

    def unpackb(data):
        """Unpack msgpack *data* to a Python object using the native decoder."""
        return unpack(BytesIO(data))

except ImportError:
    # No native msgpack — load the pure-Python implementation.
    from ._pure import pack, packb, unpack, unpackb  # noqa: F401

__all__ = ["pack", "packb", "unpack", "unpackb"]
