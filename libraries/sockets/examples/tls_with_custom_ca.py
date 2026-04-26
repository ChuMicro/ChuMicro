"""TLS example — connect with a custom CA bundle.

Demonstrates :func:`ssl_context_with_ca` — the canonical "default
everything except the trust anchor" recipe.  Useful when talking to
a self-hosted MQTT / HTTPS / etc. server with its own CA, when you
don't want to add the CA to the device's system trust store.

Identical on CPython and MicroPython.  CircuitPython on supported
boards (Pi Pico W, ESP32-S2/S3, ESP32-S3 Feather native wifi) also
works — they ship the on-board ``ssl`` module on current LTS firmware.

Substrate quirks observed on real boards (live-AP acceptance runs):

* **Pi Pico W on MicroPython (rp2 mbedTLS)** rejects self-signed
  certs with ``ValueError('invalid cert')`` regardless of SAN
  shape.  Use a properly-CA-signed cert (or skip TLS to that
  specific server-side combination).
* **IP-only SAN certs** trip stricter mbedTLS builds.  Generate
  certs with at least one DNS SAN (mDNS ``hostname.local`` works
  on a LAN); set ``server_hostname=`` to that DNS name.
"""

import sys

from chumicro_sockets import ssl_context_with_ca, tls_client_socket

# Replace this with your real CA bundle bytes (read from a file or
# bake into your build).  This stub is shaped like a real PEM but is
# NOT a valid cert — TLS will reject it as expected.
CA_PEM = (
    b"-----BEGIN CERTIFICATE-----\n"
    b"# Replace with your real CA bytes.\n"
    b"-----END CERTIFICATE-----\n"
)


def fetch_radio():
    """Return the wifi radio on CP, ``None`` everywhere else.

    Deferred ``import wifi`` so this example parses + imports cleanly
    on CPython during verify-examples; the actual import only fires
    on a CP board where ``wifi`` exists.
    """
    if sys.implementation.name == "circuitpython":
        wifi = __import__("wifi")  # noqa: PLC0415 — CP-only, deferred at runtime

        return wifi.radio
    return None


def run_tls_roundtrip(host: str, port: int) -> None:
    context = ssl_context_with_ca(CA_PEM)
    radio = fetch_radio()
    sock = tls_client_socket(host, port, context=context, radio=radio)
    try:
        sock.send(b"GET / HTTP/1.0\r\n\r\n")
        buffer = bytearray(256)
        nbytes_read = sock.recv_into(buffer, 256)
        print(bytes(buffer[:nbytes_read]))
    finally:
        sock.close()


if __name__ == "__main__":
    run_tls_roundtrip("api.example.com", 443)
