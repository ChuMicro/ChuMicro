"""MessagePack serialization for CircuitPython, MicroPython, and CPython.

Implements a strict subset of the `MessagePack spec
<https://github.com/msgpack/msgpack/blob/master/spec.md>`_: integers in
``[-2**31, 2**32-1]``, 32-bit floats, and strings, bytes, arrays, and
maps up to 65 535 elements or bytes. The subset is what fits on a small
board, but the bytes stay spec-compliant, so any standard MessagePack
reader decodes them.
"""

import gc
import sys

_native_loaded = False
if sys.implementation.name == "circuitpython":
    # Prefer the native C msgpack module when present; it keeps heap usage
    # lower than importing the pure-Python encoder.
    try:
        from io import BytesIO

        from msgpack import pack, unpack  # noqa: F401

        def packb(obj: object) -> bytes:  # pragma: no cover
            """Pack *obj* to msgpack bytes using the native encoder.

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

            Raises:
                ValueError: Truncated framing, or bytes left over after
                    the first object.
            """
            buffer = BytesIO(data)
            # The native decoder raises EOFError on truncation; translate it
            # to the ValueError our contract (and the pure path) promises.
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
