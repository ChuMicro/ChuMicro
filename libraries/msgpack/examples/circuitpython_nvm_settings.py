# requires: hardware
"""Store and retrieve device settings in non-volatile memory (NVM).

Packs a settings dict into CircuitPython's ``microcontroller.nvm``
byte array, which persists across reboots.  A 2-byte length prefix
tracks the payload size so the reader knows how many bytes to unpack.

Runs on CircuitPython.

Setup:

1. Install the library::

       circup install chumicro-msgpack

   Or copy ``chumicro_msgpack/`` to the ``lib/`` folder on your board.

2. No extra wiring required.

3. Save as ``code.py`` on the CIRCUITPY drive.
"""

import microcontroller
from chumicro_msgpack import packb, unpackb

# --- Save settings to NVM ---

settings = {
    0: "MyNetwork",       # Wi-Fi SSID
    1: "secret123",       # Wi-Fi password
    2: "living-room-lamp",  # device name
    3: True,              # configured flag
}

data = packb(settings)
length = len(data)

# Store a 2-byte big-endian length prefix followed by the payload.
# This tells the reader how many bytes to unpack on the next boot.
nvm = microcontroller.nvm
nvm[0] = (length >> 8) & 0xFF
nvm[1] = length & 0xFF
nvm[2:2 + length] = data

print(f"saved {length} bytes to NVM")

# --- Load settings from NVM ---

stored_length = (nvm[0] << 8) | nvm[1]
if stored_length > 0 and stored_length <= len(nvm) - 2:
    restored = unpackb(bytes(nvm[2:2 + stored_length]))
    print(f"loaded: {restored}")
else:
    print("no valid settings in NVM")

