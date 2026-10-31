"""Receive a stream of websocket messages on a board, again every five seconds.

This is the file that runs on the board.  It waits for wifi, opens a
websocket to a small server on your laptop, and prints each message the
server sends until the server closes the connection.  Five seconds later
it connects and does it all again, forever.  A heartbeat prints once a
second through all of it, so you can see that waiting on the network
never freezes the program.

``receive_streams`` below reads top to bottom: connect, wait for a
message, print it, wait for the next.  Every ``yield from`` marks a place
it pauses and the rest of the board gets its turn.

What the board prints::

    WIFI_OK ip=10.0.0.42
      connecting to ws://10.0.0.5:54344/
    MESSAGE seq=1
      text: stream message 1
    MESSAGE seq=2
      text: stream message 2
    MESSAGE seq=3
      text: stream message 3
    STREAM_CLOSED count=3 code=1000
    DEMO_COMPLETE
      ...still ticking
      ...still ticking
      ...still ticking
      ...still ticking
      connecting to ws://10.0.0.5:54344/
    MESSAGE seq=1
      text: stream message 1

The UPPERCASE lines are for the script on your laptop, which reads them
to follow how far the board got.  They are ordinary ``print`` calls in a
``NAME key=value`` shape, and a value may not contain a space or an
``=``.  That is why the message text goes on its own indented line.

When the laptop script finishes, its server goes away.  From then on
each attempt ends in ``STREAM_CLOSED count=0`` and the board tries again
five seconds later.

Try it: change ``RECONNECT_AFTER_MS``, or change what the laptop's
server sends in ``on_connection`` in ``driver.py`` beside this file.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_timing import ticks_add, ticks_ms
from chumicro_timing.waits import Signal, wait_for
from chumicro_websockets import WebSocketClient
from chumicro_wifi import WifiConfig, WifiService, WifiState

RECONNECT_AFTER_MS = 5_000


def receive_streams(url):
    """Connect, print every message until the server closes, wait, repeat."""
    yield from wait_for(link_up)
    print(f"WIFI_OK ip={wifi.ip}")

    streams = 0
    while True:
        print(f"  connecting to {url}")
        ws = WebSocketClient.from_config(config, radio=wifi.adapter.radio)
        ws.connect(url)
        # The client reads its socket on each pass through the loop, so
        # it needs a turn of its own.
        ws_task = runner.add(ws)

        received = 0
        while True:
            message = yield from ws.next_message()
            if message is None:
                break                       # the stream closed, or never opened
            received += 1
            text = message.text if message.is_text else repr(message.data)
            print(f"MESSAGE seq={received}")
            print(f"  text: {text}")

        ws_task.remove()
        print(f"STREAM_CLOSED count={received} code={ws.last_close_code}")
        if received > 0:
            streams += 1
            if streams == 1:
                print("DEMO_COMPLETE")      # the first stream that got through
        yield from sleep_until(ticks_add(ticks_ms(), RECONNECT_AFTER_MS))


def heartbeat(now_ms):
    """Runs once a second, whatever else is going on."""
    print("  ...still ticking")


def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


def signal_link_up(_old, new):
    """Tells the stream reader it can start."""
    if new == WifiState.CONNECTED:
        link_up.set(new)


config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
link_up = Signal()
wifi.on_state_change(signal_link_up)

runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add_periodic(heartbeat, period_ms=1000)
runner.add_generator(receive_streams(config["websockets.stream.url"]))

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
