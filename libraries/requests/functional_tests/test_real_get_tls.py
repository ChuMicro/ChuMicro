"""Real-network HTTPS smoke test for chumicro-requests.

Category 2 — public endpoint, `https://example.com/` interop.

Companion to `test_real_get.py`: drives the runner-shaped HttpClient
over TLS using `chumicro_sockets.ssl_context_with_ca` to pin a small
CA bundle. Catches regressions in the HttpClient + sockets-factory +
pinned-CA-context wiring at the request-pipeline level.

Endpoint: `https://example.com/` — IANA-reserved, ships a small
known body, real CA-signed cert.

Why pin a CA instead of using the runtime's default trust store?
Embedded CP / MP don't ship a real trust store —
`ssl.create_default_context()` on those runtimes returns an empty /
placeholder context, not the CPython equivalent. Pin the issuing
root via `chumicro_sockets.ssl_context_with_ca(pem)` instead.

What we pin: just the root (`SSL.com TLS ECC Root CA 2022`), not
the full chain. mbedTLS validates the server's chain against the
client's trust anchor — the server provides intermediates during the
handshake, so the client only needs the root. Pinning the whole chain
wastes heap and (for this site's chain) drags in a 2025-NotBefore
cross-sign that would force RTC seeding even though the actual
root's NotBefore is 2022-10-21.

Refresh `_CA_PEM` if SSL.com rotates the root (decade cadence, not
month). Grab a fresh root with::

    echo | openssl s_client -showcerts -servername example.com \\
      -connect example.com:443 2>/dev/null \\
      | python -c "import re, sys; \\
        certs=re.findall(r'-----BEGIN.*?-----END CERTIFICATE-----', \\
        sys.stdin.read(), re.DOTALL); \\
        print(certs[-1])"  # last cert in the chain is the root

Skipped at collection time when wifi credentials are missing.

Known platform gaps:

* Pi Pico W MicroPython OOMs inside `ssl.wrap_socket` during the
  TLS handshake — the rp2 port leaves only ~190 KB MicroPython heap,
  and mbedTLS + the wifi + sockets + requests payload doesn't have
  enough headroom. Board-class runtime limit, not a flash-size or
  library-bug issue (the deploy itself fits fine).
* Pi Pico W CircuitPython is known-flaky on TLS post-handshake on
  the rp2-port mbedTLS build — same gap as `sockets/test_real_tls.py`
  at the raw-socket level.

These failures document the runtime gaps rather than hiding them.
The test passes on Lolin S2 (MP + CP) and any board with > 200 KB
post-wifi free heap.
"""

import time

from chumicro_requests import HttpClient
from chumicro_sockets import ssl_context_with_ca
from chumicro_sockets.sockets_factory import connector_factory
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_ms

_TARGET_URL = "https://example.com/"
_REQUEST_TIMEOUT_MS = 20_000

# Trust anchor for example.com — `SSL.com TLS ECC Root CA 2022`,
# the root that anchors the chain Cloudflare presents. NotBefore
# 2022-10-21; valid through 2037. Single root, not a chain — see
# module docstring for the rationale.
_CA_PEM = """\
-----BEGIN CERTIFICATE-----
MIIDNDCCArmgAwIBAgIQYE2K+NALqHSLlVhTFyxfLjAKBggqhkjOPQQDAzBOMQsw
CQYDVQQGEwJVUzEYMBYGA1UECgwPU1NMIENvcnBvcmF0aW9uMSUwIwYDVQQDDBxT
U0wuY29tIFRMUyBFQ0MgUm9vdCBDQSAyMDIyMB4XDTIyMTAyMTE3MDIyM1oXDTM3
MTAxNzE3MDIyMlowTzELMAkGA1UEBhMCVVMxGDAWBgNVBAoMD1NTTCBDb3Jwb3Jh
dGlvbjEmMCQGA1UEAwwdU1NMLmNvbSBUTFMgVHJhbnNpdCBFQ0MgQ0EgUjIwdjAQ
BgcqhkjOPQIBBgUrgQQAIgNiAARk532ZA1NckR7q+NgjraG/LOJjie8oaPbt1/Ds
q2iudyvkdpcbUOvbWSgtb7g2uauNl8pMIp7uidkCP/16czqQjSvMLzo3g9oNtC1F
G3NyCWVfeCE954tmP0f9CSnWFA+jggFZMIIBVTASBgNVHRMBAf8ECDAGAQH/AgEB
MB8GA1UdIwQYMBaAFImPL6PoK6AUVHvzVrgmX2c4C5zQMEwGCCsGAQUFBwEBBEAw
PjA8BggrBgEFBQcwAoYwaHR0cDovL2NlcnQuc3NsLmNvbS9TU0xjb20tVExTLVJv
b3QtMjAyMi1FQ0MuY2VyMD8GA1UdIAQ4MDYwNAYEVR0gADAsMCoGCCsGAQUFBwIB
Fh5odHRwczovL3d3dy5zc2wuY29tL3JlcG9zaXRvcnkwHQYDVR0lBBYwFAYIKwYB
BQUHAwIGCCsGAQUFBwMBMEEGA1UdHwQ6MDgwNqA0oDKGMGh0dHA6Ly9jcmxzLnNz
bC5jb20vU1NMY29tLVRMUy1Sb290LTIwMjItRUNDLmNybDAdBgNVHQ4EFgQUMqLH
2FiL/3/APPJVaTPszswfvJcwDgYDVR0PAQH/BAQDAgGGMAoGCCqGSM49BAMDA2kA
MGYCMQC4SkI+e2cts1nTN9MCRil97z624WxLAp94hT7tNZGPZLe9YiLIyzgKqW/b
E0b2h9ACMQCvV5XMRcunAylQaCQc4J/GwR1p7yrPC0DRWWeyLAkQWi5Ylta9DxlX
74QFFksFCP0=
-----END CERTIFICATE-----
"""


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _seed_rtc(now_utc_tuple: tuple) -> None:
    """Set the device RTC from `now_utc_tuple` so cert validity-time checks pass.

    Boot RTC on most ports lands at 2021-01-01 / epoch. Without
    seeding, mbedTLS rejects every cert with "validity starts in the
    future" because the chain's NotBefore is well after epoch. Real
    deployments NTP-sync; this test bakes the host clock at session
    start (conftest) so the test stays off the network for time.
    """
    try:
        import machine
        machine.RTC().datetime((
            now_utc_tuple[0], now_utc_tuple[1], now_utc_tuple[2],
            0,
            now_utc_tuple[3], now_utc_tuple[4], now_utc_tuple[5], 0,
        ))
        return
    except (ImportError, AttributeError):
        pass
    try:
        from time import struct_time

        import rtc
        rtc.RTC().datetime = struct_time((
            now_utc_tuple[0], now_utc_tuple[1], now_utc_tuple[2],
            now_utc_tuple[3], now_utc_tuple[4], now_utc_tuple[5],
            0, 0, -1,
        ))
    except (ImportError, AttributeError):
        pass


def test_real_https_get_completes_runner_shaped() -> None:
    """Live HTTPS GET drives to completion via a pinned-CA TLS context."""
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

    _seed_rtc(config["requests.now_utc_tuple"])

    radio, ip = wifi_up(ssid, password)
    print(f"WIFI_OK ip={ip}")

    ssl_context = ssl_context_with_ca(_CA_PEM)
    client = HttpClient(
        transport_factory=connector_factory(
            radio=radio,
            ssl_context=ssl_context,
        ),
        default_timeout_ms=_REQUEST_TIMEOUT_MS,
        max_body_bytes=8192,
    )
    request = client.get(_TARGET_URL, timeout_ms=_REQUEST_TIMEOUT_MS)

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

    response = request.result
    print(
        f"GOT {response.status_code} bytes={len(response.body)} "
        f"led_ticks={led_counter}",
    )

    assert response.status_code == 200, (
        f"expected 200, got {response.status_code}"
    )
    assert response.body, "response body should be non-empty"
    assert b"Example Domain" in response.body, (
        "response body should contain example.com's marker text"
    )
    # No led_counter floor: the TLS handshake inside the underlying
    # socket factory is synchronous, so a small fast response can
    # complete in 1-2 outer ticks. The cooperative invariant for
    # plain HTTP is verified by test_real_get.py; this test's job is
    # the HTTPS round-trip itself.
