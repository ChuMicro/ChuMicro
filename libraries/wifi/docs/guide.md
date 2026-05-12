# User Guide

## Overview

`chumicro-wifi` is a single wifi service that works the same way on CircuitPython, MicroPython-on-ESP32, MicroPython-on-Pi-Pico-W, and CPython.  Construct it once, hand it to the runner, and it brings the link up, watches for drops, and reconnects on its own — no `CIRCUITPY_WIFI_*` keys, no firmware-level auto-reconnect, no `boot.py` that connects before user code runs.  Owning the radio in one place eliminates a class of "two systems both think they own the radio" bugs.

Public surface: `WifiConfig` (typed settings), `WifiService` (the supervisor), `WifiState` (the five-value state machine), plus `chumicro_wifi.testing.FakeWifi` for downstream library tests.

## Getting started

Typical wiring — config loaded from the deployed runtime-config file, service registered with the runner, ready in a few lines of app code:

```python
from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiConfig, WifiService

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))

runner = Runner()
runner.add(wifi)                 # check/handle integration

while True:
    runner.tick()
    if wifi.connected:
        # do whatever needs the network
        pass
```

`WifiService` calls into the right per-runtime adapter automatically — no platform branches in your app.

## State machine

`WifiState` has five string-sentinel values:

```
DISCONNECTED -> CONNECTING -> CONNECTED
                    |            |
                    |            v
                    |       RECONNECTING (link dropped)
                    |            |
                    v            v
                 FAILED <--- backoff exhausted (if reconnect_max set)
```

`wifi.state` returns the current sentinel; compare with `==`:

```python
if wifi.state == WifiState.CONNECTED:
    ...
```

(Plain string comparison — `enum.Enum` is unavailable on some MicroPython boards, so the sentinels are bare strings.)

`wifi.connected` is shorthand for `state == CONNECTED`.

## Reading IP and errors

After the supervisor reaches `CONNECTED`:

```python
wifi.ip            # "192.168.1.42" or None
wifi.last_error    # last exception caught, if any
wifi.adapter.name  # "cp" / "mp_esp32" / "mp_rp2" / "fake" — useful for logging
```

`last_error` is most informative on MicroPython-ESP32, where the wifi driver raises `OSError("Wifi Internal State Error")` on unreachable AP — the service captures it and surfaces it here.  On CircuitPython, the substrate raises `TimeoutError` / `ConnectionError` (both `OSError` subclasses) but `CpWifiAdapter.connect` catches them and returns `False`, so `last_error` typically stays `None` for unreachable-AP cases — only non-`OSError` failures (e.g. programmer errors) bubble up.  On MicroPython-CYW43 (Pi Pico W) the driver silently leaves `isconnected()` False with no exception, so `last_error` is `None` even though the supervisor is in `RECONNECTING` (see Platform notes).

## State-change notifications

`on_state_change(callback)` appends *callback* to the transition-listener list — every registered callback fires on every transition, in registration order:

```python
def log_transition(old_state, new_state):
    print(f"wifi: {old_state} -> {new_state}")

wifi.on_state_change(log_transition)
```

A common pattern is to wire this into `chumicro-events`' bus so other services can react:

```python
from chumicro_events import EventBus

bus = EventBus()
wifi.on_state_change(bus.publisher("wifi.state"))
```

## Configuration

`WifiConfig.from_config(config)` reads the flat `wifi.*` keys from a `RuntimeConfig` (or plain dict with the same shape).  `try_from_config(config)` is the soft variant that returns `None` when the section isn't deployed.  Accepted keys:

| Key | Required | Default | Notes |
|---|---|---|---|
| `ssid` | ✅ | — | AP SSID. |
| `password` | ✅ | — | WPA passphrase. |
| `hostname` | | `None` | Hostname advertised on the AP. |
| `connect_timeout_ms` | | `15_000` | Per-attempt connect deadline. |
| `reconnect_backoff_start_ms` | | `1_000` | Initial reconnect delay. |
| `reconnect_backoff_max_ms` | | `60_000` | Exponential-backoff cap. |
| `reconnect_max` | | `None` (unlimited) | Attempts before entering `FAILED`. |
| `power_save` | | `False` | Leave radio power-save on.  `False` disables it on Pi Pico W (CYW43); ignored on adapters without the knob. |

```toml
# Inside your project's runtime config (TOML on disk; deploy-flattened to msgpack on the device).
[wifi]
ssid = "HomeNet"
password = "secret"
hostname = "back-porch"
power_save = false                  # default; eliminates ~30-100 ms tick spikes
```

The `power_save = false` default matters on Pi Pico W: the CYW43 chip's idle power-save mode introduces 30–100 ms tick stalls, which visibly stutter LED-blink rhythms and can break sub-second control loops.

## Runner integration

`WifiService` implements the `chumicro-runner` `check(now_ms)` / `handle(now_ms)` contract:

```python
runner = Runner()
runner.add(wifi)
runner.tick()             # advances every registered service one step
```

`check` is cheap (state inspection); `handle` performs at most one wifi-driver call per tick.  On MicroPython that call is non-blocking — association happens in the background and `handle()` returns immediately, so other services keep their tick budget.  On CircuitPython the substrate-level `wifi.radio.connect()` is itself blocking, so `handle()` stalls for up to `connect_timeout_ms` (default 15 000 ms) while in `CONNECTING` / `RECONNECTING` — other services in the same `Runner` (LED heartbeat, an in-flight HTTP request, MQTT keep-alives) pause for that window.  Once `CONNECTED`, every tick is cheap on both runtimes — and connection failures land in `RECONNECTING`, with the next backoff window resuming naturally.

## Adapter detection

`WifiService` picks the right adapter at construction time based on `sys.implementation.name`:

| Runtime | Adapter | File |
|---|---|---|
| CircuitPython | `CpWifiAdapter` (uses `wifi.radio`) | `_adapters/cp.py` |
| MicroPython | `MpWifiAdapter` (handles ESP32 + CYW43) | `_adapters/mp.py` |
| CPython | `FakeWifiAdapter` | `testing.py` |

The `MpWifiAdapter` auto-detects ESP-IDF vs CYW43 by matching `sys.implementation._machine` against a positive whitelist of known CYW43 boards (`CYW43_MACHINES` in `_adapters/mp.py`); anything outside the whitelist falls through to ESP-IDF.  It then applies the right `wlan.config(...)` knobs:

* **ESP-IDF**: `config(reconnects=0)` after first link, to disable the firmware-level auto-reconnect supervisor — `chumicro-wifi` owns reconnect logic itself.
* **CYW43**: `config(pm=0xa11140)` at configure time, to disable idle power-save when `power_save=False`.

The underlying MicroPython `network.WLAN` API (`active`, `connect`, `isconnected`, `ifconfig`, `disconnect`) is identical across both wifi chips, so a single adapter handles both.

## Platform notes

Three runtimes, three different ways an unreachable AP surfaces:

| Runtime + chip | When AP is unreachable |
|---|---|
| CircuitPython `wifi.radio` | Blocks inside `connect()` until `timeout=` expires, raises `TimeoutError` / `ConnectionError` (both are `OSError` subclasses). |
| MicroPython on ESP32 (`network.WLAN`) | Returns immediately from `connect()`, then raises `OSError("Wifi Internal State Error")` on the next interaction. |
| MicroPython on CYW43 (Pi Pico W) | Returns immediately, `isconnected()` silently stays `False`, no exception. |

The supervisor handles all three honestly: each adapter checks `isconnected()` after a connect attempt rather than trusting that a non-raising `connect()` succeeded.

## Testing with `FakeWifi`

For downstream libraries' tests, [`chumicro_wifi.testing.FakeWifi`](testing.md) is a drop-in `WifiService` wrapping a `FakeWifiAdapter` with `set_connect_outcome`, `drop_link`, and `calls` hooks.

## Examples

| Example | What it shows |
|---|---|
| [`examples/connect_to_ap.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi/examples/connect_to_ap.py) | Connect to a real AP, print state transitions, observe IP — reads `wifi.ssid` / `wifi.password` from `runtime_config.msgpack`. |

---

<div class="chumicro-footer" markdown>

[← Home](index.md)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
