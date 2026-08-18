"""The same round trip as sockets_tcp_roundtrip, over an encrypted link.

This is the file that runs on the board.  It waits for wifi, opens a
*TLS* connection to a small echo server on your laptop, sends one line,
reads the line that comes back, and closes up.  TLS is the encryption
behind ``https``.

Two things are different from the plain-TCP sibling.  The server's
certificate is signed by a certificate authority your board has never
heard of, so the demo builds a trust anchor from the certificate the
driver handed it in config: that is ``ssl_context_with_ca``.  And the
connection now has a third slow step, the TLS handshake, on top of the
DNS lookup and the TCP handshake.  All three are driven by the runner,
so the loop keeps turning through them.

After that the socket is just a socket, used the blocking way.  As in
the plain-TCP demo, that means nothing else on this board runs while a
read is waiting; ``sockets_runner_connector`` is the shape to copy when
your board has other work to do.

What you will see::

    WIFI_OK ip=10.0.0.42
    CONNECTING host=10.0.0.5 port=54321
    CONNECTED
    SENT bytes=19
    ECHO_RECEIVED bytes=18 payload_hex=68656c6c6f206368756d6963726f20746c73
    DEMO_COMPLETE

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
from chumicro_sockets import connector, ssl_context_with_ca
from chumicro_wifi import WifiConfig, WifiService, WifiState

PROBE_PAYLOAD = b"hello chumicro tls\n"

config = load_runtime_config()
echo_host = config["sockets.echo.host"]
echo_port = int(config["sockets.echo.port"])
ca_pem = config["sockets.echo.ca_pem"]
if isinstance(ca_pem, str):
    ca_pem = ca_pem.encode("ascii")

wifi = WifiService(WifiConfig.from_config(config))


def on_wifi_state(_old, new):
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")


wifi.on_state_change(on_wifi_state)

def report_fault(entry, error):
    """Called when a service raises instead of returning from its turn.

    The runner catches it so one broken service cannot take the whole
    loop down with it.  Saying so out loud is the app's job.
    """
    print(f"SERVICE_FAULT service={type(entry.service).__name__} "
          f"error={type(error).__name__}")
    print(f"  detail: {error!r}")


runner = Runner(on_handler_error=report_fault)
runner.add(wifi)

# Wait for wifi.  This is the loop every ChuMicro program runs: tick()
# gives each registered service one small step, and wait() then parks the
# CPU until the next event or timer deadline.  It runs on a condition
# here only because the code below needs the link before it can dial.
while not wifi.connected:
    now_ms = runner.tick()
    runner.wait(now_ms)

# Wifi is up.  Dial the echo server, this time with TLS and the trust
# anchor built above.  `connector` is a runner service like any other:
# hand it to the runner and turn the same loop until it says `ready` or
# `failed`.  DNS, TCP, and the TLS handshake all happen in there.
context = ssl_context_with_ca(ca_pem)
print(f"CONNECTING host={echo_host} port={echo_port}")
dial = connector(
    echo_host, echo_port,
    tls=True, context=context, radio=wifi.adapter.radio,
)
runner.add(dial)
while dial.state not in ("ready", "failed"):
    now_ms = runner.tick()
    runner.wait(now_ms)
if dial.state == "failed":
    raise dial.last_error
sock = dial.socket
print("CONNECTED")

# From here the socket is just a socket.  setblocking(True) means these
# calls wait for the network instead of returning "not yet", which stops
# the loop above for as long as they take.  See the note at the top.
sock.setblocking(True)
sock.send(PROBE_PAYLOAD)
print(f"SENT bytes={len(PROBE_PAYLOAD)}")

# One byte per read: rp2's mbedTLS blocks a bulk read until the FULL
# requested size arrives (or EOF), so a 256-byte read on a 19-byte
# reply stalls forever.  Delimiter-framed blocking TLS reads on
# MicroPython silicon must read exact sizes: here, one byte at a time.
buffer = bytearray(1)
received = bytearray()
while b"\n" not in received:
    number_of_bytes = sock.recv_into(buffer, 1)
    if number_of_bytes == 0:
        break
    received.extend(buffer[:number_of_bytes])

payload = bytes(received).rstrip(b"\n")
print(f"ECHO_RECEIVED bytes={len(payload)} payload_hex={payload.hex()}")
sock.close()

print("DEMO_COMPLETE")

# The main loop.  tick() gives every registered service one small step,
# and wait() then parks the CPU until the next event or timer deadline.
# It never ends, which is what a board program does.  Your own project's
# loop looks exactly like this one.
while True:
    now_ms = runner.tick()
    runner.wait(now_ms)
