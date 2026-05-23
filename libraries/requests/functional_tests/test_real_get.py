"""Real-network acceptance for chumicro-requests.

End-to-end: bring wifi up on the device, issue an HTTP GET against
a stable public endpoint, drive the runner-shaped client to
completion, verify the response.

Skipped at collection time when no credentials are configured —
the conftest's ``set_runtime_config(..., required_keys=...)`` declares
``wifi.ssid`` / ``wifi.password`` as required, so the host plugin
applies ``pytest.mark.skip`` with a clear message before deploy.
Credentials ship from the host conftest as
``/runtime_config.msgpack`` and are read here via
``chumicro_config.load_runtime_config()`` — the same API user code
uses.

Verifies the LED-blink invariant on a real board: an LED-style
counter keeps incrementing on the same loop while the request is
in flight.  No async, no threads — the per-tick ``check`` /
``handle`` gate cooperates with everything else on the runtime.

Endpoint: ``http://example.com/`` is the lowest-friction stable
HTTP endpoint — no TLS, returns a known small body, IANA-reserved
so it won't disappear.  Avoids HTTPS deliberately so this test
runs on Pi Pico W CP, which has a post-handshake EPIPE issue
mid-TLS.
"""

import time

from chumicro_config import config
from chumicro_requests import HttpClient
from chumicro_requests.sockets_factory import chumicro_sockets_connector_factory
from chumicro_timing import ticks_ms as _ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

_TARGET_URL = "http://example.com/"
_REQUEST_TIMEOUT_MS = 10_000
_WIFI_CONNECT_TIMEOUT_MS = 15_000


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _bring_wifi_up(
    wifi_config: WifiConfig, timeout_ms: int = _WIFI_CONNECT_TIMEOUT_MS,
) -> WifiService:
    """Connect to the configured AP, return the linked service."""
    wifi_config.connect_timeout_ms = timeout_ms
    wifi = WifiService(wifi_config)
    deadline = _ticks_ms() + timeout_ms
    while wifi.state != WifiState.CONNECTED:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"wifi did not link within {timeout_ms} ms; "
                f"state={wifi.state}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        _sleep_ms(50)
    return wifi


def test_real_http_get_completes_runner_shaped() -> None:
    """Live HTTP GET drives to completion; LED-blink counter keeps ticking."""
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

    # Build a runner-shaped client using the chumicro_sockets factory.
    client = HttpClient(
        connector_factory=chumicro_sockets_connector_factory(radio=wifi.adapter.radio),
    )
    request = client.get(_TARGET_URL, timeout_ms=_REQUEST_TIMEOUT_MS)

    # Drive the request + an LED-blink counter together.  The counter
    # is the LED-blink invariant: it MUST keep ticking while the
    # request is in flight.  If it stops, somebody block-called.
    led_counter = 0
    deadline = _ticks_ms() + _REQUEST_TIMEOUT_MS + 5_000
    while not request.done:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"request did not complete within deadline; "
                f"state={request.state if hasattr(request, 'state') else 'unknown'}",
            )
        # Cooperate: tick wifi, tick client, blink, sleep.
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        if client.check(_ticks_ms()):
            client.handle(_ticks_ms())
        led_counter += 1
        _sleep_ms(20)

    response = request.result  # raises HttpError on failure
    print(
        f"GOT {response.status_code} bytes={len(response.body)} "
        f"led_ticks={led_counter}",
    )

    # Real assertions about the response.
    assert response.status_code == 200, (
        f"expected 200, got {response.status_code}"
    )
    assert response.body, "response body should be non-empty"
    assert b"Example Domain" in response.body or len(response.body) > 100, (
        "response body should contain example.com's known marker text "
        "or at minimum be substantial"
    )

    # Real assertion about the LED-blink invariant: the counter
    # should have ticked many times during the request.  A
    # blocking call would have left it at 0 or 1.
    assert led_counter > 5, (
        f"LED counter only ticked {led_counter} times — somebody "
        f"block-called during the request"
    )
