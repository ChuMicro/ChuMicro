"""Join your wifi network, then report the connection every five seconds.

The board joins the network named in your ``secrets.toml`` and prints each
wifi state change the moment it happens.  Every five seconds after that it
prints its state and IP address, for as long as it has power.

Switch the access point off (a phone hotspot is the easiest one to toggle)
and the board notices the drop, keeps retrying, and prints its IP address
again once the network is back.  Nothing in this file reconnects by hand:
``WifiService`` does that on its own.  The longer the network stays down,
the longer it waits between tries, up to one minute.

Setup:

1. Put your network name and password in ``secrets.toml`` at the root of
   your workspace::

       [wifi]
       ssid = "your-network"
       password = "your-password"

2. Deploy the example.  The deploy copies every library this file imports
   onto the board and turns ``secrets.toml`` into the
   ``/runtime_config.msgpack`` file that ``load_runtime_config()`` reads::

       chumicro-workspace deploy-example wifi connect_to_ap --device <id>

3. Open the board's serial console to watch it run.

Example output, with the access point switched off and back on partway
through::

    joining your-network
    wifi: disconnected -> connecting
    wifi: connecting -> connected
    state=connected ip=10.0.0.42
    state=connected ip=10.0.0.42
    wifi: connected -> reconnecting
    state=reconnecting ip=None
    state=reconnecting ip=None
    wifi: reconnecting -> connected
    state=connected ip=10.0.0.42

On CircuitPython, joining blocks the whole loop for up to 15 seconds per
try, so a status line can arrive late while the board is reconnecting.

Try this: add ``hostname = "back-porch"`` under ``[wifi]`` in
``secrets.toml`` and deploy again.  Your router's list of connected devices
now shows the board by that name.
"""

#: Needs a real radio and access point; a host computer has nothing to join.
__chumicro_runtimes__ = ("circuitpython", "micropython")

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_wifi import WifiService

STATUS_EVERY_MS = 5_000

# Read wifi.ssid and wifi.password from /runtime_config.msgpack on the board.
config = load_runtime_config()

# WifiService picks the radio code for this board, then joins the network,
# watches the link, and rejoins after a drop.
wifi = WifiService.from_config(config)
print(f"joining {config['wifi.ssid']}")


def show_change(old_state, new_state):
    """Print each wifi state change the moment it happens."""
    print(f"wifi: {old_state} -> {new_state}")


def print_status(now_ms):
    """Print the wifi state and IP address, plus the last error if there is one."""
    print(f"state={wifi.state} ip={wifi.ip}")
    if wifi.last_error is not None:
        print(f"  last error: {wifi.last_error!r}")


wifi.on_state_change(show_change)

runner = Runner()
runner.add(wifi)
# print_status runs every five seconds.
runner.add_periodic(print_status, period_ms=STATUS_EVERY_MS)

# The main loop.  tick() lets wifi and the status timer each take one small
# step, and wait() sleeps until one of them next needs a turn.  It never
# ends, which is what a board program does.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
