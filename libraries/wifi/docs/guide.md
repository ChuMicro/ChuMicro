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

Fan-out needs no bus: every registered callback fires on each transition, so each interested component registers its own `on_state_change` handler directly.

```python
wifi.on_state_change(status_led.on_wifi_state)
wifi.on_state_change(telemetry.on_wifi_state)
```

To let a generator task *block* on a one-time transition — the first time the link comes up, say — bridge the callback to a `Signal` and `yield from wait_for(...)` (both in `chumicro_runner.generators`; see the `chumicro-runner` guide) rather than polling `wifi.state`:

```python
from chumicro_runner.generators import Signal, wait_for

link_up = Signal()
wifi.on_state_change(lambda old, new: link_up.set(new))


def main_run():
    yield from wait_for(link_up)   # suspend until the next wifi transition
    ...
```

## Configuration

`WifiConfig.from_config(config)` reads the flat `wifi.*` keys from a `RuntimeConfig` (or plain dict with the same shape).  `try_from_config(config)` is the soft variant that returns `None` when the section isn't deployed.  Accepted keys:

| Key | Required | Default | Notes |
|---|---|---|---|
| `ssid` | ✅ | — | AP SSID. |
| `password` | ✅ | — | WPA passphrase. |
| `hostname` | | `None` | Hostname advertised on the AP. |
| `connect_timeout_ms` | | `15_000` | Per-attempt connect deadline — a blocking wait on CircuitPython, the in-flight association poll window on MicroPython. |
| `reconnect_backoff_start_ms` | | `1_000` | Initial reconnect delay. |
| `reconnect_backoff_max_ms` | | `60_000` | Exponential-backoff cap. |
| `reconnect_max` | | `None` (unlimited) | Consecutive failed attempts (initial connect + reconnects) before the terminal `FAILED` state. Leave `None` for always-on devices — see below. |
| `power_save` | | `False` | Leave radio power-save on.  `False` disables it on Pi Pico W (CYW43); ignored on adapters without the knob. |
| `tx_power_dbm` | | `None` (radio default) | Radio transmit power in dBm.  `None` leaves the firmware default untouched; set a reduced value (e.g. `15`) on boards unstable at full power.  Applied via `wifi.radio.tx_power` (CP) / `sta.config(txpower=…)` (MP); ignored on ports without the knob. |

```toml
# Inside your project's runtime config (TOML on disk; deploy-flattened to msgpack on the device).
[wifi]
ssid = "HomeNet"
password = "secret"
hostname = "back-porch"
power_save = false                  # default; eliminates ~30-100 ms tick spikes
```

The `power_save = false` default matters on Pi Pico W: the CYW43 chip's idle power-save mode introduces 30–100 ms tick stalls, which visibly stutter LED-blink rhythms and can break sub-second control loops.

`tx_power_dbm` exists for boards that are unreliable at full transmit power. The canonical case is Unexpected Maker's P4-revision ESP32-S3 boards, which are [vendor-documented unstable](https://help.unexpectedmaker.com/docs/boards/wifi-stability-issues/) at full 20 dBm — dropping to `tx_power_dbm = 15` (~75 %) restores a clean join. This knowledge lives in your deploy config, not in the library: `chumicro-wifi` never inspects the board, it only applies the value you set and leaves the radio at its firmware default when the key is absent.

### `reconnect_max` and the never-restart guarantee

Leaving `reconnect_max` at its `None` default is what lets an unattended device ride out an outage without a reboot: the supervisor retries forever with backoff capped at `reconnect_backoff_max_ms`, so a link that comes back after minutes, hours, or a whole-house power blip is re-established on its own. `FAILED` is a **terminal** state — nothing in the service leaves it — so set a finite `reconnect_max` only when a caller *wants* exhaustion to escalate (e.g. to a hardware watchdog reset or deep-sleep), and remember the count includes the initial connect: a low cap can fail permanently in the power-restore race where the board boots faster than the router. For always-on devices, keep it `None`.

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

The underlying MicroPython `network.WLAN` API (`active`, `connect`, `isconnected`, `ifconfig`) is identical across both wifi chips, so a single adapter handles both.

## Platform notes

Three runtimes, three different ways an unreachable AP surfaces:

| Runtime + chip | When AP is unreachable |
|---|---|
| CircuitPython `wifi.radio` | Blocks inside `connect()` until `timeout=` expires, raises `TimeoutError` / `ConnectionError` (both are `OSError` subclasses). |
| MicroPython on ESP32 (`network.WLAN`) | Returns immediately from `connect()`, then raises `OSError("Wifi Internal State Error")` on the next interaction. |
| MicroPython on CYW43 (Pi Pico W) | Returns immediately, `isconnected()` silently stays `False`, no exception. |

The supervisor handles all three honestly: each adapter checks `isconnected()` after a connect attempt rather than trusting that a non-raising `connect()` succeeded.

On the ESP32-S3, a failed or timed-out `wifi.radio.connect()` leaves the station half-open; re-issuing `connect()` without clearing it makes the retry slow-fail for the whole `connect_timeout_ms` (surfacing as `ConnectionError: Unknown failure 205`) instead of the ~4 s a clean attempt takes, so a single transient RF glitch cascades past the connect budget.  `CpWifiAdapter.connect` therefore calls `wifi.radio.stop_station()` before each fresh attempt (and short-circuits when the radio already reports linked), keeping every attempt independent.  This is an intermittent, RF-marginal failure mode — the chip connects in seconds when the station is clean.

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
