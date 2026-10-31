---
title: "chumicro-wifi: WiFi that reconnects itself on CircuitPython and MicroPython"
---

# chumicro-wifi

**Wifi that reconnects on its own, so your code doesn't have to.**

`WifiService` joins your network, watches the link, and rejoins after a drop, doubling the pause between failed tries up to one minute. The same code runs on CircuitPython boards and on MicroPython boards with an ESP32 or a Pi Pico W radio. Put it in the same loop as the rest of your program and you never write reconnect code yourself.

On MicroPython the radio joins in the background, so an LED blinking in the same loop keeps its rhythm. On CircuitPython each join attempt blocks the loop for up to 15 seconds; the [guide](guide.md#runner-integration) covers what that means. `chumicro-wifi` expects to be the only thing driving the radio, so on CircuitPython leave the `CIRCUITPY_WIFI_*` keys out of `settings.toml` and the firmware's own auto-connect stays out of its way.

## Install

```bash
# CircuitPython (after `circup bundle-add ChuMicro/ChuMicro-Bundle`)
circup install chumicro_wifi

# MicroPython
mpremote mip install github:ChuMicro/ChuMicro-Bundle/chumicro_wifi

# CPython
pip install chumicro-wifi
```

No board running yet?  [Start here](https://chumicro.com/ChuMicro/guides/start-here/) goes from a new board to your own code running on it.  [Installing libraries](https://chumicro.com/ChuMicro/guides/install/) covers registering the bundle, the experimental channel, and the pre-compiled `.mpy` packages.

The quick example also uses `chumicro_runner`; install it the same way.

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
    runner.wait(now_ms)         # then the board sleeps until the status timer is due
```

The [guide](guide.md#getting-started) walks through each line, and [`connect_to_ap.py`](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi/examples/connect_to_ap.py) is the same program with a printout of every state change.

## Documentation

- [User Guide](guide.md): the connect and reconnect state machine, reading IP and errors, state-change notifications, configuration, and runner integration
- [API Reference](api.md): `WifiService`, `WifiConfig`, and the `WifiState` constants
- [Testing Helpers](testing.md): using `FakeWifi` in your tests

---

<div class="chumicro-footer" markdown>

[← All ChuMicro Libraries](../../)

[Source](https://github.com/ChuMicro/ChuMicro/tree/main/libraries/wifi) · \
[PyPI](https://pypi.org/project/chumicro-wifi/) · \
[Bundle](https://github.com/ChuMicro/ChuMicro-Bundle) · \
[Experimental Bundle](https://github.com/ChuMicro/ChuMicro-Bundle-Experimental)

</div>
