"""Wifi bringup + runtime-config helpers for networking-library tests and examples.

Self-contained: only stdlib + the runtime's built-in wifi primitives
(CP ``wifi``, MP ``network``). Importable on every runtime including
CPython, where :func:`runtime_config` still works against a local
msgpack file and :func:`wifi_up` raises ``RuntimeError`` rather than
attempt a host-side wifi connect.

Exposes:

* :func:`runtime_config`: read ``/runtime_config.msgpack`` and return
  its flat-key dict. Returns ``{}`` when the file is absent or empty.
  Decoded by the inline msgpack reader below so the helper works on
  Pi Pico W MicroPython, whose firmware ships without ``msgpack``.
* :func:`wifi_up`: bring wifi up via the runtime's built-in primitives
  and return ``(radio, ip)``. On CP, ``radio`` is ``wifi.radio`` so a
  caller can build a ``socketpool.SocketPool(radio)``; on MP, ``radio``
  is ``None`` because the global ``socket`` module reads from whichever
  interface is active.

Per-platform wifi bringup, stripped of config-loading + placeholder
checks, is just the runtime's built-in wifi connect. Reference for
readers who want to understand what this helper hides:

CircuitPython::

    import time
    import wifi

    wifi.radio.connect("my-ssid", "my-password")
    while not wifi.radio.connected:
        time.sleep(0.1)
    ip = str(wifi.radio.ipv4_address)

MicroPython::

    import time
    import network

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    # Pi Pico W (CYW43) only: disable aggressive idle power-save so
    # connects don't take 30+ seconds. Whitelist by os.uname().machine
    # (see _CYW43_MACHINES below). ESP32 boards skip the call; the
    # kwarg raises RuntimeError there.
    if os.uname().machine in _CYW43_MACHINES:
        wlan.config(pm=0xA11140)
    wlan.connect("my-ssid", "my-password")
    while not wlan.isconnected():
        time.sleep(0.1)
    ip = wlan.ifconfig()[0]
"""

import os
import struct
import sys
import time

_RUNTIME_CONFIG_PATH = "/runtime_config.msgpack"

#: Known CYW43-based MicroPython board identifiers (``os.uname().machine``).
#: The CYW43 chip's aggressive idle power-save makes wifi connects take
#: 30+ seconds; ``wlan.config(pm=0xa11140)`` disables it. Add new entries
#: as CYW43-bearing boards land in upstream MP.  Match the exact string
#: ``os.uname().machine`` returns on the board (visible in the REPL via
#: ``import os; print(os.uname().machine)``).
_CYW43_MACHINES = (
    "Raspberry Pi Pico W with RP2040",
)


def runtime_config():
    """Return ``/runtime_config.msgpack`` decoded as a dict, or ``{}``.

    Uses the inline msgpack decoder below, so no on-device ``msgpack``
    module needed. Returns ``{}`` when the file is absent (raw
    single-file deploys, or any deploy that didn't bake one) or empty.
    """
    # pragma-no-cover branches below fire only on a board with /runtime_config.msgpack deployed;
    # on host (CPython + MP/CP unix-port) the file is absent and the OSError branch returns {}.
    try:
        with open(_RUNTIME_CONFIG_PATH, "rb") as handle:  # pragma: no cover - file-present path
            data = handle.read()
    except OSError:
        return {}
    if not data:  # pragma: no cover - zero-byte file path
        return {}
    value, _ = _msgpack_unpack(memoryview(data), 0)
    if not isinstance(value, dict):  # pragma: no cover - malformed (non-dict root) path
        return {}
    return value


def wifi_up(default_ssid, default_password, *, timeout_s=15):
    """Bring wifi up; return ``(radio, ip)``.

    Reads ``wifi.ssid`` / ``wifi.password`` from
    ``/runtime_config.msgpack`` when present; otherwise uses the
    supplied defaults. Blocks until the link is connected or
    *timeout_s* elapses.

    On CircuitPython the returned radio is ``wifi.radio``; pass it
    wherever a socket pool is built (``socketpool.SocketPool(radio)``).
    On MicroPython the returned radio is ``None``: there's no
    per-radio socket pool to thread, the global ``socket`` module
    reads from whichever interface is active.

    Raises:
        RuntimeError: the resolved ssid is empty, still the shipped
            placeholder, or the host runtime is not CircuitPython /
            MicroPython.
        OSError: wifi did not connect within *timeout_s* seconds.
    """
    config = runtime_config()
    ssid = config.get("wifi.ssid", default_ssid)
    password = config.get("wifi.password", default_password)

    if not ssid or ssid == "your-wifi-ssid":
        raise RuntimeError(
            "set WIFI_SSID + WIFI_PASSWORD at the top of the example "
            "before deploying (or populate wifi.ssid / wifi.password "
            "in the deployed /runtime_config.msgpack)",
        )

    name = sys.implementation.name
    if name == "circuitpython":  # pragma: no cover - CP wifi connect, exercised on hardware
        import wifi  # noqa: PLC0415 - CP-only
        wifi.radio.connect(ssid, password)
        deadline = time.time() + timeout_s
        while not wifi.radio.connected:
            if time.time() > deadline:
                raise OSError(f"wifi did not connect within {timeout_s}s")
            time.sleep(0.1)
        return wifi.radio, str(wifi.radio.ipv4_address)

    if name == "micropython":  # pragma: no cover - MP wifi connect, exercised on hardware
        import network  # noqa: PLC0415 - MP-only
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        # CYW43 boards (Pi Pico W today, list in _CYW43_MACHINES above)
        # default to aggressive idle power-save which makes connects
        # take 30+ seconds.  Disable it.  Other boards skip the call:
        # ESP32 rejects the kwarg with ESP_ERR_INVALID_ARG (raised as
        # RuntimeError, not OSError / ValueError) and has its own
        # power-save defaults.
        if os.uname().machine in _CYW43_MACHINES:
            wlan.config(pm=0xA11140)
        wlan.connect(ssid, password)
        deadline = time.time() + timeout_s
        while not wlan.isconnected():
            if time.time() > deadline:
                raise OSError(f"wifi did not connect within {timeout_s}s")
            time.sleep(0.1)
        return None, wlan.ifconfig()[0]

    raise RuntimeError(
        f"wifi_up only supports CircuitPython / MicroPython, got {name!r}",
    )


# ---------------------------------------------------------------------------
# Tiny msgpack decoder.  Handles every type used by runtime_config.msgpack:
# nil / bool / int (every width) / float 32+64 / str / bin / array / map.
# No ext / timestamp.  Spec: github.com/msgpack/msgpack/blob/master/spec.md
# ---------------------------------------------------------------------------


def _msgpack_unpack(data, pos):
    """Decode one msgpack value starting at *pos*; return ``(value, new_pos)``."""
    tag = data[pos]
    pos += 1
    if tag < 0x80:                      # positive fixint
        return tag, pos
    if tag >= 0xe0:                     # negative fixint
        return tag - 0x100, pos
    if 0xa0 <= tag <= 0xbf:             # fixstr
        length = tag & 0x1f
        return bytes(data[pos:pos + length]).decode(), pos + length
    if 0x80 <= tag <= 0x8f:             # fixmap
        return _unpack_map(data, pos, tag & 0x0f)
    if 0x90 <= tag <= 0x9f:             # fixarray
        return _unpack_array(data, pos, tag & 0x0f)
    if tag == 0xc0:                     # nil
        return None, pos
    if tag == 0xc2:                     # false
        return False, pos
    if tag == 0xc3:                     # true
        return True, pos
    if tag == 0xca:                     # float 32
        return struct.unpack_from(">f", data, pos)[0], pos + 4
    if tag == 0xcb:                     # float 64
        return struct.unpack_from(">d", data, pos)[0], pos + 8
    if tag == 0xcc:                     # uint 8
        return data[pos], pos + 1
    if tag == 0xcd:                     # uint 16
        return struct.unpack_from(">H", data, pos)[0], pos + 2
    if tag == 0xce:                     # uint 32
        return struct.unpack_from(">I", data, pos)[0], pos + 4
    if tag == 0xcf:                     # uint 64
        return struct.unpack_from(">Q", data, pos)[0], pos + 8
    if tag == 0xd0:                     # int 8
        return struct.unpack_from(">b", data, pos)[0], pos + 1
    if tag == 0xd1:                     # int 16
        return struct.unpack_from(">h", data, pos)[0], pos + 2
    if tag == 0xd2:                     # int 32
        return struct.unpack_from(">i", data, pos)[0], pos + 4
    if tag == 0xd3:                     # int 64
        return struct.unpack_from(">q", data, pos)[0], pos + 8
    if tag == 0xd9:                     # str 8
        length = data[pos]
        return bytes(data[pos + 1:pos + 1 + length]).decode(), pos + 1 + length
    if tag == 0xda:                     # str 16
        length = struct.unpack_from(">H", data, pos)[0]
        return bytes(data[pos + 2:pos + 2 + length]).decode(), pos + 2 + length
    if tag == 0xdb:                     # str 32 (4 GB strings don't appear in runtime_config files)
        length = struct.unpack_from(">I", data, pos)[0]  # pragma: no cover - spec completeness
        return bytes(data[pos + 4:pos + 4 + length]).decode(), pos + 4 + length  # pragma: no cover
    if tag == 0xc4:                     # bin 8
        length = data[pos]
        return bytes(data[pos + 1:pos + 1 + length]), pos + 1 + length
    if tag == 0xc5:                     # bin 16
        length = struct.unpack_from(">H", data, pos)[0]
        return bytes(data[pos + 2:pos + 2 + length]), pos + 2 + length
    if tag == 0xc6:                     # bin 32 (4 GB blobs don't appear in runtime_config files)
        length = struct.unpack_from(">I", data, pos)[0]  # pragma: no cover - spec completeness
        return bytes(data[pos + 4:pos + 4 + length]), pos + 4 + length  # pragma: no cover
    if tag == 0xdc:                     # array 16
        length = struct.unpack_from(">H", data, pos)[0]
        return _unpack_array(data, pos + 2, length)
    if tag == 0xdd:                     # array 32 (huge arrays not in runtime_config files)
        length = struct.unpack_from(">I", data, pos)[0]  # pragma: no cover - spec completeness
        return _unpack_array(data, pos + 4, length)  # pragma: no cover
    if tag == 0xde:                     # map 16
        length = struct.unpack_from(">H", data, pos)[0]
        return _unpack_map(data, pos + 2, length)
    if tag == 0xdf:                     # map 32 (G-entry maps don't appear in runtime_config files)
        length = struct.unpack_from(">I", data, pos)[0]  # pragma: no cover - spec completeness
        return _unpack_map(data, pos + 4, length)  # pragma: no cover
    raise ValueError(f"unsupported msgpack type byte: 0x{tag:02x}")


def _unpack_map(data, pos, length):
    result = {}
    for _ in range(length):
        key, pos = _msgpack_unpack(data, pos)
        value, pos = _msgpack_unpack(data, pos)
        result[key] = value
    return result, pos


def _unpack_array(data, pos, length):
    result = []
    for _ in range(length):
        value, pos = _msgpack_unpack(data, pos)
        result.append(value)
    return result, pos
