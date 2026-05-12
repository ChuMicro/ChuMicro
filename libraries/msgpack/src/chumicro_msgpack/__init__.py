"""MessagePack serialization for CircuitPython, MicroPython, and CPython.

Implements a strict 32-bit-int / 16-bit-length subset of the
`MessagePack spec <https://github.com/msgpack/msgpack/blob/master/spec.md>`_:

- integers in ``[-2**31, 2**32-1]``  (fixint, ``int8/16/32``, ``uint8/16/32``)
- 32-bit floats only  (``float32``)
- strings, bytes, arrays, and maps up to 65 535 elements / bytes

The subset is what fits on a small board, but the bytes are
spec-compliant — any standard MessagePack reader decodes them.

Public API
----------
- ``packb(obj)`` — pack a Python object to msgpack bytes.
- ``unpackb(data)`` — unpack msgpack bytes to a Python object.
- ``pack(obj, stream)`` — pack to a writable stream.
- ``unpack(stream)`` — unpack one object from a readable stream.

Cross-runtime compatibility
---------------------------
On CircuitPython boards that include the native ``msgpack`` module,
all four functions delegate to the C implementation.  The pure-Python
encoder in ``_pure`` is never imported, keeping heap usage lower on
memory-tight boards.

On CPython and MicroPython, the implementation is always the pure
Python ``_pure`` encoder.  Note that PyPI's ``msgpack`` package
implements the *full* spec (``float64``, ``int64``, ``*32``-length
prefixes, ``strict_map_key=True`` by default) — that's a different
contract.  Host code that produces bytes for a chumicro device should
use ``msgpack.packb(obj, use_single_float=True)`` and stay inside the
size limits above; the resulting bytes are byte-for-byte identical to
``chumicro_msgpack.packb(obj)``.  This identity is pinned by the
``test_byte_identity_with_pypi_msgpack`` test in this package's tests.

Out-of-subset bytes encountered on decode (``0xcb`` float64, ``0xcf``
uint64, ``0xd3`` int64, ``0xc6/0xdb/0xdd/0xdf`` ``*32``-length tags)
raise ``ValueError`` with a message that names the tag and points at
the producer-side fix.
"""

import sys

_native_loaded = False
if sys.implementation.name == "circuitpython":
    try:
        from io import BytesIO

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

        _native_loaded = True
    except ImportError:
        pass

if not _native_loaded:
    from chumicro_msgpack._pure import pack, packb, unpack, unpackb  # noqa: F401

__all__ = ["pack", "packb", "unpack", "unpackb"]
