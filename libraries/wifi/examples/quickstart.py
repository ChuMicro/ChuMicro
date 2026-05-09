"""WifiService quickstart.

Demonstrates the canonical pattern: read the deployed runtime
config, build a typed ``WifiConfig``, hand it to ``WifiService``,
let the runner drive it.  The library is the sole wifi supervisor
on every runtime — no ``CIRCUITPY_WIFI_*`` keys, no firmware-level
auto-reconnect.

This example uses the in-memory ``FakeWifi`` from
``chumicro_wifi.testing`` so it runs anywhere — CPython, the
MicroPython unix-port, or a real board — without needing live wifi
credentials.  In a real ``app.py`` you'd replace
``WifiService(WifiConfig.from_dict(...))`` for the auto-detected
adapter.

Example output::

    Adapter: fake
    State: disconnected
    State change: disconnected -> connecting
    State change: connecting -> connected
    State: connected, IP: 192.168.0.42
"""

from chumicro_timing.testing import FakeTicks
from chumicro_wifi.testing import FakeWifi

ticks = FakeTicks()
wifi = FakeWifi(ticks)
wifi.set_connect_outcome(True)

wifi.on_state_change(lambda old, new: print(f"State change: {old} -> {new}"))

print(f"Adapter: {wifi.adapter_name}")
print(f"State: {wifi.state}")

wifi.tick()  # one runner-style check + handle cycle

print(f"State: {wifi.state}, IP: {wifi.ip}")
