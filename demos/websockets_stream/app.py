"""Board-side of the websockets_stream demo: receive a message stream.

``receive_stream`` expresses the whole lifecycle top-to-bottom: wait
for the wifi link with ``wait_for``, connect the ``WebSocketClient``,
then loop ``yield from session.next_message()``: wait for a message,
print it, wait for the next, until the server closes the stream.  The
``Signal`` set from the wifi state-change callback resumes the
generator once the link is up.

The session and the receive generator are both registered with the
runner: the session does the frame I/O each tick, the generator drains
the messages.  Compare with the callback form (``ws.on_text`` /
``ws.on_binary``): the generator loop reads wait-process-wait
top-to-bottom instead of dispatching into a handler.

Marker lines (``WIFI_OK``, ``WS_OPEN``, ``MESSAGE``, ``STREAM_CLOSED``,
``DEMO_COMPLETE``) drive the host driver via stdout markers.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_test_harness.markers import marker
from chumicro_timing.waits import Signal, wait_for
from chumicro_websockets import WebSocketClient
from chumicro_wifi import WifiConfig, WifiService, WifiState


def receive_stream(wifi, link_up, session, url):
    yield from wait_for(link_up)
    marker("WIFI_OK", ip=wifi.ip)
    session.connect(url)
    runner.add(session)
    received = 0
    while True:
        message = yield from session.next_message()
        if message is None:
            break
        received += 1
        text = message.text if message.is_text else repr(message.data)
        marker("MESSAGE", seq=received)
        print(f"  text: {text}")
    marker("STREAM_CLOSED", count=received, code=session.last_close_code)
    marker("DEMO_COMPLETE")


_DEMO_DEADLINE_MS = 120_000

config = load_runtime_config()
stream_url = config["websockets.stream.url"]

wifi = WifiService(WifiConfig.from_config(config))
ws = WebSocketClient.from_config(config, radio=wifi.adapter.radio)
runner = Runner(on_handler_error=lambda entry, error: print("SERVICE_FAULT", entry.service, repr(error)))
runner.add(wifi)

link_up = Signal()


def signal_link_up(_old, new):
    if new == WifiState.CONNECTED:
        link_up.set(new)


ws.on_open = lambda: marker("WS_OPEN")
wifi.on_state_change(signal_link_up)

receive_handle = runner.add_generator(
    receive_stream(wifi, link_up, ws, stream_url),
)
if not runner.run_until(receive_handle, timeout_ms=_DEMO_DEADLINE_MS):
    marker("DEMO_TIMEOUT", stage="stream")
    raise SystemExit(1)
