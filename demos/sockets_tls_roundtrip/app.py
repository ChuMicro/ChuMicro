"""Board-side of the sockets_tls_roundtrip demo — synchronous TLS with custom CA.

Brings wifi up via ``chumicro_wifi.WifiService`` driven by
``chumicro_runner.Runner``, builds an ``ssl.SSLContext`` whose only
trust anchor is the cert the driver embedded in runtime config,
opens a TLS client socket via ``chumicro_sockets.tls_client_socket``
against the driver's TLS echo server, sends one probe string, reads
the echo back.

This is the entry-level TLS pattern: ``ssl_context_with_ca`` builds a
trust anchor from PEM bytes; ``tls_client_socket`` returns an
already-connected TLS-wrapped socket and the app uses it
synchronously.  The synchronous handshake blocks for the TLS-handshake
duration (100–500 ms on Pi Pico W class boards); the runner-driven
sibling demo (``sockets_runner_connector``) shows the non-blocking
connector form for code that can't pause its tick budget.

Marker lines (``WIFI_OK``, ``CONNECTING``, ``CONNECTED``, ``SENT``,
``ECHO_RECEIVED``, ``DEMO_COMPLETE``) drive the host driver via stdout
markers.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_sockets import ssl_context_with_ca, tls_client_socket
from chumicro_wifi import WifiConfig, WifiService, WifiState

_PROBE_PAYLOAD = b"hello chumicro tls\n"
_RECV_BUFFER_SIZE = 64

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

runner = Runner()
runner.add(wifi)

while wifi.state != WifiState.CONNECTED:
    now_ms = runner.tick()
    runner.wait(now_ms)

# Wifi is up — synchronous TLS round trip with the custom-CA anchor.
context = ssl_context_with_ca(ca_pem)
print(f"CONNECTING host={echo_host} port={echo_port}")
sock = tls_client_socket(echo_host, echo_port, context=context, radio=wifi.adapter.radio)
print("CONNECTED")

sock.send(_PROBE_PAYLOAD)
print(f"SENT bytes={len(_PROBE_PAYLOAD)}")

buffer = bytearray(_RECV_BUFFER_SIZE)
received = bytearray()
while b"\n" not in received:
    number_of_bytes = sock.recv_into(buffer, _RECV_BUFFER_SIZE)
    if number_of_bytes == 0:
        break
    received.extend(buffer[:number_of_bytes])

payload = bytes(received).rstrip(b"\n")
print(f"ECHO_RECEIVED bytes={len(payload)} payload={payload!r}")
sock.close()
print("DEMO_COMPLETE")
