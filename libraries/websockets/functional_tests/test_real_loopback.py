"""Real-network acceptance for chumicro-websockets — single-device loopback.

End-to-end: bring wifi up on the device, start a :class:`WebSocketServer`
on a real :func:`chumicro_sockets.listener`, connect a
:class:`WebSocketClient` to it via the device's own LAN IP, drive
both runners through bidirectional traffic and the close handshake.

Skipped at collection time when no credentials are configured —
the conftest's ``set_runtime_config(..., required_keys=...)`` declares
``wifi.ssid`` / ``wifi.password`` as required, so the host plugin
applies ``pytest.mark.skip`` with a clear message before deploy.
On Pi Pico W (rp2 stack) the test body additionally calls
``chumicro_test_harness.skip`` because lwIP doesn't implement
self-loopback there.  Credentials ship from the host conftest as
``/runtime_config.msgpack`` and are read here via
``chumicro_config.load_runtime_config()``.

Verifies the LED-blink invariant on a real board: an LED-style
counter keeps incrementing on the same loop while the handshake,
the frame I/O, and the close handshake all run concurrently
against each other on one device.

HTTP only (``ws://``) — ``wss://`` server adds the
``chumicro_sockets.listener(tls=True)`` constraints documented
in :mod:`chumicro_http_server`'s test_real_serve.py and applies the
same per-board limits.  Cover ``wss://`` server in a follow-up
slice once the four-board matrix has been re-verified for TLS-server
on this stack.

**Deploy mode:** Pi Pico W requires ``--deploy-mode flash``.  RAM-mode
keeps the full library bootstrap on the heap — wifi + sockets +
websockets server + websockets client together exceed the ~150 KB
free heap on a Pi Pico W and the bootstrap fails with
``MemoryError`` before any test code runs.  Lolin S2 (ESP32-S2)
has ~2 MB free heap and runs fine in either mode.
"""

import sys
import time

from chumicro_config import config
from chumicro_sockets import connector
from chumicro_sockets import listener as make_listener
from chumicro_test_harness import skip
from chumicro_timing import ticks_ms as _ticks_ms
from chumicro_websockets import WebSocketClient, WebSocketServer, WebSocketState
from chumicro_wifi import WifiConfig, WifiService, WifiState

_LISTEN_PORT = 8766
_DEADLINE_MS = 30_000
_WIFI_CONNECT_TIMEOUT_MS = 15_000


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _bring_wifi_up(wifi_config: WifiConfig) -> WifiService:
    wifi_config.connect_timeout_ms = _WIFI_CONNECT_TIMEOUT_MS
    wifi = WifiService(wifi_config)
    deadline = _ticks_ms() + _WIFI_CONNECT_TIMEOUT_MS
    while wifi.state != WifiState.CONNECTED:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"wifi did not link within {_WIFI_CONNECT_TIMEOUT_MS} ms; "
                f"state={wifi.state}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        _sleep_ms(50)
    return wifi


_RP2_PLATFORM_PREFIX = ("rp2",)


def _is_pi_pico_w_rp2() -> bool:
    """``True`` on Pi Pico W (rp2040 / rp2350) on either runtime.

    Two distinct platform issues prevent the single-device loopback
    from working on Pi Pico W class boards:

    * **MicroPython:** the rp2 lwIP stack doesn't support a chip
      connecting to its own listening socket via the wifi IP — the
      a plain connect raises ``OSError(103)`` (ECONNABORTED).
      This is independent of chumicro-websockets; chumicro-http-server's
      single-device loopback hits the same limit.
    * **CircuitPython:** the device tends to wedge USB-side under
      load (related cluster of CP-rp2 issues — the same one
      `chumicro_sockets.listener(tls=True)` refuses up-front
      with `UnsupportedSSLConfigError`), which knocks the test
      runner's serial port offline mid-run.

    The library itself works on Pi Pico W — the wire layer + frame
    parser + state machines pass cross-runtime unit tests on both
    ports.  Real-world acceptance needs a two-device setup (Pi Pico W
    as client connecting to a host-side ``websockets`` server, or
    vice versa), which is a follow-up.
    """
    return sys.platform.lower().startswith(_RP2_PLATFORM_PREFIX)


def test_real_websocket_loopback_round_trip() -> None:
    """Server + client on the same device exchange messages over real wifi."""
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time.  Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )
    if _is_pi_pico_w_rp2():
        skip(
            "single-device loopback unsupported on rp2 "
            "(lwIP self-loopback + CP USB wedge cluster); use a two-device "
            "setup or run on the ESP32 family instead",
        )

    wifi = _bring_wifi_up(wifi_cfg)
    print(f"WIFI_OK ip={wifi.ip}")

    # --- Server side ---------------------------------------------------
    server_observed_text = []
    accepted_connections = []

    def on_connection(connection):
        accepted_connections.append(connection)
        connection.on_text = lambda text: (
            server_observed_text.append(text),
            # Echo back with a server-side prefix.
            connection.send_text(f"echo: {text}"),
        )

    listener = make_listener(
        host="0.0.0.0",
        port=_LISTEN_PORT,
        radio=wifi.adapter.radio,
    )
    server = WebSocketServer(
        listener=listener,
        on_connection=on_connection,
        max_connections=1,
    )
    # One server tick + brief sleep so the listener's accept queue is
    # warm before the client (running on the same chip) tries to
    # connect.
    server.handle(_ticks_ms())
    _sleep_ms(50)
    print(f"SERVER_OK port={_LISTEN_PORT}")

    # --- Client side ---------------------------------------------------
    client_observed_text = []
    client_open_ticks = []

    def make_connector(host, port, use_tls):  # noqa: ARG001 - protocol
        return connector(host, port, radio=wifi.adapter.radio)

    client = WebSocketClient(transport_factory=make_connector)
    client.on_open = lambda: client_open_ticks.append(_ticks_ms())
    client.on_text = lambda text: client_observed_text.append(text)

    target_url = f"ws://{wifi.ip}:{_LISTEN_PORT}/loopback"
    client.connect(target_url, timeout_ms=10_000)
    print(f"CLIENT_CONNECT url={target_url}")

    # --- Drive both runners + LED counter together ---------------------
    led_counter = 0
    sent_message_index = 0
    closed = False
    deadline = _ticks_ms() + _DEADLINE_MS
    while True:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"loopback did not complete within {_DEADLINE_MS} ms; "
                f"client.state={client.state} "
                f"server.connection_count={server.connection_count}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        if server.check(_ticks_ms()):
            server.handle(_ticks_ms())
        if client.check(_ticks_ms()):
            client.handle(_ticks_ms())

        # Once the client is OPEN, send 3 messages back-to-back.
        if (
            client.state == WebSocketState.OPEN
            and sent_message_index < 3
        ):
            client.send_text(f"hello {sent_message_index}")
            sent_message_index += 1

        # After all 3 echoes returned, initiate close.
        if (
            sent_message_index == 3
            and len(client_observed_text) == 3
            and not closed
            and client.state == WebSocketState.OPEN
        ):
            client.close()
            closed = True

        # Done when both sides reach CLOSED.
        if (
            client.state == WebSocketState.CLOSED
            and server.connection_count == 0
        ):
            break

        led_counter += 1
        _sleep_ms(20)

    print(
        f"LOOPBACK_OK sent=3 received={len(client_observed_text)} "
        f"server_saw={len(server_observed_text)} led_ticks={led_counter}",
    )

    # --- Real assertions -----------------------------------------------
    assert client_open_ticks, "client never reached OPEN"
    assert server_observed_text == ["hello 0", "hello 1", "hello 2"], (
        f"server expected to receive 3 messages, got {server_observed_text!r}"
    )
    assert client_observed_text == ["echo: hello 0", "echo: hello 1", "echo: hello 2"], (
        f"client expected 3 echoed responses, got {client_observed_text!r}"
    )
    # LED-blink invariant: the counter must have ticked several
    # times during the bidirectional exchange.  A blocking call
    # would have left it near zero.  Threshold matches chumicro-requests
    # test_real_get's `> 5`.  The loopback is fast on the ESP32 family
    # (~8 ticks end-to-end) and the assertion is detecting block-calling,
    # not measuring throughput.
    assert led_counter > 5, (
        f"LED counter only ticked {led_counter} times — "
        f"somebody block-called during loopback"
    )
    server.close()
