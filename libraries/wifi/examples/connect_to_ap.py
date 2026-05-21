"""WifiService: connect to a real AP, print state transitions.

Reads `wifi.ssid` / `wifi.password` from `runtime_config.msgpack`
(deployed from `secrets.toml` by `chumicro-workspace`).

Deploy with::

    chumicro-workspace deploy-example wifi connect_to_ap --device <id>

Example output::

    ADAPTER: cp
    State: disconnected -> connecting
    State: connecting -> connected
    WIFI_OK ip=10.0.0.42
"""

import time

from chumicro_config import load_runtime_config
from chumicro_timing import ticks_diff, ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
wifi.on_state_change(lambda old, new: print(f"State: {old} -> {new}"))

print(f"ADAPTER: {wifi.adapter.name}")

start_ms = ticks_ms()
while wifi.state != WifiState.CONNECTED:
    now_ms = ticks_ms()
    if ticks_diff(now_ms, start_ms) > 15_000:
        print(f"FAIL last_error={wifi.last_error}")
        raise SystemExit(1)
    if wifi.check(now_ms):
        wifi.handle(now_ms)
    time.sleep(0.05)

print(f"WIFI_OK ip={wifi.ip}")
