"""Exchange one line with a TCP server while sharing a Runner loop.

This is the file that runs on the board.  It waits for wifi, opens a TCP
connection to a small echo server running on your laptop, sends one
line, reads the reply, and closes the socket. A heartbeat is scheduled
once a second alongside the exchange. Synchronous work between yields,
including a runtime's blocking connection calls, delays other tasks.

``echo_run`` below is the whole conversation as one function you read top
to bottom. ``yield from`` delegates to a helper. When that helper yields,
control returns to the runner; a helper that finishes immediately lets
this function continue in the same turn.

What you will see::

    WIFI_OK ip=10.0.0.42
    CONNECTING host=10.0.0.5 port=54321
      ...still ticking
    CONNECTED
    SENT bytes=15
    ECHO_RECEIVED bytes=14 payload_hex=68656c6c6f206368756d6963726f
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
That is why the payload rides as hex rather than as text.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_sockets import connector
from chumicro_sockets.generators import connect, recv_until, send_all
from chumicro_timing.waits import Signal, wait_for
from chumicro_wifi import WifiConfig, WifiService, WifiState

PROBE_PAYLOAD = b"hello chumicro\n"
MAX_REPLY_BYTES = 256


def echo_run(wifi, link_up, host, port):
    """Wait for WiFi, exchange one line, and close the connected socket."""
    yield from wait_for(link_up)
    print(f"WIFI_OK ip={wifi.ip}")

    print(f"CONNECTING host={host} port={port}")
    sock = yield from connect(connector(host, port, radio=wifi.adapter.radio))
    print("CONNECTED")

    try:
        yield from send_all(sock, PROBE_PAYLOAD)
        print(f"SENT bytes={len(PROBE_PAYLOAD)}")

        reply = yield from recv_until(sock, b"\n", max_bytes=MAX_REPLY_BYTES)
        payload = reply.rstrip(b"\n")
        print(f"ECHO_RECEIVED bytes={len(payload)} payload_hex={payload.hex()}")
        print("DEMO_COMPLETE")
    finally:
        # Runs whether the lines above returned, raised, or were cancelled.
        sock.close()


def heartbeat(now_ms):
    """Print a heartbeat when the runner dispatches this periodic task."""
    print("  ...still ticking")


def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


def signal_link_up(_old, new):
    """Tells the round trip it can start."""
    if new == WifiState.CONNECTED:
        link_up.set(new)


config = load_runtime_config()
wifi = WifiService(WifiConfig.from_config(config))
link_up = Signal()
wifi.on_state_change(signal_link_up)

runner = Runner(on_handler_error=report_fault)
runner.add(wifi)
runner.add_periodic(heartbeat, period_ms=1000)
runner.add_generator(echo_run(
    wifi, link_up, config["sockets.echo.host"], int(config["sockets.echo.port"]),
))

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.  Your own project's
# loop looks exactly like this one.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
