# chumicro-wifi

<img src="https://raw.githubusercontent.com/ChuMicro/ChuMicro/main/support/docs/chumicro_tip.png"
align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

**Wifi that reconnects on its own, so your code doesn't have to.**

`WifiService` joins your network, watches the link, and rejoins after a drop, doubling the pause between failed tries up to one minute.  The same code runs on CircuitPython boards and on MicroPython boards with an ESP32 or a Pi Pico W radio.  It expects to drive the radio alone.  On CircuitPython, leave the `CIRCUITPY_WIFI_*` keys out of `settings.toml`, so the firmware's own auto-connect stays out of its way.  On CircuitPython each join attempt also pauses your loop.  [Platform support](#platform-support) says for how long.

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

The quick example runs on a `Runner` from `chumicro-runner`.  Install it the same way.

[Start here](https://chumicro.com/ChuMicro/guides/start-here/) takes a new board from flashing CircuitPython or MicroPython to running your own blink.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the pre-compiled `.mpy` packages, the experimental channel, and why package names use a hyphen on PyPI and an underscore on the board.

## Quick example

Join the network, then print the state and IP address every five seconds, forever:

```python
from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiService

config = load_runtime_config()  # wifi.ssid and wifi.password, deployed to the board
wifi = WifiService.from_config(config)


def print_status(now_ms):
    print(f"state={wifi.state} ip={wifi.ip}")


runner = Runner()
runner.add(wifi)                # joins, watches the link, rejoins after a drop
runner.add_periodic(print_status, period_ms=5_000)

while True:
    now_ms = runner.tick()      # wifi and the status timer each take one small step
    runner.wait(now_ms)         # sleep until wifi or the status timer is due
```

`load_runtime_config()` reads the settings a `chumicro-workspace` deploy writes to the board.  [Wifi credentials](#wifi-credentials) shows that file, and the way to build the settings in code.

`runner.tick()` runs every job that is due.  `runner.wait(now_ms)` sleeps until the next one is.  `wifi` is a service, an object a loop drives through two methods.  `check(now_ms)` returns `True` when the service has work to do.  `handle(now_ms)` does one small step of that work.  `WifiService` tells `wait()` when it next needs `handle()`, so a loop holding wifi alone still sleeps between passes.  Put your own code in place of `print_status`, and wifi keeps reconnecting in the same loop.

Read the state any time:

```python
wifi.state          # "disconnected", "connecting", "connected", "reconnecting", or "failed"
wifi.connected      # True while the link is up
wifi.ip             # "192.168.1.42" while connected, otherwise None
wifi.last_error     # the last exception the service caught, or None
wifi.on_state_change(lambda old, new: print(f"{old} -> {new}"))   # runs on every change
```

## Wifi credentials

`WifiService` reads no file itself.  It takes a `WifiConfig`, built from the deployed settings or directly in code.

**From the deployed settings.**  In a [ChuMicro workspace](https://chumicro.com/ChuMicro/workspace/stable/), put the credentials in `secrets.toml`:

```toml
[wifi]
ssid = "your-network"
password = "your-password"
```

A deploy writes that file to the board as `/runtime_config.msgpack`.  `load_runtime_config()` reads it back, and `WifiService.from_config(config)` picks out the `wifi.*` keys.  The quick example and `connect_to_ap.py` work this way.  The [guide's Configuration table](https://chumicro.com/ChuMicro/wifi/stable/guide/#configuration) lists every optional key.

**Directly in code**, with no workspace:

```python
from chumicro_wifi import WifiConfig, WifiService

wifi = WifiService(WifiConfig(ssid="your-network", password="your-password"))
```

Keep a real password out of any file you commit.

## What's included

| Symbol | Description |
|---|---|
| `WifiConfig` | Connection settings: `ssid`, `password`, and optional hostname, timeouts, and reconnect tuning.  `WifiConfig.from_config(config)` reads them from the `wifi.*` keys of the deployed settings.  `try_from_config(config)` returns `None` when no wifi section was deployed |
| `WifiService` | Joins the network, watches the link, and rejoins after a drop.  Hand it to a `Runner`, or call its `check(now_ms)` and `handle(now_ms)` from your own loop.  `WifiService.from_config(config)` builds it from the `wifi.*` keys.  It picks the radio code for CircuitPython, MicroPython, or CPython when constructed |
| `WifiState` | The five state names, as plain strings: `DISCONNECTED`, `CONNECTING`, `CONNECTED`, `RECONNECTING`, `FAILED` |
| `chumicro_wifi.testing.FakeWifi` | A `WifiService` on a pretend radio, for testing code that depends on wifi without a board.  `set_connect_outcome`, `drop_link`, `restore_link`, and `calls` script and record what the radio does |

## Where this fits

Depends on [`chumicro-config`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/config) for `from_config` and [`chumicro-timing`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/timing) for the millisecond clock.  Both install with this library.  Runs as a service on a [`chumicro-runner`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/runner) loop, as the quick example shows.

The network libraries run on the link it brings up: pass `wifi.adapter.radio` as the `radio=` argument to [`chumicro-sockets`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/sockets) and the HTTP, MQTT, WebSocket, and NTP clients built on it.  On CircuitPython that value is `wifi.radio`.  On MicroPython it is `None`, because sockets there use the active network interface on their own.

## Platform support

Runs on CircuitPython (`wifi.radio`), on MicroPython with an ESP32-family chip or a Pi Pico W / Pico 2 W (`network.WLAN`), and on CPython.  `WifiService` picks the radio code from `sys.implementation.name`.  On MicroPython it tells the Pico W radio, a CYW43 chip, apart from an ESP32 by the board name the firmware reports.  On CPython the operating system owns the network, so a stand-in reports a connection to `127.0.0.1` straight away.  Tests that need failures and drops use `chumicro_wifi.testing.FakeWifi`.

### On CircuitPython, joining pauses the loop

CircuitPython's `wifi.radio.connect()` blocks.  The firmware has no non-blocking version.  While `WifiService` is joining on a CircuitPython board, each try holds the loop for up to `connect_timeout_ms`, 15 seconds by default.  Everything else in the same `Runner` waits with it: an LED blink, an HTTP request, MQTT keep-alives.  Once connected, the loop runs at full speed until the link drops.

On MicroPython, `wlan.connect()` returns at once on both ESP32 and Pi Pico W.  The radio joins in the background while the loop keeps running.  A board that must keep doing other work while it reconnects wants MicroPython on an RP2040, RP2350, or ESP32-family board.

## Examples

| Example | What it shows |
|---|---|
| [`connect_to_ap.py`](https://github.com/ChuMicro/ChuMicro/blob/main/libraries/wifi/examples/connect_to_ap.py) | Joins your network, prints every state change, and prints the state and IP address every five seconds.  Switch the access point off and on to watch it reconnect |

### Running the examples

`connect_to_ap.py` reads the wifi settings a deploy writes to the board, so it runs through a deploy.  From a clone of the [ChuMicro repository](https://github.com/ChuMicro/ChuMicro), `chumicro-workspace deploy-example wifi connect_to_ap` copies the example and the libraries it imports to the board and takes the wifi settings from `secrets.toml`.  [Wiring wifi credentials](https://chumicro.com/ChuMicro/guides/wiring-wifi-credentials/) walks through `secrets.toml`.

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
