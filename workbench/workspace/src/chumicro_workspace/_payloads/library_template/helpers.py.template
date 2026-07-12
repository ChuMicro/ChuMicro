"""Standalone wifi-up helper for library examples that bring wifi up.

Self-contained: relies only on runtime built-ins (CP `wifi`, MP
`network`, `struct`).  Each network-using library ships a copy in its
`examples/` directory.  The canonical body lives at
`scripts/templates/examples_helpers.py`; the new-library scaffold emits
it into a fresh library, and a preflight drift check keeps every
`examples/helpers.py` byte-identical to it.  Edit the canonical file,
not a per-library copy.

What it does:

* `runtime_config()` reads `/runtime_config.msgpack` (a flat-key
  config dict baked onto the device by whichever deploy pipeline
  put it there) and returns it as a Python dict.  Uses the inline
  decoder below.  Works on every runtime including Pi Pico W
  MicroPython, whose firmware doesn't ship `msgpack`.
* `wifi_up()` brings the link up via the runtime's built-in wifi
  primitives and returns ``(radio, ip)``.

When the library this `helpers.py` ships with doesn't need wifi
(non-network library), delete the file.

What `wifi_up` is doing per platform
====================================

Stripped of the config-loading + placeholder check, the per-platform
flow is just the runtime's built-in wifi connect.  Reference for users
who want to understand what this helper hides:

CircuitPython::

    import time
    import wifi

    wifi.radio.connect("my-ssid", "my-password")
    while not wifi.radio.connected:
        time.sleep(0.1)
    ip = str(wifi.radio.ipv4_address)
    # `wifi.radio` is the per-board radio singleton.  Anything that
    # opens sockets does so via `socketpool.SocketPool(wifi.radio)`,
    # so the radio object itself is what gets threaded through.

MicroPython::

    import time
    import network

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    # Pi Pico W (CYW43) only: disable aggressive idle power-save so
    # connects don't take 30+ seconds.  Whitelist by os.uname().machine
    # (see _CYW43_MACHINES below).  Other boards skip the call: ESP32
    # rejects the kwarg with ESP_ERR_INVALID_ARG (raised as RuntimeError,
    # not OSError / ValueError) and has its own power-save defaults.
    if os.uname().machine in _CYW43_MACHINES:
        wlan.config(pm=0xA11140)
    wlan.connect("my-ssid", "my-password")
    while not wlan.isconnected():
        time.sleep(0.1)
    ip = wlan.ifconfig()[0]
    # MP has no per-radio socket pool: `import socket` operates
    # against the global active interface, so there's nothing equivalent
    # to thread around.  `wifi_up` returns `None` for the radio slot.
"""

#: Helper imports CP `wifi` and MP `network`: runtime built-ins, not
#: importable on the host.  The marker tells `verify_examples.py` to
#: skip platform-import checks here.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import os
import struct
import sys
import time

_RUNTIME_CONFIG_PATH = "/runtime_config.msgpack"


def _resolve_ticks_ms():
    """Pick the best raw ms tick source available on this runtime.

    Resolution order: ``supervisor.ticks_ms`` (CP 7+), then
    ``time.ticks_ms`` (MP), then ``time.monotonic_ns``, then
    ``time.monotonic`` as the final fallback.  Reimplemented inline so
    example helpers don't depend on ``chumicro_timing``.
    """
    try:
        import supervisor  # type: ignore[import-not-found]
        candidate = getattr(supervisor, "ticks_ms", None)
        if callable(candidate):
            return candidate
    except ImportError:
        pass
    candidate = getattr(time, "ticks_ms", None)
    if callable(candidate):
        return candidate
    candidate = getattr(time, "monotonic_ns", None)
    if callable(candidate):
        return lambda: candidate() // 1_000_000
    monotonic = time.monotonic
    return lambda: int(monotonic() * 1000)


_raw_ticks_ms = _resolve_ticks_ms()
_TICKS_MAX = (1 << 29) - 1
_TICKS_PERIOD = 1 << 29
_TICKS_HALFPERIOD = _TICKS_PERIOD // 2


def ticks_ms():
    """Return a wrapping monotonic millisecond count in ``[0, 2**29 - 1]``.

    Pass this value to ``check`` / ``handle`` of any chumicro service
    so the time-base matches the library's internal deadline math and
    per-request timeouts compute correctly.
    """
    return _raw_ticks_ms() & _TICKS_MAX


def ticks_add(ticks, delta):
    """Add *delta* milliseconds to a wrapping tick value.

    Wraps at ``2**29``; *delta* must be in ``(-2**28, +2**28)``.
    """
    if -_TICKS_HALFPERIOD < delta < _TICKS_HALFPERIOD:
        return (ticks + delta) % _TICKS_PERIOD
    raise OverflowError("ticks interval overflow")


def ticks_diff(end, start):
    """Signed millisecond difference *end* minus *start* with wraparound.

    Correct as long as the two values are within ``2**28`` ms
    (~3.1 days) of each other.
    """
    diff = (end - start) & _TICKS_MAX
    return ((diff + _TICKS_HALFPERIOD) & _TICKS_MAX) - _TICKS_HALFPERIOD


#: MicroPython board identifiers (``os.uname().machine``) whose wifi
#: needs ``wlan.config(pm=0xa11140)`` before connect.  Without this call
#: the CYW43 chip's aggressive idle power-save makes connects take 30+
#: seconds.  Add new entries as CYW43-bearing boards land in upstream MP,
#: matching the exact ``os.uname().machine`` string the board returns
#: (visible in the REPL via ``import os; print(os.uname().machine)``).
_CYW43_MACHINES = (
    "Raspberry Pi Pico W with RP2040",
)


def runtime_config():
    """Return ``/runtime_config.msgpack`` decoded as a dict, or ``{}``.

    Uses the inline msgpack decoder below.  No on-device `msgpack`
    module needed.  Returns ``{}`` if the file is absent (raw
    single-file deploys, or any deploy that didn't bake one).
    """
    try:
        with open(_RUNTIME_CONFIG_PATH, "rb") as handle:
            data = handle.read()
    except OSError:
        return {}
    if not data:
        return {}
    value, _ = _msgpack_unpack(memoryview(data), 0)
    return value if isinstance(value, dict) else {}


def wifi_up(default_ssid, default_password, *, timeout_s=15):
    """Bring wifi up; return ``(radio, ip)``.

    Reads `wifi.ssid` / `wifi.password` from `/runtime_config.msgpack`
    when present; otherwise uses the supplied defaults.  Blocks until
    the link is connected or *timeout_s* elapses.

    On CircuitPython the returned radio is `wifi.radio`: pass it
    through wherever a socket pool is built (``socketpool.SocketPool(radio)``).
    On MicroPython the returned radio is ``None``: there's no per-radio
    socket pool to thread, the global `socket` module reads from
    whichever interface is active.

    Raises:
        RuntimeError: the resolved ssid is empty or still the
            shipped placeholder.
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
    if name == "circuitpython":
        import wifi  # noqa: PLC0415 - CP-only
        wifi.radio.connect(ssid, password)
        deadline = time.time() + timeout_s
        while not wifi.radio.connected:
            if time.time() > deadline:
                raise OSError(f"wifi did not connect within {timeout_s}s")
            time.sleep(0.1)
        return wifi.radio, str(wifi.radio.ipv4_address)

    if name == "micropython":
        import network  # noqa: PLC0415 - MP-only
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        # CYW43 boards (Pi Pico W today, list in _CYW43_MACHINES above)
        # default to aggressive idle power-save which makes connects
        # take 30+ seconds.  Disable it via the 0xA11140 magic constant.
        # Other boards skip the call: ESP32 rejects the kwarg with
        # ESP_ERR_INVALID_ARG (raised as RuntimeError, not OSError /
        # ValueError) and has its own power-save defaults.
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
    if tag == 0xdb:                     # str 32
        length = struct.unpack_from(">I", data, pos)[0]
        return bytes(data[pos + 4:pos + 4 + length]).decode(), pos + 4 + length
    if tag == 0xc4:                     # bin 8
        length = data[pos]
        return bytes(data[pos + 1:pos + 1 + length]), pos + 1 + length
    if tag == 0xc5:                     # bin 16
        length = struct.unpack_from(">H", data, pos)[0]
        return bytes(data[pos + 2:pos + 2 + length]), pos + 2 + length
    if tag == 0xc6:                     # bin 32
        length = struct.unpack_from(">I", data, pos)[0]
        return bytes(data[pos + 4:pos + 4 + length]), pos + 4 + length
    if tag == 0xdc:                     # array 16
        length = struct.unpack_from(">H", data, pos)[0]
        return _unpack_array(data, pos + 2, length)
    if tag == 0xdd:                     # array 32
        length = struct.unpack_from(">I", data, pos)[0]
        return _unpack_array(data, pos + 4, length)
    if tag == 0xde:                     # map 16
        length = struct.unpack_from(">H", data, pos)[0]
        return _unpack_map(data, pos + 2, length)
    if tag == 0xdf:                     # map 32
        length = struct.unpack_from(">I", data, pos)[0]
        return _unpack_map(data, pos + 4, length)
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
