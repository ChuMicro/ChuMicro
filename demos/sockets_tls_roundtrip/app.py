"""Board-side of the sockets_tls_roundtrip demo: one-shot TLS with custom CA.

Brings wifi up via ``chumicro_wifi.WifiService`` driven by
``chumicro_runner.Runner``, builds an ``ssl.SSLContext`` whose only
trust anchor is the cert the driver embedded in runtime config, then
dials the driver's TLS echo server with
``chumicro_sockets.connector(tls=True)`` (the one connect state
machine) and lets ``runner.run_until`` drive it to a terminal state.

This is the entry-level TLS pattern: ``ssl_context_with_ca`` builds a
trust anchor from PEM bytes; the connector is registered with the
runner like any other service (it exposes ``check`` / ``handle`` /
``io_*``), so the dial never blocks a tick beyond each phase's
substrate compromise (the TLS handshake is a single blocking tick on
MicroPython; TCP+TLS collapse into one blocking connect on
CircuitPython).  The generator-shaped sibling demo
(``sockets_runner_connector``) expresses the same wire behaviour
top-to-bottom with ``yield from`` helpers.

Marker lines (``WIFI_OK``, ``CONNECTING``, ``CONNECTED``, ``SENT``,
``ECHO_RECEIVED``, ``DEMO_COMPLETE``) drive the host driver via stdout
markers.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_sockets import connector, ssl_context_with_ca
from chumicro_test_harness.markers import marker
from chumicro_wifi import WifiConfig, WifiService, WifiState

_PROBE_PAYLOAD = b"hello chumicro tls\n"

config = load_runtime_config()
echo_host = config["sockets.echo.host"]
echo_port = int(config["sockets.echo.port"])
ca_pem = config["sockets.echo.ca_pem"]
if isinstance(ca_pem, str):
    ca_pem = ca_pem.encode("ascii")

wifi = WifiService(WifiConfig.from_config(config))


def on_wifi_state(_old, new):
    if new == WifiState.CONNECTED:
        marker("WIFI_OK", ip=wifi.ip)


wifi.on_state_change(on_wifi_state)

runner = Runner(on_handler_error=lambda entry, error: print("SERVICE_FAULT", entry.service, repr(error)))
runner.add(wifi)

runner.run_until(lambda: wifi.state == WifiState.CONNECTED)

# Wifi is up.  Dial the TLS echo server with the custom-CA anchor.
# The connector is a runner service: register it raw and run until it
# reaches a terminal state.
context = ssl_context_with_ca(ca_pem)
marker("CONNECTING", host=echo_host, port=echo_port)
dial = connector(
    echo_host, echo_port,
    tls=True, context=context, radio=wifi.adapter.radio,
)
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
marker("ECHO_RECEIVED", bytes=len(payload), payload_hex=payload)
sock.close()
marker("DEMO_COMPLETE")
