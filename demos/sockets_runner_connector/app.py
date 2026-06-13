"""Board-side echo demo — sockets via runner, generator shape.

``echo_run`` expresses the full lifecycle top-to-bottom: build a
``SocketConnector``, drive it to ``ready`` via ``connect``, send a
probe via ``send_all``, receive the echo via ``recv_until``, close.
``Runner.add_generator`` drives it across ticks; the wait-tokens
the helpers yield gate ipoll wake-ups on the right socket events.

Compare with ``demos/sockets_runner_connector_explicit/app.py`` —
the same wire behaviour expressed as an explicit ``check`` / ``handle``
state machine.  Read that one to see what the generator helpers
collapse.

Marker lines (``WIFI_OK``, ``CONNECTING``, ``CONNECTED``, ``SENT``,
``ECHO_RECEIVED``, ``DEMO_COMPLETE``) drive the host driver.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_sockets.generators import connect, recv_until, send_all
from chumicro_sockets import tcp_client_connector
from chumicro_wifi import WifiConfig, WifiService, WifiState

PROBE_PAYLOAD = b"hello chumicro\n"
MAX_REPLY_BYTES = 256


def echo_run(host, port, radio):
    print(f"CONNECTING host={host} port={port}")
    sock = yield from connect(tcp_client_connector(host, port, radio=radio))
    print("CONNECTED")
    try:
        yield from send_all(sock, PROBE_PAYLOAD)
        print(f"SENT bytes={len(PROBE_PAYLOAD)}")
        reply = yield from recv_until(sock, b"\n", max_bytes=MAX_REPLY_BYTES)
        payload = reply.rstrip(b"\n")
        print(f"ECHO_RECEIVED bytes={len(payload)} payload={payload!r}")
        print("DEMO_COMPLETE")
    finally:
        sock.close()


config = load_runtime_config()
echo_host = config["sockets.echo.host"]
echo_port = int(config["sockets.echo.port"])

wifi = WifiService(WifiConfig.from_config(config))
runner = Runner()
runner.add(wifi)

echo_handle = None


def on_wifi_state(_old, new):
    global echo_handle  # noqa: PLW0603
    if new == WifiState.CONNECTED:
        print(f"WIFI_OK ip={wifi.ip}")
        echo_handle = runner.add_generator(
            echo_run(echo_host, echo_port, radio=wifi.adapter.radio),
        )


wifi.on_state_change(on_wifi_state)

while echo_handle is None or not echo_handle.done:
    now_ms = runner.tick()
    runner.wait(now_ms)
