"""Board-side echo demo: sockets via runner, generator shape.

``echo_run`` expresses the full lifecycle top-to-bottom: wait for the
wifi link with ``wait_for``, build a ``SocketConnector``, drive it to
``ready`` via ``connect``, send a probe via ``send_all``, receive the
echo via ``recv_until``, close.  ``Runner.add_generator`` drives it
across ticks; the wait-tokens the helpers yield gate ipoll wake-ups
on the right socket events, and the ``Signal`` set from the wifi
state-change callback resumes the generator once the link is up.

Compare with ``demos/sockets_runner_connector_explicit/app.py``:
the same wire behaviour expressed as an explicit ``check`` / ``handle``
state machine.  Read that one to see what the generator helpers
collapse.

Marker lines (``WIFI_OK``, ``CONNECTING``, ``CONNECTED``, ``SENT``,
``ECHO_RECEIVED``, ``DEMO_COMPLETE``) drive the host driver.
"""

from chumicro_config import load_runtime_config
from chumicro_runner import Runner
from chumicro_sockets import connector
from chumicro_sockets.generators import connect, recv_until, send_all
from chumicro_test_harness.markers import marker
from chumicro_timing.waits import Signal, wait_for
from chumicro_wifi import WifiConfig, WifiService, WifiState

PROBE_PAYLOAD = b"hello chumicro\n"
MAX_REPLY_BYTES = 256


def echo_run(wifi, link_up, host, port):
    yield from wait_for(link_up)
    marker("WIFI_OK", ip=wifi.ip)
    marker("CONNECTING", host=host, port=port)
    sock = yield from connect(
        connector(host, port, radio=wifi.adapter.radio),
    )
    marker("CONNECTED")
    try:
        yield from send_all(sock, PROBE_PAYLOAD)
        marker("SENT", bytes=len(PROBE_PAYLOAD))
        reply = yield from recv_until(sock, b"\n", max_bytes=MAX_REPLY_BYTES)
        payload = reply.rstrip(b"\n")
        marker("ECHO_RECEIVED", bytes=len(payload), payload_hex=payload)
        marker("DEMO_COMPLETE")
    finally:
        sock.close()


config = load_runtime_config()
echo_host = config["sockets.echo.host"]
echo_port = int(config["sockets.echo.port"])

wifi = WifiService(WifiConfig.from_config(config))
runner = Runner(on_handler_error=lambda entry, error: print("SERVICE_FAULT", entry.service, repr(error)))
runner.add(wifi)

link_up = Signal()


def signal_link_up(_old, new):
    if new == WifiState.CONNECTED:
        link_up.set(new)


wifi.on_state_change(signal_link_up)

echo_handle = runner.add_generator(echo_run(wifi, link_up, echo_host, echo_port))
runner.run_until(echo_handle)
