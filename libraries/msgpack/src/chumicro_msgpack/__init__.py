"""MessagePack serialization for CircuitPython, MicroPython, and CPython."""

import gc
import sys

_native_loaded = False
if sys.implementation.name == "circuitpython":
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
            # The native decoder raises EOFError on truncation; our contract promises ValueError.
            # Both message texts below are one contract with the pure path
            # (chumicro_msgpack._pure raises them verbatim); change together.
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
