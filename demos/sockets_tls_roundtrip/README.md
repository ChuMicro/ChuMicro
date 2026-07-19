# sockets_tls_roundtrip: synchronous TLS with custom CA, wifi via runner

End-to-end demo of `chumicro_sockets.connector(tls=True)` against a host
TLS echo server with a self-signed cert.  Wifi comes up via
`chumicro_wifi.WifiService` driven by `chumicro_runner.Runner`; the
driver generates a fresh cert, runs a TLS echo server, and bakes the
cert PEM into runtime config so the board's
`ssl_context_with_ca(ca_pem)` trust anchor matches.

## What it shows

- **Custom-CA TLS trust anchor.**  `ssl_context_with_ca(pem_bytes)`
  builds an `ssl.SSLContext` whose only trust root is the cert the
  driver embedded.  The system trust store is not consulted: same
  pattern as talking to a homelab CA or a self-signed broker.
- **The full chumicro stack for wifi.**  `WifiService` configured from
  `chumicro_config.load_runtime_config()`, driven by
  `chumicro_runner.Runner` to `WifiState.CONNECTED`.
- **Cross-runtime TLS handshake on real silicon.**  The handshake runs
  via the on-board `ssl` module (firmware-bundled on CP, mbedTLS on MP)
  against the host's CPython TLS server.  Works on Pi Pico W, ESP32-S2,
  ESP32-S3: the same `connector(tls=True)` dial, the same payload back.

## Run it

```bash
.venv/bin/python demos/sockets_tls_roundtrip/driver.py
```

Defaults: targets the first CircuitPython device in `devices.yml`.

Override:

- `--device <id>`: a specific device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython device.
- `--wifi-timeout-s <n>`: how long to wait for the board's `WIFI_OK`
  marker (default 45 s).
- `--completion-timeout-s <n>`: how long to wait for `DEMO_COMPLETE`
  after `WIFI_OK` (default 60 s; TLS handshakes are slower than plain
  TCP, especially on Pi Pico W class boards).

## Expected output

```
driver: tls echo server up on 10.0.0.5:54321
driver: self-signed cert at /tmp/sockets-tls-demo-abc123/cert.pem (CN=10.0.0.5)
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
driver: board WIFI_OK ip=10.0.0.42
driver: board CONNECTING host=10.0.0.5 port=54321
driver: board CONNECTED
driver: board SENT bytes=19
driver: board ECHO_RECEIVED bytes=18 payload_hex=68656c6c6f206368756d6963726f20746c73
driver: demo completed cleanly.
```

## What it requires

- A board registered in `devices.yml`.
- `secrets.toml` at the repo root with `wifi.ssid` + `wifi.password`.
- A reachable wifi network the board can join: the board needs to
  reach the host's LAN IP that the TLS echo server binds to.
- The `cryptography` library (already a transitive chumicro dep via
  ruamel.yaml, should already be in `.venv`).

## Notes

- **CP-rp2 caveat doesn't apply here.**  `chumicro_sockets` blocks
  TLS *server* sockets on CP-rp2 because `wrap_socket(server_side=True)`
  wedges the CYW43 chip; TLS *client* (this demo's role) works fine
  on every supported board.
- **Substrate-blocking handshake.**  The TLS handshake is a single
  blocking connector tick on MicroPython (mbedTLS exposes no
  non-blocking handshake) and folds into the one blocking `connect()`
  on CircuitPython: 100–500 ms on Pi Pico W class boards.  The
  connector keeps DNS and TCP off the tick budget either way.

## Related

- [`sockets_tcp_roundtrip`](../sockets_tcp_roundtrip/): plain TCP
  variant of this demo.
- [`sockets_runner_connector`](../sockets_runner_connector/): TCP
  via the non-blocking connector under runner.
