"""Send a line to a server over an encrypted link, every five seconds.

This is the file that runs on the board.  It joins wifi, then every five
seconds opens a *TLS* connection to a small echo server on your laptop,
sends one line, reads the same line back, and hangs up.  TLS is the
encryption behind ``https``.

The server's certificate is one your laptop made up a moment ago, so no
certificate authority your board knows has signed it.  The script on
your laptop hands the board that certificate in its config, and
``ssl_context_with_ca`` turns it into the one thing the board trusts.
That is the same move you make to talk to a broker or server you run
yourself.

Connecting is the slow step: a DNS lookup, a TCP handshake, then the TLS
handshake.  The board hands all three to the runner and keeps turning
its loop while they happen.  After that ``echo_once`` uses the socket
the plain way: ``send`` and ``recv_into`` block, so nothing else on the
board runs until the echo comes back.

What you will see::

    WIFI_OK ip=10.0.0.42
    CONNECTING host=10.0.0.5 port=54321
    CONNECTED
    SENT bytes=19
    ECHO_RECEIVED bytes=18 payload_hex=68656c6c6f206368756d6963726f20746c73
      echo 1: 'hello chumicro tls' came back
    DEMO_COMPLETE
    CONNECTING host=10.0.0.5 port=54321
    CONNECTED
    SENT bytes=19
    ECHO_RECEIVED bytes=18 payload_hex=68656c6c6f206368756d6963726f20746c73
      echo 2: 'hello chumicro tls' came back

It never stops.  When the script on your laptop finishes, it shuts the
echo server down, and from then on each round prints ``ECHO_FAILED`` and
tries again five seconds later.

The UPPERCASE lines are for the script running on your laptop, which
reads them to follow how far the board got.  They are ordinary ``print``
calls: the format is just ``NAME key=value``, and the values have to be
free of spaces and ``=`` signs so the laptop side can split them apart.
That is why the payload rides as hex rather than as text.

Try deleting the ``context=context`` argument: the board falls back to
the certificate authorities it already knows, refuses the made-up
certificate, and every round prints ``ECHO_FAILED``.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_sockets import connector, ssl_context_with_ca
from chumicro_timing import Deadline, ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

PROBE_PAYLOAD = b"hello chumicro tls\n"
ECHO_EVERY_MS = 5000

config = load_runtime_config()
echo_host = config["sockets.echo.host"]
echo_port = int(config["sockets.echo.port"])
ca_pem = config["sockets.echo.ca_pem"]
if isinstance(ca_pem, str):
    ca_pem = ca_pem.encode("ascii")
context = ssl_context_with_ca(ca_pem)


def on_wifi_state(_old, new):
    """Prints the board's address once wifi is up."""
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")


def report_fault(entry, error):
    """Runs if a service raises.  The loop keeps going; this says so."""
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


def echo_once():
    """Dial the echo server over TLS, send ``PROBE_PAYLOAD``, and return the reply."""
    print(f"CONNECTING host={echo_host} port={echo_port}")
    # `dial` is a runner service like wifi.  Add it, turn the same loop
    # until it says `ready` or `failed`, then take it back off the runner.
    # The check sits before wait(): a finished dial asks to be woken for
    # nothing, so wait() would sleep through the moment it finished.
    dial = connector(
        echo_host, echo_port,
        tls=True, context=context, radio=wifi.adapter.radio,
    )
    dialing = runner.add(dial)
    while True:
        now_ms = runner.tick()
        if dial.state in ("ready", "failed"):
            break
        runner.wait(now_ms)
    dialing.remove()
    if dial.state == "failed":
        raise dial.last_error
    print("CONNECTED")

    # From here the socket is just a socket.  setblocking(True) makes send()
    # and recv_into() wait for the network, and the loop waits with them.
    sock = dial.socket
    try:
        sock.setblocking(True)
        sock.send(PROBE_PAYLOAD)
        print(f"SENT bytes={len(PROBE_PAYLOAD)}")
        # Read one byte at a time.  On a Pico W running MicroPython, a
        # blocking TLS read waits until the whole buffer fills, so asking
        # for 64 bytes when 19 are coming would wait forever.
        buffer = bytearray(1)
        received = bytearray()
        while b"\n" not in received:
            if sock.recv_into(buffer, 1) == 0:
                raise OSError("echo server hung up before the newline")
            received.extend(buffer)
    finally:
        sock.close()
    payload = bytes(received).rstrip(b"\n")
    print(f"ECHO_RECEIVED bytes={len(payload)} payload_hex={payload.hex()}")
    return payload


wifi = WifiService(WifiConfig.from_config(config))
wifi.on_state_change(on_wifi_state)

runner = Runner(on_handler_error=report_fault)
runner.add(wifi)

echoes = 0
next_echo = Deadline(ECHO_EVERY_MS, ticks_ms())

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# Anything the program needs to notice is an `if` in between: here, that
# wifi is up and five seconds have passed.  It never ends, which is what
# a board program does.
while True:
    now_ms = runner.tick()
    if wifi.connected and next_echo.expired(now_ms):
        try:
            payload = echo_once()
            echoes += 1
            print(f"  echo {echoes}: {payload.decode()!r} came back")
            if echoes == 1:
                print("DEMO_COMPLETE")
        except Exception as error:
            print(f"ECHO_FAILED error={type(error).__name__}")
            print(f"  detail: {error!r}, trying again in five seconds")
        next_echo.reset(ticks_ms())
    runner.wait(now_ms)
