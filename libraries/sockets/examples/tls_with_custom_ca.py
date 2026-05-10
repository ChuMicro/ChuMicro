"""TLS example — connect with a custom CA bundle.

Demonstrates :func:`ssl_context_with_ca` — the "default everything
except the trust anchor" recipe for TLS clients.  Useful when
talking to a self-hosted HTTPS / MQTT / etc. server with its own
CA, when you don't want to add the CA to the device's system trust
store.

This example uses ``letsencrypt.org:443`` + an embedded ISRG Root
X1 PEM as a stable public test target.  ``ssl_context_with_ca``
builds an SSL context whose only trust anchor is what you pass —
the device's system trust store is *not* consulted.  REPLACE
``CA_PEM`` with your homelab CA bytes and the host string with
your own server when adapting.

ISRG Root X1 valid through 2035-06-04.  If the example ever fails
after a Let's Encrypt CA rotation, re-pin via::

    openssl s_client -connect letsencrypt.org:443 -showcerts

Edit ``WIFI_SSID`` / ``WIFI_PASSWORD`` below for raw deploys, or
set ``wifi.ssid`` / ``wifi.password`` in your ``secrets.toml`` and
deploy via::

    chumicro-workspace deploy-example sockets tls_with_custom_ca --device <id>

Example output::

    WIFI_OK ip=10.0.0.42
    sent: GET / HTTP/1.0
    received 256 bytes (head): b'HTTP/1.1 200 OK\\r\\nServer: ...'
    closed cleanly

Substrate quirks observed on real boards:

* **Pi Pico W on MicroPython (rp2 mbedTLS)** rejects self-signed
  certs with ``ValueError('invalid cert')`` regardless of SAN
  shape.  Use a properly-CA-signed cert (or skip TLS to that
  specific server-side combination).
* **MicroPython rp2 firmware boots with the system clock at
  2021-01-01.**  TLS validation fails with ``ValueError: The
  certificate validity starts in the future`` against any leaf
  cert whose ``notBefore`` is more recent.  Sync the clock from
  NTP (built-in ``ntptime.settime()``) before the TLS handshake
  or use a CircuitPython board (CP sets the clock from cyw43 /
  firmware base sufficiently close to current).  This example is
  marked CircuitPython-only via ``__chumicro_runtimes__`` to
  avoid the trap on the canonical sweep matrix.
* **IP-only SAN certs** trip stricter mbedTLS builds.  Generate
  certs with at least one DNS SAN (mDNS ``hostname.local`` works
  on a LAN); set ``server_hostname=`` to that DNS name.
"""

#: CircuitPython-only because MicroPython rp2 needs NTP-sync first
#: (see Substrate quirks in the docstring).  Marker keeps the sweep
#: harness from running this on MP boards.
__chumicro_runtimes__ = ("circuitpython",)

from chumicro_sockets import ssl_context_with_ca, tls_client_socket
from helpers import wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 — replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 — replace before deploying

# ISRG Root X1 — the trust anchor for letsencrypt.org's cert chain.
# Self-signed; valid through 2035-06-04.  Replace with your real CA
# bundle bytes when adapting to a homelab / self-hosted endpoint.
CA_PEM = (
    b"-----BEGIN CERTIFICATE-----\n"
    b"MIIFazCCA1OgAwIBAgIRAIIQz7DSQONZRGPgu2OCiwAwDQYJKoZIhvcNAQELBQAw\n"
    b"TzELMAkGA1UEBhMCVVMxKTAnBgNVBAoTIEludGVybmV0IFNlY3VyaXR5IFJlc2Vh\n"
    b"cmNoIEdyb3VwMRUwEwYDVQQDEwxJU1JHIFJvb3QgWDEwHhcNMTUwNjA0MTEwNDM4\n"
    b"WhcNMzUwNjA0MTEwNDM4WjBPMQswCQYDVQQGEwJVUzEpMCcGA1UEChMgSW50ZXJu\n"
    b"ZXQgU2VjdXJpdHkgUmVzZWFyY2ggR3JvdXAxFTATBgNVBAMTDElTUkcgUm9vdCBY\n"
    b"MTCCAiIwDQYJKoZIhvcNAQEBBQADggIPADCCAgoCggIBAK3oJHP0FDfzm54rVygc\n"
    b"h77ct984kIxuPOZXoHj3dcKi/vVqbvYATyjb3miGbESTtrFj/RQSa78f0uoxmyF+\n"
    b"0TM8ukj13Xnfs7j/EvEhmkvBioZxaUpmZmyPfjxwv60pIgbz5MDmgK7iS4+3mX6U\n"
    b"A5/TR5d8mUgjU+g4rk8Kb4Mu0UlXjIB0ttov0DiNewNwIRt18jA8+o+u3dpjq+sW\n"
    b"T8KOEUt+zwvo/7V3LvSye0rgTBIlDHCNAymg4VMk7BPZ7hm/ELNKjD+Jo2FR3qyH\n"
    b"B5T0Y3HsLuJvW5iB4YlcNHlsdu87kGJ55tukmi8mxdAQ4Q7e2RCOFvu396j3x+UC\n"
    b"B5iPNgiV5+I3lg02dZ77DnKxHZu8A/lJBdiB3QW0KtZB6awBdpUKD9jf1b0SHzUv\n"
    b"KBds0pjBqAlkd25HN7rOrFleaJ1/ctaJxQZBKT5ZPt0m9STJEadao0xAH0ahmbWn\n"
    b"OlFuhjuefXKnEgV4We0+UXgVCwOPjdAvBbI+e0ocS3MFEvzG6uBQE3xDk3SzynTn\n"
    b"jh8BCNAw1FtxNrQHusEwMFxIt4I7mKZ9YIqioymCzLq9gwQbooMDQaHWBfEbwrbw\n"
    b"qHyGO0aoSCqI3Haadr8faqU9GY/rOPNk3sgrDQoo//fb4hVC1CLQJ13hef4Y53CI\n"
    b"rU7m2Ys6xt0nUW7/vGT1M0NPAgMBAAGjQjBAMA4GA1UdDwEB/wQEAwIBBjAPBgNV\n"
    b"HRMBAf8EBTADAQH/MB0GA1UdDgQWBBR5tFnme7bl5AFzgAiIyBpY9umbbjANBgkq\n"
    b"hkiG9w0BAQsFAAOCAgEAVR9YqbyyqFDQDLHYGmkgJykIrGF1XIpu+ILlaS/V9lZL\n"
    b"ubhzEFnTIZd+50xx+7LSYK05qAvqFyFWhfFQDlnrzuBZ6brJFe+GnY+EgPbk6ZGQ\n"
    b"3BebYhtF8GaV0nxvwuo77x/Py9auJ/GpsMiu/X1+mvoiBOv/2X/qkSsisRcOj/KK\n"
    b"NFtY2PwByVS5uCbMiogziUwthDyC3+6WVwW6LLv3xLfHTjuCvjHIInNzktHCgKQ5\n"
    b"ORAzI4JMPJ+GslWYHb4phowim57iaztXOoJwTdwJx4nLCgdNbOhdjsnvzqvHu7Ur\n"
    b"TkXWStAmzOVyyghqpZXjFaH3pO3JLF+l+/+sKAIuvtd7u+Nxe5AW0wdeRlN8NwdC\n"
    b"jNPElpzVmbUq4JUagEiuTDkHzsxHpFKVK7q4+63SM1N95R1NbdWhscdCb+ZAJzVc\n"
    b"oyi3B43njTOQ5yOf+1CceWxG1bQVs5ZufpsMljq4Ui0/1lvh+wjChP4kqKOJ2qxq\n"
    b"4RgqsahDYVvTH9w7jXbyLeiNdd8XM2w9U/t7y0Ff/9yi0GE44Za4rF2LN9d11TPA\n"
    b"mRGunUHBcnWEvgJBQl9nJEiU0Zsnvgc/ubhPgXRR4Xq37Z0j4r7g1SgEEzwxA57d\n"
    b"emyPxgcYxn/eR44/KJ4EBs+lVDR3veyJm+kXQ99b21/+jh5Xos1AnX5iItreGCc=\n"
    b"-----END CERTIFICATE-----\n"
)

radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

context = ssl_context_with_ca(CA_PEM)
sock = tls_client_socket("letsencrypt.org", 443, context=context, radio=radio)
try:
    sock.send(b"GET / HTTP/1.0\r\nHost: letsencrypt.org\r\nConnection: close\r\n\r\n")
    print("sent: GET / HTTP/1.0")
    buffer = bytearray(256)
    nbytes_read = sock.recv_into(buffer, 256)
    head = bytes(buffer[:nbytes_read])[:80]
    print(f"received {nbytes_read} bytes (head): {head!r}")
finally:
    sock.close()
    print("closed cleanly")
