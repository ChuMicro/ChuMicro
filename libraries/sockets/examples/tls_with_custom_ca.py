"""Fetch a page over TLS, trusting only the certificate authority you choose.

The board joins your wifi, opens an encrypted connection to
letsencrypt.org on port 443, sends a short HTTP request, and prints the
first line of the reply.  Then it closes the connection, waits 30
seconds, and does it all again for as long as it has power.  When a
round trip fails, the board prints what went wrong and tries again on
the next pass.

The connection trusts exactly one certificate authority (CA): the ISRG
Root X1 certificate pasted into ``CA_PEM`` below, which sits at the top
of letsencrypt.org's certificate chain.  The board's built-in list of
trusted CAs plays no part.  This is the recipe for a server whose
certificate your own CA signed, such as an HTTPS or MQTT server on your
home network.  ``ssl_context_with_ca(CA_PEM)`` builds the trust setting
once, and every pass hands it to
``connector(..., tls=True, context=context)``.

Before you run it:

1. Set ``WIFI_SSID`` and ``WIFI_PASSWORD`` below.  If you deploy with
   chumicro-workspace, ``wifi.ssid`` and ``wifi.password`` in your
   ``secrets.toml`` are used instead.
2. Put ``chumicro_sockets`` and this folder's ``helpers.py`` on the
   board, and save this file as ``code.py``.  From a ChuMicro
   workspace, one command does all of that::

       chumicro-workspace deploy-example sockets tls_with_custom_ca --device <id>

What you will see::

    WIFI_OK ip=10.0.0.42
    connecting to letsencrypt.org:443
    reply: HTTP/1.1 200 OK
    next round trip in 30 s
    connecting to letsencrypt.org:443
    reply: HTTP/1.1 200 OK
    next round trip in 30 s

A pass that fails prints ``connect failed:`` or ``send or receive
failed:`` followed by the error, and the next pass starts on schedule.

Pointing it at your own server:

* Paste your CA's PEM text into ``CA_PEM`` and set ``HOST`` to the
  server's DNS name.
* Give the server's certificate at least one DNS name.  Stricter TLS
  builds reject a certificate that names only an IP address; on a home
  network, ``<hostname>.local`` works.

ISRG Root X1 stays valid until 2035-06-04.  If letsencrypt.org moves to
another root first, the connect fails with a certificate error; download
the current root from https://letsencrypt.org/certificates/ and paste
it into ``CA_PEM``.
"""

#: CircuitPython only.  MicroPython on a Pi Pico W boots with its clock at
#: 2021-01-01, so every certificate looks not yet valid until the clock is
#: set from NTP (``ntptime.settime()``) before the first connect.
__chumicro_runtimes__ = ("circuitpython",)

import time

from chumicro_sockets import connector, ssl_context_with_ca
from helpers import wifi_up

WIFI_SSID = "your-wifi-ssid"  # noqa: S105 - replace before deploying
WIFI_PASSWORD = "your-wifi-password"  # noqa: S105 - replace before deploying

HOST = "letsencrypt.org"
PORT = 443
REQUEST = f"GET / HTTP/1.0\r\nHost: {HOST}\r\nConnection: close\r\n\r\n".encode()
REPEAT_EVERY_S = 30  # pause between round trips
TIMEOUT_S = 5  # longest wait for the server on each send and read

# ISRG Root X1, the root CA at the top of letsencrypt.org's certificate chain.
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

# Join wifi.  wifi_up waits until the board has an IP address.
radio, ip = wifi_up(WIFI_SSID, WIFI_PASSWORD)
print(f"WIFI_OK ip={ip}")

# Build the trust setting once: this context accepts only certificates
# that chain up to CA_PEM.
context = ssl_context_with_ca(CA_PEM)

buffer = bytearray(256)  # one receive buffer, reused on every pass

while True:
    print(f"connecting to {HOST}:{PORT}")

    # connector() returns at once.  Each tick() takes the next step (look up
    # the address, open the connection, check the server's certificate)
    # until the state is "ready" or "failed".  tick() takes the time in
    # milliseconds for services that keep deadlines; a connector keeps
    # none, so 0 is fine.
    dial = connector(HOST, PORT, tls=True, context=context, radio=radio)
    while dial.state not in ("ready", "failed"):
        dial.tick(0)
        time.sleep(0.01)

    if dial.state == "failed":
        print(f"connect failed: {dial.last_error!r}")
    else:
        sock = dial.socket
        try:
            # A timeout bounds every send and read, so a server that stops
            # answering costs one pass, not the rest of the program.
            sock.settimeout(TIMEOUT_S)
            sock.send(REQUEST)
            count = sock.recv_into(buffer)
            first_line = bytes(buffer[:count]).split(b"\r\n")[0]
            print(f"reply: {first_line.decode()}")
        except OSError as error:
            print(f"send or receive failed: {error!r}")
        sock.close()

    print(f"next round trip in {REPEAT_EVERY_S} s")
    time.sleep(REPEAT_EVERY_S)
