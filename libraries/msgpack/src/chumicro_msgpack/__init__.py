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

CPython's PyPI ``msgpack`` package implements the full upstream
MessagePack spec — 64-bit integers, 32-bit length prefixes,
``strict_map_key=True`` by default — which silently drifts away from
the chumicro 32-bit/16-bit subset.  Delegation to the native module is
therefore gated to CircuitPython, where it's a built-in C module that
faithfully implements the same subset chumicro promises.  CPython
tests + CPython runtime use the pure-Python implementation, keeping
the contract identical across runtimes.
"""

import sys
from io import BytesIO

if sys.implementation.name == "circuitpython":
    try:
        from msgpack import pack, unpack  # noqa: F401

        def packb(obj: object) -> bytes:  # pragma: no cover
            """Pack *obj* to msgpack bytes using the native encoder.

            Allocates a ``BytesIO`` buffer internally.  For small payloads
            this is fine; for larger data or tight loops, prefer
            ``pack(obj, stream)`` to write directly to a destination.

            Args:
                obj: Python object to serialize.

            Returns:
                Msgpack-encoded data.
            """
            buffer = BytesIO()
            pack(obj, buffer)
            return buffer.getvalue()

        def unpackb(data: bytes | bytearray | memoryview) -> object:  # pragma: no cover
            """Unpack msgpack *data* to a Python object using the native decoder.

            Args:
                data: Msgpack-encoded data.

            Returns:
                Deserialized Python object.
            """
            return unpack(BytesIO(data))

    except ImportError:
        from chumicro_msgpack._pure import pack, packb, unpack, unpackb  # noqa: F401
else:
    from chumicro_msgpack._pure import pack, packb, unpack, unpackb  # noqa: F401

__all__ = ["pack", "packb", "unpack", "unpackb"]
