"""Save settings in NVM so they survive a reset, then show they are still there.

When the board starts, it loads a small settings dict from
``microcontroller.nvm``, turns the brightness setting up by 10, and saves
the dict back.  After that it reads NVM every five seconds and prints what
it finds.  Press reset and the board loads the brightness it saved last
time, which shows the setting survived.

``microcontroller.nvm`` is a few kilobytes of memory that keeps its contents
through a reset or a power cycle.  It works like a ``bytearray`` of fixed
size, so the example stores a two-byte length in front of the data to know
where the data ends::

    bytes 0-1   how many bytes of msgpack data follow (high byte first)
    bytes 2...  the settings dict, packed by ``packb``

Every save erases a block of flash, and flash wears out after a limited
number of erases.  That is why the board saves once each time it starts and
only reads after that: save a setting when it changes, never on a fast timer.

Setup:

1. Install the library with ``circup install chumicro_msgpack``, or copy
   ``chumicro_msgpack/`` to the ``lib/`` folder on your board.
2. No wiring needed.
3. Save this file as ``code.py`` on the CIRCUITPY drive.

Example output after a few resets::

    Loaded from NVM: {'name': 'lamp', 'brightness': 30}
    Saved brightness 40.  Press reset and the board loads 40.
    NVM holds: {'name': 'lamp', 'brightness': 40}
    NVM holds: {'name': 'lamp', 'brightness': 40}

Runs on CircuitPython.
"""

# CircuitPython only: microcontroller.nvm has no MicroPython equivalent.
__chumicro_runtimes__ = ("circuitpython",)

import time

import microcontroller
from chumicro_msgpack import packb, unpackb


def save_settings(nvm, settings):
    """Write *settings* into *nvm*: a two-byte length, then the msgpack bytes."""
    data = packb(settings)
    header = bytes([len(data) >> 8, len(data) & 0xFF])
    # One write for header and data together, so the board erases flash once.
    nvm[0 : 2 + len(data)] = header + data


def load_settings(nvm):
    """Return the settings dict saved in *nvm*, or None when nothing valid is there."""
    length = (nvm[0] << 8) | nvm[1]
    # A length of 0, or one longer than NVM, means nothing was saved here yet.
    if length == 0 or length > len(nvm) - 2:
        return None
    try:
        settings = unpackb(nvm[2 : 2 + length])
    except ValueError:
        return None
    if not isinstance(settings, dict):
        return None
    return settings


nvm = microcontroller.nvm
while nvm is None:
    # Some boards have no NVM.  Say so every ten seconds instead of stopping.
    print("This board has no microcontroller.nvm, so there is nowhere to save settings.")
    time.sleep(10)

settings = load_settings(nvm)
if settings is None:
    print("No settings in NVM yet, so starting from brightness 0.")
    settings = {"name": "lamp", "brightness": 0}
else:
    print(f"Loaded from NVM: {settings}")

# Change one setting and save it, once per start.  Brightness steps 0, 10, ... 100, 0.
settings["brightness"] = (settings.get("brightness", 0) + 10) % 110
save_settings(nvm, settings)
brightness = settings["brightness"]
print(f"Saved brightness {brightness}.  Press reset and the board loads {brightness}.")

# Keep running, and read the saved settings back every five seconds.
while True:
    time.sleep(5)
    print(f"NVM holds: {load_settings(nvm)}")
