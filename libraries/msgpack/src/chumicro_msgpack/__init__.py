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
``pack`` and ``unpack`` delegate to the C implementation.  ``packb``
and ``unpackb`` always use the pure-Python encoder/decoder.
"""

from .core import pack, packb, unpack, unpackb

__all__ = ["pack", "packb", "unpack", "unpackb"]
