"""Board-side of the sockets_tcp_roundtrip demo: one-shot TCP.

Brings wifi up via ``chumicro_wifi.WifiService`` driven by
``chumicro_runner.Runner``, then dials the driver's echo server with
``chumicro_sockets.connector`` (the one connect state machine) and
lets ``runner.run_until`` drive it to a terminal state.  Once the
socket is ready the app uses it synchronously (``send`` /
``recv_into`` / ``close``).

This is the entry-level sockets pattern: the connector is registered
with the runner like any other service (it exposes ``check`` /
``handle`` / ``io_*``), so the dial never blocks a tick.  The
generator-shaped sibling demo (``sockets_runner_connector``) expresses
the same wire behaviour top-to-bottom with ``yield from`` helpers.

Marker lines (``WIFI_OK``, ``CONNECTING``, ``CONNECTED``, ``SENT``,
``ECHO_RECEIVED``, ``DEMO_COMPLETE``) drive the host driver via stdout
markers.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_sockets import connector
from chumicro_test_harness.markers import marker
from chumicro_wifi import WifiConfig, WifiService, WifiState

_PROBE_PAYLOAD = b"hello chumicro\n"
_RECV_BUFFER_SIZE = 64

config = load_runtime_config()
echo_host = config["sockets.echo.host"]
echo_port = int(config["sockets.echo.port"])

wifi = WifiService(WifiConfig.from_config(config))


def on_wifi_state(_old, new):
    if new == WifiState.CONNECTED:
        marker("WIFI_OK", ip=wifi.ip)


wifi.on_state_change(on_wifi_state)

runner = Runner(on_handler_error=lambda entry, error: print("SERVICE_FAULT", entry.service, repr(error)))
runner.add(wifi)

# Drive the runner until wifi is up.
runner.run_until(lambda: wifi.state == WifiState.CONNECTED)

# Wifi is up.  Dial the echo server.  The connector is a runner
# service: register it raw and run until it reaches a terminal state.
marker("CONNECTING", host=echo_host, port=echo_port)
dial = connector(echo_host, echo_port, radio=wifi.adapter.radio)
runner.add(dial)
runner.run_until(lambda: dial.state in ("ready", "failed"))
if dial.state == "failed":
    raise dial.last_error
sock = dial.socket
marker("CONNECTED")

# One-shot round trip: blocking reads are fine once the runner has
# nothing else to schedule.
sock.setblocking(True)
sock.send(_PROBE_PAYLOAD)
marker("SENT", bytes=len(_PROBE_PAYLOAD))

buffer = bytearray(_RECV_BUFFER_SIZE)
received = bytearray()
while b"\n" not in received:
    number_of_bytes = sock.recv_into(buffer, _RECV_BUFFER_SIZE)
    if number_of_bytes == 0:  # peer closed before we saw the newline
        break
    received.extend(buffer[:number_of_bytes])

payload = bytes(received).rstrip(b"\n")
marker("ECHO_RECEIVED", bytes=len(payload), payload_hex=payload)
sock.close()
marker("DEMO_COMPLETE")
