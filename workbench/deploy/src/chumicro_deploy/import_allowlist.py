"""Device-runtime built-in module names the import walker treats as external.

:data:`DEVICE_BUILTIN_MODULES` lists every top-level module name that a
device-side ``import`` resolves against the MicroPython or CircuitPython
runtime itself, never against a deployed file.  When
:class:`chumicro_deploy.sources.ImportGraphSource` walks an entrypoint and a
module name fails to resolve against any host search path, this set is how it
tells a genuine runtime built-in (``import wifi``, ``import struct``) from an
import that should have resolved to a deployed file but didn't (a chumicro
library missing from the search paths, or a typo).  Names on this set are
skipped; unresolved names off it become a deploy-time
:class:`~chumicro_deploy.sources.UnresolvedImportError`.

The set is a union across both runtimes and across board variants, so a name
on it is accepted on all three runtimes.  That is deliberately permissive: the
cost of including a name is that a typo matching the *other* runtime's built-in
won't be flagged (``import machine`` under CircuitPython); the cost of omitting
a real built-in is a false deploy refusal.  Per-runtime gating of a
platform-specific module is a ``__chumicro_runtimes__`` marker job, not a walker
job, so the union is the right granularity here.

Provenance: derived from the pinned runtime clones under ``.tools/``.
MicroPython v1.26.0 ``MP_REGISTER_MODULE`` / ``MP_REGISTER_EXTENSIBLE_MODULE``
QSTRs (``py/``, ``extmod/``, ``ports/rp2/``) plus the ``u``-prefix weak-link
aliases resolved by ``py/objmodule.c`` ``mp_module_get_builtin``, and
CircuitPython 10.2.0 ``shared-bindings/`` directory names (each directory is
one importable built-in) plus its stdlib ``MP_REGISTER_EXTENSIBLE_MODULE``
set.  Maintained by hand: when a runtime adds a built-in a project imports, add
the name here.

A pip-installed consumer cannot edit this file, so the
``CHUMICRO_DEPLOY_EXTRA_BUILTINS`` environment variable (comma-separated
top-level names) extends the set without touching installed source.  That is
the unblock for a board whose firmware carries a frozen or vendor module this
list doesn't know.  The durable fix is still adding the name here upstream.
"""

from __future__ import annotations

import os

#: CPython-compatible stdlib both runtimes ship as C built-ins, plus the core
#: always-present names (``builtins``, ``sys``, ``gc``, ``micropython``).
_STDLIB_BUILTINS: frozenset[str] = frozenset(
    {
        "array",
        "binascii",
        "builtins",
        "cmath",
        "collections",
        "cryptolib",
        "deflate",
        "errno",
        "gc",
        "hashlib",
        "heapq",
        "io",
        "json",
        "marshal",
        "math",
        "micropython",
        "os",
        "platform",
        "random",
        "re",
        "select",
        "struct",
        "sys",
        "time",
        "uctypes",
        "zlib",
        "__future__",
        "__main__",
    }
)

#: MicroPython-specific built-ins (``MP_REGISTER_MODULE`` /
#: ``MP_REGISTER_EXTENSIBLE_MODULE`` on ``py/`` + ``extmod/`` + the rp2 port)
#: and the ``u``-prefix weak-link aliases the runtime resolves at import time.
_MICROPYTHON_BUILTINS: frozenset[str] = frozenset(
    {
        "_asyncio",
        "_rp2",
        "_thread",
        "asyncio",
        "bluetooth",
        "btree",
        "framebuf",
        "machine",
        "network",
        "socket",
        "ssl",
        "tls",
        "vfs",
        "websocket",
        # ``u``-prefix weak-link aliases (py/objmodule.c).
        "uarray",
        "uasyncio",
        "ubinascii",
        "ubluetooth",
        "ucollections",
        "ucryptolib",
        "uerrno",
        "uhashlib",
        "uheapq",
        "uio",
        "ujson",
        "umachine",
        "uos",
        "uplatform",
        "urandom",
        "ure",
        "uselect",
        "usocket",
        "ussl",
        "ustruct",
        "usys",
        "utime",
        "uwebsocket",
    }
)

#: CircuitPython-specific built-ins, one ``shared-bindings/`` directory per
#: name, including the raspberrypi-port (Pico / Pico W) bindings and the
#: networking / BLE modules that appear only on capable board variants.
_CIRCUITPYTHON_BUILTINS: frozenset[str] = frozenset(
    {
        "_bleio",
        "_pixelmap",
        "_stage",
        "aesio",
        "alarm",
        "analogbufio",
        "analogio",
        "audiobusio",
        "audiocore",
        "audioio",
        "audiomixer",
        "audiomp3",
        "audiopwmio",
        "bitbangio",
        "bitmaptools",
        "board",
        "busdisplay",
        "busio",
        "canio",
        "countio",
        "cyw43",
        "digitalio",
        "displayio",
        "epaperdisplay",
        "fontio",
        "fourwire",
        "framebufferio",
        "frequencyio",
        "gifio",
        "i2cdisplaybus",
        "i2ctarget",
        "ipaddress",
        "jpegio",
        "keypad",
        "mdns",
        "memorymap",
        "memorymonitor",
        "microcontroller",
        "msgpack",
        "neopixel_write",
        "nvm",
        "onewireio",
        "paralleldisplaybus",
        "picodvi",
        "pulseio",
        "pwmio",
        "qrio",
        "rainbowio",
        "rgbmatrix",
        "rotaryio",
        "rp2pio",
        "rtc",
        "sdcardio",
        "socketpool",
        "storage",
        "supervisor",
        "synthio",
        "terminalio",
        "touchio",
        "traceback",
        "usb_cdc",
        "usb_hid",
        "usb_midi",
        "vectorio",
        "warnings",
        "watchdog",
        "wifi",
    }
)

#: Every top-level module name a device ``import`` resolves against the runtime
#: rather than a deployed file.  The import walker skips these and refuses any
#: other unresolved import at deploy time.
DEVICE_BUILTIN_MODULES: frozenset[str] = (
    _STDLIB_BUILTINS | _MICROPYTHON_BUILTINS | _CIRCUITPYTHON_BUILTINS
)


#: Environment variable extending the built-in set for pip-installed
#: consumers: comma-separated top-level module names.
EXTRA_BUILTINS_ENV = "CHUMICRO_DEPLOY_EXTRA_BUILTINS"


def _extra_builtins() -> frozenset[str]:
    """Consumer-declared built-in names from the environment.

    Read per call so a shell export takes effect without re-importing.
    """
    raw = os.environ.get(EXTRA_BUILTINS_ENV, "")
    return frozenset(name.strip() for name in raw.split(",") if name.strip())


def is_device_builtin(module_name: str) -> bool:
    """Return whether *module_name*'s top-level package is a runtime built-in.

    A dotted name (``collections.deque``) is a built-in when its first segment
    (``collections``) is on :data:`DEVICE_BUILTIN_MODULES`.  A runtime built-in
    package owns its whole subtree, none of which the host can supply as a file.
    Names listed in :data:`EXTRA_BUILTINS_ENV` count as built-ins too.
    """
    top_level = module_name.split(".", 1)[0]
    return top_level in DEVICE_BUILTIN_MODULES or top_level in _extra_builtins()
