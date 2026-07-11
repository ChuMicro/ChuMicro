# requires: hardware
"""Store and retrieve device settings in non-volatile memory (NVM).

CircuitPython provides ``microcontroller.nvm``, a small byte array
(typically 256–8192 bytes depending on the board) that persists across
reboots and power cycles.  It behaves like a ``bytearray``: you read
and write individual bytes or slices.

This example uses ``packb`` to convert a Python dict into compact
msgpack bytes, writes those bytes into NVM with a 2-byte length
header, and reads them back with ``unpackb``.  The length header is
needed because NVM is a fixed-size buffer.  Without it, you would not
know where the meaningful data ends and the unused bytes begin.

**NVM layout used by this example:**

.. code-block:: text

    Byte 0      Byte 1      Byte 2 ...  Byte N+1
    ┌──────────┬──────────┬───────────────────────┐
    │ len high │ len low  │  msgpack payload ...   │
    └──────────┴──────────┴───────────────────────┘

    len = (byte_0 << 8) | byte_1   (big-endian 16-bit unsigned integer)

Runs on CircuitPython.

Setup:

1. Install the library::

       circup install chumicro_msgpack

   Or copy ``chumicro_msgpack/`` to the ``lib/`` folder on your board.

2. No extra wiring required.

3. Save as ``code.py`` on the CIRCUITPY drive.
"""

#: CircuitPython-only.  Uses ``microcontroller.nvm``, a CP-specific
#: API with no MicroPython equivalent.  The marker tells
#: ``deploy-example`` to refuse this file on MP boards instead of
#: silently AttributeError'ing at import.
__chumicro_runtimes__ = ("circuitpython",)

import microcontroller
from chumicro_msgpack import packb, unpackb

# --- Key definitions -------------------------------------------------------

# Integer keys keep the msgpack payload small.  Each integer key
# encodes in a single byte, whereas a string key like "ssid" would
# take 5+ bytes.  Define named constants so the rest of your code
# reads clearly without sacrificing compactness on the wire.
KEY_SSID = 0
KEY_PASSWORD = 1
KEY_DEVICE_NAME = 2
KEY_CONFIGURED = 3

# --- Save settings to NVM -------------------------------------------------

settings = {
    KEY_SSID: "MyNetwork",
    KEY_PASSWORD: "secret123",
    KEY_DEVICE_NAME: "living-room-lamp",
    KEY_CONFIGURED: True,
}

# packb converts the dict to compact binary bytes.
data = packb(settings)
length = len(data)

# Get a reference to the NVM byte array.  Its size varies by board
# (e.g., 256 bytes on ESP32-S2, 8192 on some RP2040 boards).
# Not all boards have NVM. Check before using it.
nvm = microcontroller.nvm
if nvm is None:
    print("This board does not have NVM.")
    raise SystemExit

# Write a 2-byte big-endian length prefix so we know how many bytes
# to read back later.  Big-endian means the high byte comes first:
#   length = 52  →  high byte = 0, low byte = 52
#   length = 300 →  high byte = 1, low byte = 44
nvm[0] = (length >> 8) & 0xFF  # high byte
nvm[1] = length & 0xFF         # low byte

# Write the msgpack payload immediately after the 2-byte header.
nvm[2:2 + length] = data

print(f"saved {length} bytes to NVM (total NVM size: {len(nvm)} bytes)")

# --- Load settings from NVM -----------------------------------------------

# Reconstruct the length from the 2-byte header.
stored_length = (nvm[0] << 8) | nvm[1]

# Validate: length must be positive and fit within the NVM buffer
# (minus the 2-byte header).  A length of 0 or a value larger than
# the buffer means NVM has not been written yet or is corrupted.
if 0 < stored_length <= len(nvm) - 2:
    # Read exactly stored_length bytes from NVM and decode.
    # bytes() copies the slice out of NVM into a regular bytes object
    # that unpackb can parse.
    restored = unpackb(bytes(nvm[2:2 + stored_length]))
    print(f"loaded: {restored}")
else:
    print("no valid settings in NVM")
