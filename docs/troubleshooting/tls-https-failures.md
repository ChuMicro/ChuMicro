# TLS and HTTPS failures

TLS is the encryption behind `https://` web requests, secure MQTT, and `wss://` websockets. Before a board trusts a server, it checks the server's certificate: who signed it, and whether today falls inside the dates it is valid for. A laptop always knows the date. Most boards start up without it, which causes most TLS failures.

## `ValueError: certificate validity starts in the future`

Set the board's clock from an internet time server once wifi is up, before the first HTTPS request. `chumicro-ntp` asks the server for the time. This code takes `config` from `load_runtime_config()`, and `radio` set to `wifi.radio` on CircuitPython. MicroPython ignores `radio`.

```python
from chumicro_ntp import NTPClient
from chumicro_timing import ticks_ms

client = NTPClient.from_config(config, radio=radio)
request = client.query()
while not request.done:          # check() and handle() collect the reply
    now_ms = ticks_ms()
    if client.check(now_ms):
        client.handle(now_ms)
unix_seconds = request.unix_seconds   # raises the error if no reply came back
```

Then copy the answer into the board's real-time clock, its RTC. On CircuitPython:

```python
import rtc
import time

rtc.RTC().datetime = time.localtime(unix_seconds)
```

On MicroPython:

```python
import machine
import time

if time.gmtime(0)[0] == 2000:    # ESP32 boards count seconds from 2000, not 1970
    unix_seconds -= 946_684_800
year, month, day, hour, minute, second, weekday, _ = time.gmtime(unix_seconds)
machine.RTC().datetime((year, month, day, weekday, hour, minute, second, 0))
```

The `while` loop above waits up to five seconds for the answer, which suits a single wait at startup. A program that must keep moving runs the same `check()` and `handle()` calls inside its main loop instead. The `ntp_query.py` example in `chumicro-ntp` shows that version.

Most boards have no clock battery, so each power-up starts the clock at a date years in the past. The certificate then looks like it isn't valid yet, and the board refuses it.

## An HTTPS request fails against a site whose certificate is valid

Give the connection the authority that signed the server's certificate, as PEM text, the `-----BEGIN CERTIFICATE-----` format:

```python
from chumicro_requests import HttpClient
from chumicro_sockets import ssl_context_with_ca

context = ssl_context_with_ca(pem)   # trusts this authority and checks the certificate against it
client = HttpClient.from_config(config, radio=radio, ssl_context=context)
```

`MQTTClient.from_config` and `WebSocketClient.from_config` take the same `ssl_context=` argument. On MicroPython, `chumicro_sockets.set_default_ca_bundle(pem)` replaces the shipped list for every connection instead. Set the board's clock first, as the previous section shows: with the clock unset, even a certificate from a known authority fails.

A board trusts only a certificate signed by an authority it already knows. CircuitPython firmware carries a list of the common public authorities. On MicroPython, `chumicro-sockets` ships a shorter list of 17 widely used ones, among them Let's Encrypt, DigiCert, Amazon, Google, GlobalSign, and Sectigo, because the full list costs too much memory on a small board. A site signed by an authority outside that list fails the check, and so does your own server with a self-made certificate.

## `OSError: [Errno 12]` during the TLS handshake

- Deploy in flash mode, the default. RAM mode keeps your whole program in memory and leaves too little for the handshake on a Pi Pico W. The deploy switches HTTPS projects to flash automatically unless you pass `--force-deploy-mode ram`.
- Create your network clients at the start of your program, before it fills memory with other objects. [Running out of memory](out-of-memory.md#memoryerror-the-first-time-your-program-imports-a-library-partway-through-a-run) explains how free memory breaks into small gaps over time.

`Errno 12` means the board ran out of memory. The handshake needs about 25 KB of free memory in one piece, on top of everything your program already holds.

## Serving HTTPS or `wss://` from a Pi Pico W on CircuitPython fails with `UnsupportedSSLConfigError`

Serve HTTPS from an ESP32 board on CircuitPython, or run MicroPython on the Pico W. A reverse proxy on another machine, such as Caddy, nginx, or a Cloudflare Tunnel, also works: it handles TLS and forwards plain HTTP to the board.

CircuitPython on the Pi Pico W and Pico 2 W can't act as a TLS server, and forcing it past the error locks up the wifi chip until you unplug the board. HTTPS requests *from* the same board work.
