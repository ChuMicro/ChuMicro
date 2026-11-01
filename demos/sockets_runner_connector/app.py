"""Echo a line off a server every five seconds, and never freeze the board.

This is the file that runs on the board.  It joins wifi, then every five
seconds opens a TCP connection to a small echo server running on your
laptop, sends one line, reads the same line back, and hangs up.  A
heartbeat prints once a second the whole time, so you can see that no
step of the round trip stops the program.

``echo_once`` below is one round trip, written as a function you read
top to bottom.  Every ``yield from`` is a place it pauses so the rest of
the board gets a turn; it picks up on that same line once the socket is
ready.

What you will see::

      ...still ticking
    WIFI_OK ip=10.0.0.42
    CONNECTING host=10.0.0.5 port=54321
      ...still ticking
    CONNECTED
    SENT bytes=15
    ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
      echo 1: 'hello chumicro' came back
    DEMO_COMPLETE
      ...still ticking
      ...still ticking
      ...still ticking
      ...still ticking
    CONNECTING host=10.0.0.5 port=54321
      ...still ticking
    CONNECTED
    SENT bytes=15
    ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
      echo 2: 'hello chumicro' came back

It never stops.  When the script on your laptop finishes, it shuts the
echo server down, and from then on each round prints ``ECHO_FAILED`` and
tries again five seconds later.  Start the server again and the echoes
come back on their own.

The UPPERCASE lines are for the script running on your laptop, which
reads them to follow how far the board got.  They are ordinary ``print``
calls: the format is just ``NAME key=value``, and the values have to be
free of spaces and ``=`` signs so the laptop side can split them apart.
That is why the payload rides as hex rather than as text.

Try changing ``PROBE_PAYLOAD`` or ``ECHO_EVERY_MS`` and running it again.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_runner.generators import sleep_until
from chumicro_sockets import connector
from chumicro_sockets.generators import connect, recv_until, send_all
from chumicro_timing import ticks_add, ticks_ms
from chumicro_timing.waits import Signal, wait_for
from chumicro_wifi import WifiConfig, WifiService, WifiState

PROBE_PAYLOAD = b"hello chumicro\n"
MAX_REPLY_BYTES = 256
ECHO_EVERY_MS = 5000


def echo_once(radio, host, port):
    """Send ``PROBE_PAYLOAD`` to the echo server and return the line that comes back."""
    print(f"CONNECTING host={host} port={port}")
    sock = yield from connect(connector(host, port, radio=radio))
    print("CONNECTED")
    try:
        yield from send_all(sock, PROBE_PAYLOAD)
        print(f"SENT bytes={len(PROBE_PAYLOAD)}")
        reply = yield from recv_until(sock, b"\n", max_bytes=MAX_REPLY_BYTES)
    finally:
        # Runs whether the lines above finished or raised, so no socket is left open.
        sock.close()
    payload = reply.rstrip(b"\n")
    print(f"ECHO_RECEIVED bytes={len(payload)} payload_hex={payload.hex()}")
    return payload


def echo_forever(wifi, link_up, host, port):
    """Wait for wifi, then run ``echo_once`` every five seconds, forever."""
    yield from wait_for(link_up)
    print(f"WIFI_OK ip={wifi.ip}")

    echoes = 0
    while True:
        try:
            payload = yield from echo_once(wifi.adapter.radio, host, port)
            echoes += 1
            print(f"  echo {echoes}: {payload.decode()!r} came back")
            if echoes == 1:
                print("DEMO_COMPLETE")
        except Exception as error:
            print(f"ECHO_FAILED error={type(error).__name__}")
            print(f"  detail: {error!r}, trying again in five seconds")
        yield from sleep_until(ticks_add(ticks_ms(), ECHO_EVERY_MS))


def heartbeat(now_ms):
    """Runs once a second, whatever else is going on."""
    print("  ...still ticking")


def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


def signal_link_up(_old, new):
    """Tells the echo loop it can start."""
    if new == WifiState.CONNECTED:
        link_up.set(new)


config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
link_up = Signal()
wifi.on_state_change(signal_link_up)

runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add_periodic(heartbeat, period_ms=1000)
runner.add_generator(echo_forever(
    wifi, link_up, config["sockets.echo.host"], int(config["sockets.echo.port"]),
))

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.  Your own project's
# loop looks exactly like this one.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
