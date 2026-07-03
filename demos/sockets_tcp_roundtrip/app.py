"""Board-side of the sockets_tcp_roundtrip demo — synchronous TCP.

Brings wifi up via ``chumicro_wifi.WifiService`` driven by
``chumicro_runner.Runner``, then opens a plain TCP client socket via
``chumicro_sockets.tcp_client_socket`` against the driver's echo
server, sends one probe string, reads the echo back.

This is the entry-level sockets pattern: once wifi is up, the
``tcp_client_socket`` factory returns an already-connected socket and
the app uses it synchronously (``send`` / ``recv_into`` / ``close``).
The synchronous connect blocks for the TCP-handshake duration; the
runner-driven sibling demo (``sockets_runner_connector``) shows the
non-blocking connector form for code that can't pause its tick budget.

Marker lines (``WIFI_OK``, ``CONNECTING``, ``CONNECTED``, ``SENT``,
``ECHO_RECEIVED``, ``DEMO_COMPLETE``) drive the host driver via stdout
markers.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_sockets import tcp_client_socket
from chumicro_wifi import WifiConfig, WifiService, WifiState

_PROBE_PAYLOAD = b"hello chumicro\n"
_RECV_BUFFER_SIZE = 64

config = load_runtime_config()
echo_host = config["sockets.echo.host"]
echo_port = int(config["sockets.echo.port"])

wifi = WifiService(WifiConfig.from_config(config))


def on_wifi_state(_old, new):
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")


wifi.on_state_change(on_wifi_state)

runner = Runner()
runner.add(wifi)

# Drive the runner until wifi is up.
while wifi.state != WifiState.CONNECTED:
    now_ms = runner.tick()
    runner.wait(now_ms)

# Wifi is up — synchronous TCP round trip.
print(f"CONNECTING host={echo_host} port={echo_port}")
sock = tcp_client_socket(echo_host, echo_port, radio=wifi.adapter.radio)
print("CONNECTED")

sock.send(_PROBE_PAYLOAD)
print(f"SENT bytes={len(_PROBE_PAYLOAD)}")

buffer = bytearray(_RECV_BUFFER_SIZE)
received = bytearray()
while b"\n" not in received:
    number_of_bytes = sock.recv_into(buffer, _RECV_BUFFER_SIZE)
    if number_of_bytes == 0:  # peer closed before we saw the newline
        break
    received.extend(buffer[:number_of_bytes])

payload = bytes(received).rstrip(b"\n")
# Marker values must be whitespace-free — parse_marker drops the
# whole line otherwise — so the payload rides as hex.
print(f"ECHO_RECEIVED bytes={len(payload)} payload_hex={payload.hex()}")
sock.close()
print("DEMO_COMPLETE")
