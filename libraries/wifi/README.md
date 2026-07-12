# chumicro-wifi

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Wifi that auto-reconnects so your app code doesn't have to.**

One WiFi service across CircuitPython (Adafruit boards) and MicroPython on both ESP32 and Pi Pico W.  Owns the radio (no `CIRCUITPY_WIFI_*` settings, no firmware-level auto-reconnect competing with you), surfaces state transitions as events you can wire into the rest of your app via [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner), and reads its config section via [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config).  CircuitPython's substrate-level `connect()` is blocking — see [Platform support](#platform-support) for what that means in practice.

<br clear="left">

> Part of the [ChuMicro](https://github.com/ChuMicro/ChuMicro) family — small, focused Python libraries for microcontrollers and laptops. [Browse all libraries.](https://github.com/ChuMicro/ChuMicro/tree/main/libraries)

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
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()
runner = Runner()
wifi = WifiService(WifiConfig.from_config(config))
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
| `WifiService` | State machine + reconnect supervisor; implements `Runner.add()`-compatible `check`/`handle`. Auto-detects the runtime adapter at construction time (`FakeWifiAdapter` on CPython, `CpWifiAdapter` on CircuitPython, substrate-aware `MpWifiAdapter` on MicroPython — handles ESP-IDF + CYW43 transparently). |
| `WifiState` | String-sentinel state names: `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `RECONNECTING`, `FAILED`. |
| `chumicro_wifi.testing.FakeWifi` | Drop-in `WifiService` wrapping a `FakeWifiAdapter` with `set_connect_outcome`, `drop_link`, `calls` hooks for downstream library tests. |

## Where this fits

Depends on [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) for its config section and registers with [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) for its tick contract.  Provides the radio that the networking layers — [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) on CircuitPython, downstream of that for HTTP / MQTT / WebSocket / NTP — sit on top of.

## Platform support

Works on CPython, MicroPython, and CircuitPython.  Ships three adapters: CircuitPython `wifi.radio` (`_adapters/cp.py`), MicroPython `network.WLAN` covering both ESP-IDF (ESP32 family) and CYW43 (Pi Pico W) stacks (`_adapters/mp.py`), and a `FakeWifiAdapter` for host-side tests.  The right adapter is selected at runtime via `sys.implementation.name`; the MP adapter then auto-detects ESP-IDF vs CYW43 by matching `sys.implementation._machine` against a positive whitelist of known CYW43 boards.

### CircuitPython connect is blocking — read this if you're shipping to CP

CircuitPython's substrate-level `wifi.radio.connect()` is blocking — there is no non-blocking variant exposed by the firmware.  While `WifiService` is `CONNECTING` or `RECONNECTING` on a CircuitPython board, `handle()` stalls for up to `connect_timeout_ms` (default 15 000 ms).  Other services in the same `Runner` — your LED heartbeat, an HTTP request, an MQTT keep-alive — pause for that window.  Once the state reaches `CONNECTED`, the loop runs at full speed again and stays there until the link drops.

MicroPython's `wlan.connect()` is genuinely non-blocking on both ESP32 and Pi Pico W substrates — association happens in the background and `handle()` returns immediately.  If non-blocking connect is load-bearing for your app, prefer MicroPython on RP2040 / RP2350 or ESP32-family boards.

## Examples

| Example | What it shows |
|---|---|
| [`connect_to_ap.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/wifi/examples/connect_to_ap.py) | Connect to a real AP, print state transitions, observe IP — reads `wifi.ssid` / `wifi.password` from `runtime_config.msgpack`. |

## Wiring wifi credentials for examples and functional tests

The acceptance test in `functional_tests/test_acceptance.py` connects to a real AP and skips silently when no credentials are configured.  Two paths for getting credentials onto the device — workspace-based deploy or raw single-file deploy — are documented in [`docs/wiring-wifi-credentials.md`](https://github.com/ChuMicro/ChuMicro/blob/main/docs/wiring-wifi-credentials.md).  The library itself never reads TOML — it takes a `WifiConfig` and goes; `WifiConfig.from_config(config)` is the construction path used by the standard pipeline.

## Contributing

Working on `chumicro-wifi` itself?  Clone the [mono-repo](https://github.com/ChuMicro/ChuMicro) if you haven't already — the rest of the workflow assumes you're inside that workspace.

```bash
pip install -e .[test]
pytest tests/                  # host-side tests
pytest functional_tests/       # on-device tests (needs a board registered in devices.yml)
```

Register a board before running functional tests: `chumicro-workspace add-device <id> --address <port>`.

## Docs

📖 **[Stable docs](https://chumicro.github.io/ChuMicro/wifi/stable/)** · **[Experimental docs](https://chumicro.github.io/ChuMicro/wifi/experimental/)**

## Find this library

- **PyPI:** [chumicro-wifi](https://pypi.org/project/chumicro-wifi/)
- **Bundle:** [ChuMicro-Bundle](https://github.com/ChuMicro/ChuMicro-Bundle/tree/main/chumicro_wifi) (CircuitPython & MicroPython)
- **Experimental bundle:** [ChuMicro-Bundle-Experimental](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental/tree/main/chumicro_wifi)
- **Source:** [libraries/wifi](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi)

## License

[MIT](https://github.com/ChuMicro/ChuMicro/blob/main/LICENSE)
