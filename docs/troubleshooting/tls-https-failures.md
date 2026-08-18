# TLS and HTTPS failures

This page is for failures when a board opens an HTTPS request or a secure WebSocket (`wss://`).  TLS is the encryption behind HTTPS; on a microcontroller it fails for reasons you never see on a laptop, most often an unset clock.  The traps are ordered by how often they bite in the first week.

## `ValueError: certificate validity starts in the future`

A fresh board with no real-time-clock (RTC) battery boots at 2021 (or the Unix epoch).  mbedTLS, the TLS engine on both runtimes, checks the certificate's validity window against that clock, so a perfectly valid cert reads as "not yet valid".  On MicroPython the connection can instead just stop silently.

**Fix.** After wifi connects and before the first TLS handshake, set the RTC from network time (NTP) with `chumicro-ntp`.  Run one query to get the time, then write it into the RTC:

```python
from chumicro_ntp import NTPClient
from chumicro_sockets import udp_socket
from chumicro_timing import ticks_ms
import time

sock = udp_socket(radio=wifi.adapter.radio)
sock.setblocking(False)
client = NTPClient(socket=sock, server="pool.ntp.org")
request = client.query()
while not request.done:
    now = ticks_ms()
    if client.check(now):
        client.handle(now)

utc = time.gmtime(request.unix_seconds)   # server time, before any TLS handshake
```

Then set the board clock.  On CircuitPython:

```python
import rtc
rtc.RTC().datetime = utc
```

On MicroPython:

```python
import machine
machine.RTC().datetime((utc[0], utc[1], utc[2], 0, utc[3], utc[4], utc[5], 0))
```

For local development only, you can instead backdate the cert's `notBefore` so the unset clock still falls inside the window.

## `OSError(12)` inside `wrap_socket()` on a Pi Pico W

`OSError(12)` is ENOMEM, out of memory.  In RAM deploy mode the library bootstrap stays on the heap and leaves under 50 KB free, but the mbedTLS handshake needs about 25 KB on top of an already-loaded heap.  Flash mode (the default) bootstraps from disk instead and leaves roughly 150 KB free.

**Fix.** If you pinned RAM mode, deploy HTTPS and `wss://` workloads in flash mode:

```
chumicro-workspace deploy <project> --deploy-mode flash
```

or set `deploy_mode: flash` for the device in `devices.yml`.  An ESP32-S3 with more than 200 KB of free heap after wifi can do HTTPS in RAM mode.

## The handshake against a real certificate fails even though the cert is valid

The CPython intuition that "the default context loads the system trust store" does not hold on device.  Neither MicroPython (which has no `ssl.create_default_context()`) nor CircuitPython (whose context carries no CAs) bundles a trust store, so nothing on the board can validate the server's certificate.

**Fix.** On both runtimes, pass a context with a certificate authority (CA) pinned.  The CA is the root that signs the server's cert; load its PEM:

```python
from chumicro_sockets import ssl_context_with_ca
context = ssl_context_with_ca(pem)   # returns CERT_REQUIRED with the CA loaded
```

(background: [Decision 0067](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0067-mp-tls-default-trust.md))

## `UnsupportedSSLConfigError`, or a wedged chip, when serving HTTPS or `wss://` on a Pi Pico W

The CYW43 TLS-server handshake path is broken on CircuitPython on the rp2 (adafruit/circuitpython#10339).  `listener(tls=True)` raises `UnsupportedSSLConfigError` up front; if you force it, `wrap_socket(server_side=True)` plus `accept()` raises `OSError(32)` mid-handshake and wedges station mode until a USB power-cycle (`microcontroller.reset()` does not recover it).  The TLS client path on the same board is fine.

**Fix.** Serve HTTPS and `wss://` from an ESP32-family board on CircuitPython, or run MicroPython on the same Pico W.  Or terminate TLS in a front proxy (Caddy, nginx, a Cloudflare Tunnel) and serve plain HTTP behind it.
