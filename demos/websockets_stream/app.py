"""Board-side of the websockets_stream demo — receive a message stream.

Brings wifi up with ``chumicro_wifi.WifiService``, connects a
``WebSocketClient`` to the host's WebSocket server, then a generator
loop receives messages with ``yield from ws.next_message()``: wait for
a message, print it, wait for the next, until the server closes the
stream.

The session and the receive generator are both registered with the
runner — the session does the frame I/O each tick, the generator drains
the messages.  Compare with the callback form (``ws.on_text`` /
``ws.on_binary``): the generator loop reads wait-process-wait
top-to-bottom instead of dispatching into a handler.

Marker lines (``WIFI_OK``, ``WS_OPEN``, ``MESSAGE``, ``STREAM_CLOSED``,
``DEMO_COMPLETE``) drive the host driver via stdout markers.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_websockets import WebSocketClient
from chumicro_wifi import WifiConfig, WifiService, WifiState

config = load_runtime_config()
stream_url = config["websockets.stream.url"]

wifi = WifiService(WifiConfig.from_config(config))
ws = WebSocketClient.from_config(config, radio=wifi.adapter.radio)
runner = Runner()
runner.add(wifi)

receive_handle = None


def receive_stream(session):
    received = 0
    while True:
        message = yield from session.next_message()
        if message is None:
            break
        received += 1
        text = message.text if message.is_text else repr(message.data)
        print(f"MESSAGE seq={received} text={text}")
    print(f"STREAM_CLOSED count={received} code={session.last_close_code}")
    print("DEMO_COMPLETE")


def on_wifi_state(_old, new):
    global receive_handle  # noqa: PLW0603
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        ws.connect(stream_url)
        runner.add(ws)
        receive_handle = runner.add_generator(receive_stream(ws))


ws.on_open = lambda: print("WS_OPEN")
wifi.on_state_change(on_wifi_state)

while receive_handle is None or not receive_handle.done:
    now_ms = runner.tick()
    runner.wait(now_ms)
