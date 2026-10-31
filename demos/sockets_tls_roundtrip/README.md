# sockets_tls_roundtrip: the echo round trip over TLS, every five seconds

Your board joins wifi, opens an encrypted TLS connection to an echo
server the driver starts on your laptop, sends `hello chumicro tls`, and
reads the same line back. Five seconds later it does it again, for as
long as the board has power.

The server's certificate is one the driver makes up on the spot, so no
certificate authority your board knows has signed it. The driver hands
the board that certificate in its config, and the board trusts it and
nothing else. That is the same setup you need to talk to a broker or
server you run yourself.

## What you need

- A wifi board (Pi Pico W, ESP32-S2, ESP32-S3) registered with
  `chumicro-workspace add-device`.
- `secrets.toml` at the repo root with `wifi.ssid` and `wifi.password`
  ([wiring wifi credentials](../../docs/wiring-wifi-credentials.md)).
- The board and your laptop on the same network.

The driver makes the certificate with the `cryptography` package, which
the workspace setup already installed.

## Run it

```bash
.venv/bin/python demos/sockets_tls_roundtrip/driver.py
```

The driver deploys [`app.py`](app.py) to the first CircuitPython board
in `devices.yml`. Pick a board with `--device <id>`, or
`--runtime micropython` for the first MicroPython one.

## What you will see

Lines starting `board |` are what the board prints; `driver:` lines come
from the script on your laptop.

```
driver: tls echo server up on 10.0.0.5:54321
driver: self-signed cert at /var/folders/.../sockets-tls-demo-abc123/cert.pem (CN=10.0.0.5)
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
board | WIFI_OK ip=10.0.0.42
board | CONNECTING host=10.0.0.5 port=54321
board | CONNECTED
board | SENT bytes=19
board | ECHO_RECEIVED bytes=18 payload_hex=68656c6c6f206368756d6963726f20746c73
board |   echo 1: 'hello chumicro tls' came back
board | DEMO_COMPLETE
driver: first round trip done; watching 2 more
board | CONNECTING host=10.0.0.5 port=54321
board | CONNECTED
board | SENT bytes=19
board | ECHO_RECEIVED bytes=18 payload_hex=68656c6c6f206368756d6963726f20746c73
board |   echo 2: 'hello chumicro tls' came back
...
board |   echo 3: 'hello chumicro tls' came back
driver: done, stopping the echo server.  The board keeps running; its next rounds print ECHO_FAILED and retry.
```

The driver deletes the certificate and its key when it exits.

## Try next

- Delete `context=context` from the `connector(...)` call in `app.py`.
  The board falls back to the certificate authorities it already knows,
  refuses the made-up certificate, and every round prints
  `ECHO_FAILED`.
- Pass `--watch-rounds 10` to keep the server up for ten more echoes.

## How `app.py` works

- **`ssl_context_with_ca(ca_pem)` builds the trust.** The board trusts
  the one certificate in `ca_pem` and skips its built-in list.
- **`connector(..., tls=True, context=context)` dials.** It runs the DNS
  lookup, the TCP handshake, and the TLS handshake as a runner service,
  the same way [`sockets_tcp_roundtrip`](../sockets_tcp_roundtrip/)
  dials without TLS.
- **Reads go one byte at a time.** On a Pico W running MicroPython, a
  blocking TLS read waits until it has the whole size it asked for, so
  asking for 64 bytes when 19 are coming would wait forever.
- **The TLS handshake blocks the loop for its length**, about 100 to
  500 ms on a Pico W. The connector takes one step per turn of the loop,
  so wifi gets a turn between the DNS lookup, the TCP handshake, and the
  TLS handshake, but neither runtime can split the TLS handshake itself
  into smaller pieces. CircuitPython also runs the TCP and TLS
  handshakes inside one blocking call.

## Next to the other sockets demos

Everything here except the TLS lines matches
[`sockets_tcp_roundtrip`](../sockets_tcp_roundtrip/). Read that one first
if you have not.

## Driver options

- `--device <id>`: a device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython board.
- `--wifi-timeout-s <n>`: how long to wait for `WIFI_OK` (default 45 s).
- `--completion-timeout-s <n>`: how long to wait for `DEMO_COMPLETE`
  (default 60 s, because TLS handshakes take longer).
- `--watch-rounds <n>`: echoes to watch after `DEMO_COMPLETE` before the
  driver stops the echo server (default 2, `0` stops at the first).
