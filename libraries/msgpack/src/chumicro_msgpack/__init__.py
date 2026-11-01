"""Pack Python values into MessagePack bytes and unpack them, on CircuitPython, MicroPython, and CPython.

``packb`` and ``unpackb`` convert between a value and ``bytes``. ``pack``
and ``unpack`` write a value to a stream and read one back.

The four functions run this package's pure-Python code, with the limits
each one lists, except on a CircuitPython board whose firmware has the
built-in ``msgpack`` module. There they use the firmware module. Its
encoder packs integers from ``-2**30`` to ``2**30 - 1`` and raises
``ValueError`` for a larger integer or a type it cannot pack. Its
``unpack`` reads one value and leaves any bytes after it in the stream.
"""

import gc
import sys

_native_loaded = False
if sys.implementation.name == "circuitpython":
    try:
        from io import BytesIO

        from msgpack import pack, unpack  # noqa: F401

        def packb(obj: object) -> bytes:  # pragma: no cover
            """Pack ``obj`` into MessagePack bytes with the firmware's ``msgpack.pack``.

            Args:
                obj: Value to pack, within the firmware limits the module
                    docstring lists.

            Returns:
                The packed bytes.

            Raises:
                ValueError: ``obj`` holds an integer or a type the firmware
                    encoder cannot pack.
            """
            buffer = BytesIO()
            pack(obj, buffer)
            return buffer.getvalue()

        def unpackb(data: bytes | bytearray | memoryview) -> object:  # pragma: no cover
            """Unpack the one MessagePack value in ``data`` with the firmware's ``msgpack.unpack``.

            Args:
                data: The packed bytes, holding exactly one value.

            Returns:
                The unpacked value.

            Raises:
                ValueError: ``data`` ends inside a value, holds an invalid
                    type byte, or has bytes left after the value.
            """
            buffer = BytesIO(data)
            # The firmware raises EOFError when data ends inside a value.
            # unpackb raises ValueError instead, with the same two messages
            # chumicro_msgpack._pure raises, so callers see one error on every runtime.
            try:
                result = unpack(buffer)
            except EOFError as truncation_error:
                raise ValueError(
                    "malformed msgpack: truncated or over-length framing",
                ) from truncation_error
            if buffer.tell() != len(data):
                raise ValueError("trailing bytes after msgpack value")
            return result

        _native_loaded = True
    except ImportError:
        pass

if not _native_loaded:
    from chumicro_msgpack._pure import pack, packb, unpack, unpackb  # noqa: F401

__all__ = ["pack", "packb", "unpack", "unpackb"]

gc.collect()
