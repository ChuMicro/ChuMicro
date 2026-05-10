"""Wifi-up helper for `chumicro-http-server` examples.

Hides the runtime-specific wifi setup so each example stays focused
on the http_server API.  Uses raw runtime primitives (CP `wifi.radio`,
MP `network.WLAN`) so the helper doesn't pull in any library that
`chumicro-http-server` doesn't already depend on.

Optionally reads `wifi.ssid` / `wifi.password` from the deployed
`/runtime_config.msgpack` via the on-device `msgpack` module — built
into CircuitPython core; ESP32 MicroPython firmware ships it; Pi
Pico W MicroPython doesn't (run `mpremote mip install msgpack`
once, or edit the example's WIFI_SSID / WIFI_PASSWORD constants
directly).  When neither path resolves, the placeholder check below
raises a clear "edit the constants" error instead of timing out
silently.
"""

#: Helper imports CP `wifi` and MP `network` — runtime built-ins, not
#: importable on the host.  The marker tells `verify_examples.py` to
#: skip platform-import checks here.
__chumicro_runtimes__ = ("circuitpython", "micropython")

import sys
import time

_PLACEHOLDER_SSIDS = {"", "your-wifi-ssid", "your-ssid"}
_RUNTIME_CONFIG_PATH = "/runtime_config.msgpack"


def runtime_config():
    """Return `/runtime_config.msgpack` decoded as a dict, or `{}`.

    Reads the deployed runtime-config file via the on-device `msgpack`
    module (built into CircuitPython core; ESP32 MicroPython firmware
    ships it; Pi Pico W MicroPython doesn't — run `mpremote mip install
    msgpack` once, or fall through to in-file constants).
    """
    try:
        import msgpack  # noqa: PLC0415 — built-in on CP, optional on MP
    except ImportError:
        return {}
    try:
        with open(_RUNTIME_CONFIG_PATH, "rb") as handle:
            return msgpack.unpack(handle) or {}
    except OSError:
        return {}


def wifi_up(default_ssid, default_password, *, timeout_s=15):
    """Bring wifi up; return ``(radio, ip)``.

    Reads `wifi.ssid` / `wifi.password` from `/runtime_config.msgpack`
    when present; otherwise uses the supplied defaults.  Blocks until
    the link is connected or *timeout_s* elapses.

    On CircuitPython the returned radio is `wifi.radio`; on
    MicroPython it's `None` (the `chumicro_sockets` MP adapter uses
    the global `socket` module and ignores the kwarg).

    Raises:
        RuntimeError: the resolved ssid is still a placeholder.
        OSError: wifi did not connect within *timeout_s* seconds.
    """
    config = runtime_config()
    ssid = config.get("wifi.ssid", default_ssid)
    password = config.get("wifi.password", default_password)

    if ssid in _PLACEHOLDER_SSIDS:
        raise RuntimeError(
            "set WIFI_SSID + WIFI_PASSWORD at the top of the example "
            "to your real wifi credentials before deploying (or set "
            "wifi.ssid / wifi.password in your secrets.toml and "
            "deploy via chumicro-workspace).",
        )

    name = sys.implementation.name
    if name == "circuitpython":
        import wifi  # noqa: PLC0415 — CP-only
        wifi.radio.connect(ssid, password)
        deadline = time.time() + timeout_s
        while not wifi.radio.connected:
            if time.time() > deadline:
                raise OSError(f"wifi did not connect within {timeout_s}s")
            time.sleep(0.1)
        return wifi.radio, str(wifi.radio.ipv4_address)

    if name == "micropython":
        import network  # noqa: PLC0415 — MP-only
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        # CYW43 (Pi Pico W) defaults to aggressive power-save which
        # makes connects take 30+ seconds.  Disable it; ESP32 chips
        # raise on this kwarg — silently skip there.
        try:
            wlan.config(pm=0xA11140)
        except (OSError, ValueError):
            pass
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
