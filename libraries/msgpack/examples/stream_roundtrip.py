"""Use the stream-based pack / unpack API with BytesIO.

The stream API matches CircuitPython's native ``msgpack.pack`` and
``msgpack.unpack`` signatures.  On CircuitPython hardware, these
delegate directly to the C implementation.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    wrote 9 bytes to stream
    unpacked: {'key': [1, 2, 3]}
"""

from io import BytesIO

from chumicro_msgpack import pack, unpack

# Create an in-memory stream.  On a real board you might use a file
# or a network socket instead.
buffer = BytesIO()

# pack writes msgpack bytes to the stream.
pack({"key": [1, 2, 3]}, buffer)
print(f"wrote {buffer.tell()} bytes to stream")

# Seek back to the start before reading.
buffer.seek(0)

# unpack reads one object from the stream.
result = unpack(buffer)
print(f"unpacked: {result}")
