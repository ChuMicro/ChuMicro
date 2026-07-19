# websockets_stream: receive a message stream with `yield from`

End-to-end demo of the `chumicro_websockets` receive-stream API on a
real board.  The driver runs a WebSocket server on the host's LAN IP,
built on `chumicro_websockets.WebSocketServer` itself, so both ends of
the library run in one demo.  On each connection the server streams a
few text messages then closes; the board receives them with a linear
loop:

```python
def receive_stream(ws):
    while True:
        message = yield from ws.next_message()
        if message is None:
            break
        handle(message)

runner.add(ws)                              # drives frame I/O each tick
runner.add_generator(receive_stream(ws))    # drains the messages
```

## What it shows

- **Receive stream as a generator.** `ws.next_message()` suspends until
  the next inbound message and returns it, or `None` once the stream
  closes: wait-process-wait instead of an `on_text` / `on_binary`
  callback.
- **Session + consumer split.** The `WebSocketClient` is registered with
  `runner.add(...)` (it does the recv + frame parse each tick); the
  receive generator is registered with `runner.add_generator(...)` and
  drains the bounded inbound queue the session fills.
- **Both ends of the library.** The host server uses
  `chumicro_websockets.WebSocketServer` on CPython, so a single demo
  exercises the server, the client, and the receive stream.

## Run it

```bash
.venv/bin/python demos/websockets_stream/driver.py
```

Defaults: targets the first CircuitPython device in `devices.yml`.

Override:

- `--device <id>`: a specific device id from `devices.yml`.
- `--runtime micropython`: pick the first MicroPython device.

## Expected output

```
driver: websocket stream server up at ws://10.0.0.5:54344/
driver: targeting raspberry-pi-pico-w-cp (circuitpython @ /dev/cu.usbmodem...)
driver: board WIFI_OK ip=10.0.0.42
driver: board WS_OPEN
driver: board STREAM_CLOSED count=3 code=1000
driver: demo completed cleanly.
```
