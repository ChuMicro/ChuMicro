"""Receive a stream of websocket messages, without blocking the board.

This is the file that runs on the board.  It waits for wifi, opens a
websocket to a small server running on your laptop, then reads messages
as they arrive until the server closes the stream.  A heartbeat prints
once a second through all of it, so you can see that waiting on the
network never froze the program.

``receive_stream`` below is the reading loop written as one function you
read top to bottom: wait for a message, print it, wait for the next.
Every ``yield from`` marks a place it pauses and the rest of the board
gets its turn.  The alternative is the ``on_text`` / ``on_binary``
callbacks, where the same work is split across handlers the library
calls into.

What you will see::

    WIFI_OK ip=10.0.0.42
    WS_OPEN
    MESSAGE seq=1
      text: hello 1
      ...still ticking
    MESSAGE seq=2
      text: hello 2
    STREAM_CLOSED count=2 code=1000
    DEMO_COMPLETE
      ...still ticking
      ...still ticking

Nothing stops after that.  The loop goes on turning, the way a board
program does, and the script on your laptop closes the connection once
it has seen what it came for.

The UPPERCASE lines are for the script running on your laptop, which
reads them to follow how far the board got.  They are ordinary ``print``
calls: the format is just ``NAME key=value``, and the values have to be
free of spaces and ``=`` signs so the laptop side can split them apart.
That is why the message text goes on its own indented line.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_timing.waits import Signal, wait_for
from chumicro_websockets import WebSocketClient
from chumicro_wifi import WifiConfig, WifiService, WifiState


def receive_stream(wifi, link_up, session, url):
    """Read messages until the server closes the stream."""
    yield from wait_for(link_up)
    print(f"WIFI_OK ip={wifi.ip}")

    session.connect(url)
    # The session does the frame I/O each tick, so it needs a turn too.
    runner.add(session)

    received = 0
    while True:
        message = yield from session.next_message()
        if message is None:
            break                       # the server closed the stream
        received += 1
        print(f"MESSAGE seq={received}")
        print(f"  text: {message.text if message.is_text else message.data!r}")

    print(f"STREAM_CLOSED count={received} code={session.last_close_code}")
    print("DEMO_COMPLETE")


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
ws = WebSocketClient.from_config(config, radio=wifi.adapter.radio)
ws.on_open = lambda: print("WS_OPEN")

link_up = Signal()
wifi.on_state_change(signal_link_up)

runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add_periodic(heartbeat, period_ms=1000)
runner.add_generator(
    receive_stream(wifi, link_up, ws, config["websockets.stream.url"]),
)

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.  Your own project's
# loop looks exactly like this one.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
