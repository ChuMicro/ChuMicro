# chumicro-wifi

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Wifi that auto-reconnects so your app code doesn't have to.**

One WiFi service across CircuitPython (Adafruit boards) and MicroPython on both ESP32 and Pi Pico W.  Owns the radio (no `CIRCUITPY_WIFI_*` settings, no firmware-level auto-reconnect competing with you), surfaces state transitions as events you can wire into the rest of your app via [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), and reads its config section via [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config).  CircuitPython's substrate-level `connect()` is blocking.  See [Platform support](#platform-support) for what that means in practice.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family: small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_wifi

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_wifi

# CPython
pip install chumicro-wifi
```

For bundle setup, pre-compiled `.mpy` bundles, the experimental channel, and details on PyPI naming, see the [chumicro INSTALL guide](https://github.com/ChuMicro/ChuMicro/blob/main/INSTALL.md).

## Quick example

User-app pattern (the 4-line bring-up):

```python
from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiService

config = load_runtime_config()
runner = Runner()
wifi = WifiService.from_config(config)
runner.add(wifi)
```

State + IP introspection any time:

```python
wifi.state          # "disconnected" | "connecting" | "connected" | "reconnecting" | "failed"
wifi.connected
wifi.ip
wifi.last_error
wifi.on_state_change(lambda old, new: print(f"{old} -> {new}"))
```

## What's included

| Symbol | What it does |
|---|---|
| `WifiConfig` | Typed connection settings (`ssid`, `password`, hostname, timeouts, reconnect tuning).  `from_config(config)` reads the flat `wifi.*` keys; `try_from_config(config)` returns `None` when the section isn't deployed. |
| `WifiService` | State machine + reconnect supervisor; implements `Runner.add()`-compatible `check`/`handle`.  `from_config(config, radio=None, ...)` builds it straight from the flat `wifi.*` keys; extra keywords pass through to the constructor. Auto-detects the runtime adapter at construction time (the `CpythonWifiAdapter` host stand-in on CPython, `CpWifiAdapter` on CircuitPython, substrate-aware `MpWifiAdapter` on MicroPython, handling ESP-IDF + CYW43 transparently). |
| `WifiState` | String-sentinel state names: `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `RECONNECTING`, `FAILED`. |
| `chumicro_wifi.testing.FakeWifi` | Drop-in `WifiService` wrapping a `FakeWifiAdapter` with `set_connect_outcome`, `drop_link`, `calls` hooks for downstream library tests. |

## Where this fits

Depends on [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) for its config section and registers with [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) for its tick contract.  Provides the radio the networking layers sit on top of: [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) on CircuitPython, with the HTTP / MQTT / WebSocket / NTP libraries downstream of that.

## Platform support

Works on CPython, MicroPython, and CircuitPython.  Ships three runtime adapters: CircuitPython `wifi.radio` (`_adapters/cp.py`), MicroPython `network.WLAN` covering both ESP-IDF (ESP32 family) and CYW43 (Pi Pico W) stacks (`_adapters/mp.py`), and a CPython host stand-in that reports success immediately (`_adapters/cpython.py`); `chumicro_wifi.testing.FakeWifiAdapter` covers host-side tests.  The right adapter is selected at runtime via `sys.implementation.name`; the MP adapter then auto-detects ESP-IDF vs CYW43 by matching `sys.implementation._machine` against a positive whitelist of known CYW43 boards.

### CircuitPython connect is blocking (read this if you're shipping to CP)

CircuitPython's substrate-level `wifi.radio.connect()` is blocking.  There is no non-blocking variant exposed by the firmware.  While `WifiService` is `CONNECTING` or `RECONNECTING` on a CircuitPython board, `handle()` stalls for up to `connect_timeout_ms` (default 15 000 ms).  Other services in the same `Runner` (your LED heartbeat, an HTTP request, an MQTT keep-alive) pause for that window.  Once the state reaches `CONNECTED`, the loop runs at full speed again and stays there until the link drops.

MicroPython's `wlan.connect()` is genuinely non-blocking on both ESP32 and Pi Pico W substrates: association happens in the background and `handle()` returns immediately.  If non-blocking connect is load-bearing for your app, prefer MicroPython on RP2040 / RP2350 or ESP32-family boards.

## Examples

| Example | What it shows |
|---|---|
| [`connect_to_ap.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/wifi/examples/connect_to_ap.py) | Connect to a real AP, print state transitions, observe IP, reading `wifi.ssid` / `wifi.password` from `runtime_config.msgpack`. |

## Wiring wifi credentials

The library never reads TOML itself: it takes a `WifiConfig` and connects.  `WifiService.from_config(config)` is the construction path the standard pipeline uses, reading credentials from your project's runtime config under the `wifi.*` keys (`wifi.ssid`, `wifi.password`) through the same `WifiConfig.from_config(config)` loader that also works standalone.  To get those credentials onto the device, deploy them as part of a workspace-based deploy or a raw single-file deploy.  The bundled `connect_to_ap.py` example and the on-device acceptance test both read the credentials this way and skip silently when none are configured.

## Contributing

Issues, bug reports, and pull requests are welcome, and so is "I ran it on this board and here's what happened", some of the most useful feedback a hardware project can get.  Development happens in the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), whose contributing guide covers setup and the test workflow.

## Docs

📖 **[Stable docs](https://chumicro.com/ChuMicro/wifi/stable/)** · **[Experimental docs](https://chumicro.com/ChuMicro/wifi/experimental/)**

## Find this library

- **PyPI:** [chumicro-wifi](https://pypi.org/project/chumicro-wifi/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_wifi) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_wifi)
- **Source:** [libraries/wifi](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
