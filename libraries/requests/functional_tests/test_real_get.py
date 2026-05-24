"""Real-network acceptance for chumicro-requests.

Category 2 — public endpoint, `http://example.com/` interop.

Brings wifi up on the device, issues an HTTP GET against example.com,
drives the runner-shaped client to completion, asserts the response.
Cooperates with an LED-blink counter on the same loop to verify the
request path doesn't block the runner.

Why public endpoint? A controlled HTTP server would chain the
chumicro-requests client through our own server fixture — green
wouldn't prove the HTTP/1.1 wire format interoperates with real
deployed servers. `example.com` is IANA-reserved, ships a small
known body, and won't disappear.

Why plain HTTP, not HTTPS? Pi Pico W CP has a post-handshake EPIPE
on the rp2-port mbedTLS build. HTTPS coverage is in `test_real_get_tls.py`,
which documents the known gap. This test stays HTTP-only so it runs
green across every board.

Skipped at collection time when wifi credentials are missing.
"""

import time

from chumicro_requests import HttpClient
from chumicro_requests.sockets_factory import chumicro_sockets_connector_factory
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_ms

_TARGET_URL = "http://example.com/"
_REQUEST_TIMEOUT_MS = 10_000


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def test_real_http_get_completes_runner_shaped() -> None:
    """Live HTTP GET drives to completion while an LED-blink counter keeps ticking."""
    config = runtime_config()
    ssid = config.get("wifi.ssid", "")
    password = config.get("wifi.password", "")
    if not ssid:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time. Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )

    radio, ip = wifi_up(ssid, password)
    print(f"WIFI_OK ip={ip}")

    client = HttpClient(
        connector_factory=chumicro_sockets_connector_factory(radio=radio),
    )
    request = client.get(_TARGET_URL, timeout_ms=_REQUEST_TIMEOUT_MS)

    # Drive the request alongside an LED-blink counter. The counter
    # MUST keep ticking while the request is in flight; if it stops,
    # somebody block-called inside the client path.
    led_counter = 0
    deadline = ticks_ms() + _REQUEST_TIMEOUT_MS + 5_000
    while not request.done:
        if ticks_ms() > deadline:
            raise AssertionError(
                f"request did not complete within deadline; "
                f"state={request.state if hasattr(request, 'state') else 'unknown'}",
            )
        if client.check(ticks_ms()):
            client.handle(ticks_ms())
        led_counter += 1
        _sleep_ms(20)

    response = request.result  # raises HttpError on failure
    print(
        f"GOT {response.status_code} bytes={len(response.body)} "
        f"led_ticks={led_counter}",
    )

    assert response.status_code == 200, (
        f"expected 200, got {response.status_code}"
    )
    assert response.body, "response body should be non-empty"
    assert b"Example Domain" in response.body or len(response.body) > 100, (
        "response body should contain example.com's known marker text "
        "or at minimum be substantial"
    )

    # LED-blink invariant: a blocking call inside the client would
    # leave the counter at 0 or 1.
    assert led_counter > 5, (
        f"LED counter only ticked {led_counter} times — somebody "
        f"block-called during the request"
    )
