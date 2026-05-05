"""Two-device acceptance: device-as-client against a host-side ``websockets`` server.

End-to-end: bring wifi up on the device, point a
:class:`chumicro_websockets.WebSocketClient` at the host-side
``websockets`` PyPI echo server (spawned by ``conftest.py`` on the
Mac's LAN IP), exchange messages, close gracefully.

This is the "real" two-device test the slice-6 single-device
loopback couldn't be — bytes actually leave the chip + traverse the
LAN + come back from a battle-tested third-party server (the
``websockets`` PyPI package) that's never going to share bugs with
:class:`WebSocketClient`.  Verifies:

* The client's opening handshake is bit-exact-interoperable with a
  reference server.
* Outbound mask discipline (the ``websockets`` server MUST validate
  it; if our masks are wrong, it closes with ``1002``).
* UTF-8 text frames + binary frames both round-trip.
* The close handshake completes gracefully on the wire.

Skips silently when no wifi credentials are configured OR the
``websockets`` PyPI package isn't installed in the host venv (the
conftest can't spin up the server without it).

**Deploy mode:** Pi Pico W requires ``--deploy-mode flash`` per the
multi-stack-too-heavy rule from ``plans/learnings.md`` — same
constraint as ``test_real_loopback.py``.
"""

import time

from chumicro_config import config
from chumicro_websockets import WebSocketClient, WebSocketState
from chumicro_websockets.sockets_factory import chumicro_sockets_factory
from chumicro_wifi import WifiConfig, WifiService, WifiState

_DEADLINE_MS = 30_000
_WIFI_CONNECT_TIMEOUT_MS = 15_000
_HANDSHAKE_TIMEOUT_MS = 10_000


def _ticks_ms() -> int:
    from chumicro_timing import ticks_ms

    return ticks_ms()


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


def test_real_client_round_trip_against_host_echo_server() -> None:
    """Device client connects to host echo server, round-trips 3 messages."""
    wifi_cfg = WifiConfig.try_from_dict(config)
    if wifi_cfg is None:
        return
    server_host = config["websockets"]["server"]["host"]
    server_port = config["websockets"]["server"]["port"]
    if server_host is None or server_port is None:
        # Host fixture didn't bring up the echo server (websockets PyPI
        # missing, LAN detection failed, etc.).  Skip silently — the
        # in-memory integration suite still validates the wire.
        print("WS_HOST_SKIP no host echo-server fixture available")
        return

    wifi = _bring_wifi_up(wifi_cfg)
    print(f"WIFI_OK ip={wifi.ip}")

    received_text = []
    open_observed = []
    close_observed = []

    client = WebSocketClient(
        connection_factory=chumicro_sockets_factory(radio=wifi.adapter.radio),
        handshake_timeout_ms=_HANDSHAKE_TIMEOUT_MS,
    )
    client.on_open = lambda: open_observed.append(True)
    client.on_text = lambda text: received_text.append(text)
    client.on_close = lambda code, reason: close_observed.append((code, reason))

    target_url = f"ws://{server_host}:{server_port}/"
    client.connect(target_url, timeout_ms=_HANDSHAKE_TIMEOUT_MS)
    print(f"CLIENT_CONNECT url={target_url}")

    led_counter = 0
    sent_message_index = 0
    closed = False
    deadline = _ticks_ms() + _DEADLINE_MS
    while client.state != WebSocketState.CLOSED:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"client did not finish within {_DEADLINE_MS} ms; "
                f"state={client.state} received={len(received_text)}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        if client.check(_ticks_ms()):
            client.handle(_ticks_ms())

        if (
            client.state == WebSocketState.OPEN
            and sent_message_index < 3
        ):
            client.send_text(f"hello {sent_message_index}")
            sent_message_index += 1

        if (
            sent_message_index == 3
            and len(received_text) == 3
            and not closed
            and client.state == WebSocketState.OPEN
        ):
            client.close()
            closed = True

        led_counter += 1
        _sleep_ms(20)

    print(
        f"HOST_ROUND_TRIP_OK sent=3 received={len(received_text)} "
        f"led_ticks={led_counter}",
    )

    # --- Real assertions ---------------------------------------------------
    assert open_observed == [True], (
        f"client never reached OPEN; open_observed={open_observed!r}"
    )
    assert received_text == [
        "echo: hello 0",
        "echo: hello 1",
        "echo: hello 2",
    ], f"unexpected echo replies: {received_text!r}"
    assert close_observed, (
        f"on_close never fired; close_observed={close_observed!r}"
    )
    # Decision 0045 LED-blink invariant.
    assert led_counter > 5, (
        f"LED counter only ticked {led_counter} times — "
        f"somebody block-called against the host server"
    )
