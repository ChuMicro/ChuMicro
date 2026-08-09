"""Real-network HTTP-server acceptance for chumicro-http-server.

Category 1 — host-side stdlib HTTP client driver.

Brings wifi up on the device, starts an ``HttpServer`` on a real
``chumicro_sockets.listener``, prints ``SERVER_READY ip=<ip> port=<port>``
once the listener is accepting, ticks the server cooperatively until
a route handler fires or the per-test deadline expires, prints
``SERVER_REQUEST_OBSERVED route=<path>`` from inside the handler,
asserts locally that the route did fire, and exits.

The paired host file (``test_real_serve_host.py``) opens a stdlib
``http.client.HTTPConnection`` to the marker's ``ip:port`` and asserts
on the response shape.  Replaces the prior self-loopback variant that
broke on Pi Pico W defaults (consumer routers don't reflect a board's
own packets back to it; host-driver-as-client sidesteps the
hairpinning question entirely).

Skipped at collection time when no credentials are configured — the
conftest's ``set_runtime_config(..., required_keys=...)`` declares
``wifi.ssid`` / ``wifi.password`` as required, so the host plugin
applies ``pytest.mark.skip`` with a clear message before deploy.
Credentials ship from the host conftest as
``/runtime_config.msgpack``.
"""

import time

from chumicro_http_server import HttpServer, build_response
from chumicro_sockets import listener
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

_LISTEN_PORT = 8765
_REQUEST_DEADLINE_MS = 30_000
_TICK_SLEEP_MS = 20


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def test_real_serve_responds_to_host_driver() -> None:
    """The on-device half of the Category 1 host-driver round trip."""
    config = runtime_config()
    radio, ip_address = wifi_up(
        config.get("wifi.ssid"),
        config.get("wifi.password"),
    )
    print(f"WIFI_OK ip={ip_address}")

    server = HttpServer(
        transport_factory=lambda: listener(
            host="0.0.0.0",
            port=_LISTEN_PORT,
            radio=radio,
        ),
    )

    observed_routes: list[str] = []

    @server.route("/ping")
    def ping_route(request):  # noqa: ARG001 - request unused for this fixture
        observed_routes.append("/ping")
        print("SERVER_REQUEST_OBSERVED route=/ping")
        return build_response(200, json={"ok": True})

    # One tick to bind the listener + initialize the accept loop.
    server.handle(ticks_ms())
    print(f"SERVER_READY ip={ip_address} port={_LISTEN_PORT}")

    # Cooperative tick loop: wait for the host-driver's request to
    # land or the per-test deadline to expire.  Reraises as
    # AssertionError so the result-parser reports FAIL with the
    # deadline message.
    deadline = ticks_add(ticks_ms(), _REQUEST_DEADLINE_MS)
    while not observed_routes:
        now = ticks_ms()
        if ticks_diff(deadline, now) <= 0:
            raise AssertionError(
                f"no HTTP request observed within "
                f"{_REQUEST_DEADLINE_MS} ms",
            )
        if server.check(now):
            server.handle(now)
        _sleep_ms(_TICK_SLEEP_MS)

    server.close()
    assert observed_routes == ["/ping"]
