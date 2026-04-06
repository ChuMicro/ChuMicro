"""Pack and unpack a settings dictionary.

Converts a Python dict to compact binary bytes with ``packb`` and
restores it with ``unpackb``.  The bytes-based API is the simplest
way to serialize data when you don't need a stream.

Runs on CPython, MicroPython, and CircuitPython.

Example output::

    packed 46 bytes
    restored: {0: 'MyNetwork', 1: 'secret123', 2: 'lamp', 3: '192.168.1.100', 4: True}
"""

from chumicro_msgpack import packb, unpackb

# Use integer keys for maximum compactness.  Each integer key encodes
# in a single byte, versus multiple bytes for a quoted string key.
settings = {
    0: "MyNetwork",
    1: "secret123",
    2: "lamp",
    3: "192.168.1.100",
    4: True,
}

# packb returns bytes — ready to write to NVM, send over the network, etc.
data = packb(settings)
print(f"packed {len(data)} bytes")

# unpackb accepts bytes, bytearray, or memoryview.
restored = unpackb(data)
print(f"restored: {restored}")
