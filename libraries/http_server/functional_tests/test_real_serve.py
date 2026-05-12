"""Real-network acceptance for chumicro-http-server.

End-to-end: bring wifi up on the device, start an ``HttpServer``
on a real ``tcp_listening_socket``, hit it from the device itself
via ``chumicro-requests`` (loopback over the LAN — no second
device required), verify the request/response round-trip.

Skipped at collection time when no credentials are configured —
the conftest's ``set_runtime_config(..., required_keys=...)`` declares
``wifi.ssid`` / ``wifi.password`` as required, so the host plugin
applies ``pytest.mark.skip`` with a clear message before deploy.
Credentials
ship from the host conftest as ``/runtime_config.msgpack`` and are
read here via ``chumicro_config.load_runtime_config()``.

Verifies the LED-blink invariant on a real board: an LED-style
counter keeps incrementing on the same loop while the server is
mid-handshake / mid-response.  Uses HTTP only — HTTPS server
verification on Pi Pico W CP is the documented open follow-up.
"""

import time

from chumicro_config import config
from chumicro_http_server import HttpServer, build_response
from chumicro_requests import HttpClient
from chumicro_requests.sockets_factory import chumicro_sockets_factory
from chumicro_sockets import tcp_listening_socket
from chumicro_timing import ticks_ms as _ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

_LISTEN_PORT = 8765
_REQUEST_TIMEOUT_MS = 5_000
_WIFI_CONNECT_TIMEOUT_MS = 15_000
_DEADLINE_MS = 20_000


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
                f"wifi did not link within "
                f"{_WIFI_CONNECT_TIMEOUT_MS} ms; state={wifi.state}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        _sleep_ms(50)
    return wifi


def test_real_serve_and_self_request_round_trip() -> None:
    """Start a server on the device, hit it with the device's own client."""
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time.  Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )

    wifi = _bring_wifi_up(wifi_cfg)
    print(f"WIFI_OK ip={wifi.ip}")

    server = HttpServer(
        listener_factory=lambda: tcp_listening_socket(
            host="0.0.0.0",
            port=_LISTEN_PORT,
            radio=wifi.adapter.radio,
        ),
    )

    @server.route("/ping")
    def ping_route(request):  # noqa: ARG001 - request unused for this fixture
        return build_response(200, json={"ok": True})

    @server.route("/echo", methods=["POST"])
    def echo_route(request):
        return build_response(200, json={"received": request.json()})

    # Start the listener.
    server.handle(_ticks_ms())  # one tick to bind / accept-loop init
    print(f"SERVER_OK port={_LISTEN_PORT}")

    # Hit it from the same device — wifi loopback.
    client = HttpClient(
        connection_factory=chumicro_sockets_factory(radio=wifi.adapter.radio),
    )
    target = f"http://{wifi.ip}:{_LISTEN_PORT}/ping"
    request = client.get(target, timeout_ms=_REQUEST_TIMEOUT_MS)

    led_counter = 0
    deadline = _ticks_ms() + _DEADLINE_MS
    while not request.done:
        if _ticks_ms() > deadline:
            raise AssertionError("self-request did not complete in time")
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        if server.check(_ticks_ms()):
            server.handle(_ticks_ms())
        if client.check(_ticks_ms()):
            client.handle(_ticks_ms())
        led_counter += 1
        _sleep_ms(20)

    response = request.result
    print(
        f"GOT {response.status_code} bytes={len(response.body)} "
        f"led_ticks={led_counter}",
    )

    assert response.status_code == 200
    assert b'"ok"' in response.body and b"true" in response.body
    assert led_counter > 5, (
        f"LED counter only ticked {led_counter} times — somebody "
        f"block-called during the round-trip"
    )

    server.close()
