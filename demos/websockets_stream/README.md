# websockets_stream: your board reads a stream of websocket messages

Your board joins wifi and opens a websocket to a small server the
driver runs on your laptop. The server sends three text messages and
closes the connection. The board prints each message as it arrives,
waits five seconds, and connects again, forever. A heartbeat prints
once a second the whole time, so you can see the board never freezes
while it waits on the network.

Both ends run `chumicro_websockets`: the board runs `WebSocketClient`,
and the laptop runs `WebSocketServer` on CPython.

## What you will see

The driver's own lines start with `driver:`. Everything the board
prints shows up as it happens, after `board |`:

```
driver: websocket stream server up at ws://10.0.0.5:54344/
driver: targeting pi-pico-w-circuitpython-board (circuitpython @ /dev/cu.usbmodem...)
board |   ...still ticking
board |   ...still ticking
board | WIFI_OK ip=10.0.0.42
driver: board WIFI_OK ip=10.0.0.42
board |   connecting to ws://10.0.0.5:54344/
board | MESSAGE seq=1
board |   text: stream message 1
board | MESSAGE seq=2
board |   text: stream message 2
board | MESSAGE seq=3
board |   text: stream message 3
board | STREAM_CLOSED count=3 code=1000
board | DEMO_COMPLETE
driver: board STREAM_CLOSED count=3 code=1000
driver: demo completed cleanly; the board keeps reconnecting.
```

The driver stops there and takes its server with it. The board carries
on: the heartbeat keeps printing every second, and every five seconds
the board connects again and prints `STREAM_CLOSED count=0` now that
nothing answers. To watch it after the driver exits, run
`chumicro-workspace repl --tail 60 --device <id>`.

## What you need

- A board registered with `chumicro-workspace add-device`.
- `secrets.toml` at the repo root with `wifi.ssid` and `wifi.password`.
- A wifi network that your board and your laptop both join.

## Run it

```bash
.venv/bin/python demos/websockets_stream/driver.py
```

The driver picks the first CircuitPython board in `devices.yml`. Pass
`--device <id>` for a specific board or `--runtime micropython` for the
first MicroPython one. `--help` lists the timeouts.

## How it works

The reader in [`app.py`](app.py) is one function that reads top to
bottom:

```python
while True:
    ws = WebSocketClient.from_config(config, radio=wifi.adapter.radio)
    ws.connect(url)
    ws_task = runner.add(ws)               # the client reads its socket each pass
    while True:
        message = yield from ws.next_message()
        if message is None:
            break                          # the server closed the stream
        print(message.text)
    ws_task.remove()
    yield from sleep_until(ticks_add(ticks_ms(), RECONNECT_AFTER_MS))
```

`ws.next_message()` pauses the function until the next message arrives
and hands it back, or returns `None` once the server closes. Each
`yield from` is a place the rest of the board runs, which is how the
heartbeat keeps printing. A `WebSocketClient` connects once, so each
pass builds a fresh one.

The other way to read messages is the `on_text` / `on_binary`
callbacks, where the library calls your handler for each message
instead. `libraries/websockets/examples/client.py` shows that style.

[`driver.py`](driver.py) starts the websocket server on your laptop's
network address, deploys `app.py` with the server URL baked into the
board's config, and checks that the first stream delivered all three
messages.

## Try next

- Change what the server sends in `on_connection` in `driver.py`, or
  change `RECONNECT_AFTER_MS` in `app.py`, and run the demo again.
