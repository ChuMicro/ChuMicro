"""Real-network HTTPS smoke test for chumicro-requests.

Companion to ``test_real_get.py``: drives the runner-shaped
``HttpClient`` over TLS using ``chumicro_sockets.ssl_context_with_ca``
to pin a small CA bundle.  Catches regressions in the
HttpClient + sockets-factory + pinned-CA-context wiring at the
request-pipeline level (where the existing
``libraries/sockets/functional_tests/test_real_tls.py`` only
exercises the raw socket).

Skips silently when no credentials are configured.

Endpoint: ``https://example.com/`` — IANA-reserved, ships a small
known body, real CA-signed cert.

Why pin a CA instead of using the runtime's default trust store?
Pi Pico W's heap can't fit ``ssl.create_default_context()``'s
bundled CA store on either CP or MP — the same memory pressure
chumicro-mqtt's TLS path hit.  Pinning just the few certs in
example.com's chain (~3.7 KB) is the working pattern for that
board class, and it's the one the test exercises.

Refresh the inlined ``_CA_BUNDLE_PEM`` when Cloudflare rotates the
issuing intermediate (typically multi-month cadence).  Grab a fresh
chain with::

    echo | openssl s_client -showcerts -servername example.com \\
      -connect example.com:443 2>/dev/null \\
      | python -c "import re, sys; \\
        certs=re.findall(r'-----BEGIN.*?-----END CERTIFICATE-----', \\
        sys.stdin.read(), re.DOTALL); \\
        print(chr(10).join(certs[1:]))"

Known platform gap (open follow-up in plans/next-up.md): Pi Pico
W CircuitPython hits a post-handshake EPIPE on the rp2-port
mbedTLS build.  This test will fail on that combination; the
failure documents the issue rather than hiding it.
"""

import sys
import time

from chumicro_requests import HttpClient, chumicro_sockets_factory
from chumicro_sockets import ssl_context_with_ca
from chumicro_timing import ticks_ms as _ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

try:
    from _test_creds import NOW_UTC_TUPLE, PASSWORD, SSID
    _HAS_CREDS = True
except ImportError:
    SSID = ""
    PASSWORD = ""
    NOW_UTC_TUPLE = (2025, 1, 1, 0, 0, 0)
    _HAS_CREDS = False


_IS_DEVICE_RUNTIME = sys.implementation.name in ("circuitpython", "micropython")
_TARGET_URL = "https://example.com/"
_REQUEST_TIMEOUT_MS = 20_000
_WIFI_CONNECT_TIMEOUT_MS = 15_000

# CA bundle for example.com's chain (Cloudflare-issued, three certs:
# issuing intermediate, intermediate root, AAA cross-sign).  Refresh
# when example.com's cert chain rotates — see module docstring.
_CA_BUNDLE_PEM = """\
-----BEGIN CERTIFICATE-----
MIIC5DCCAmqgAwIBAgIQLD+iaS9BE707f+W2BLSdTTAKBggqhkjOPQQDAzBPMQsw
CQYDVQQGEwJVUzEYMBYGA1UECgwPU1NMIENvcnBvcmF0aW9uMSYwJAYDVQQDDB1T
U0wuY29tIFRMUyBUcmFuc2l0IEVDQyBDQSBSMjAeFw0yMzEwMzExNzE3NDlaFw0z
MzEwMjgxNzE3NDhaMFIxCzAJBgNVBAYTAlVTMRkwFwYDVQQKDBBDTE9VREZMQVJF
LCBJTkMuMSgwJgYDVQQDDB9DbG91ZGZsYXJlIFRMUyBJc3N1aW5nIEVDQyBDQSAx
MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEByHHIHytNSzTS+F3JA7hHMDGd2cp
cY9i3MLTKmE6DJTKc6JwvW50pwKodvd2Qj4RAAy2jSejsVgw5jeh6syt3KOCASMw
ggEfMBIGA1UdEwEB/wQIMAYBAf8CAQAwHwYDVR0jBBgwFoAUMqLH2FiL/3/APPJV
aTPszswfvJcwSAYIKwYBBQUHAQEEPDA6MDgGCCsGAQUFBzAChixodHRwOi8vY2Vy
dC5zc2wuY29tL1NTTC5jb20tVExTLVQtRUNDLVIyLmNlcjARBgNVHSAECjAIMAYG
BFUdIAAwHQYDVR0lBBYwFAYIKwYBBQUHAwIGCCsGAQUFBwMBMD0GA1UdHwQ2MDQw
MqAwoC6GLGh0dHA6Ly9jcmxzLnNzbC5jb20vU1NMLmNvbS1UTFMtVC1FQ0MtUjIu
Y3JsMB0GA1UdDgQWBBScxAlyRxgXe6caibOSNdXhA4z+kjAOBgNVHQ8BAf8EBAMC
AYYwCgYIKoZIzj0EAwMDaAAwZQIxAL0Sk3RweR6uG1aSHF3JgHQptubP9xoZyUmz
HSa+SSdY5wTGSx5qAowrLPCpLio2PAIwXQGgYzf5QzD/1Bsu87WrUcIVtLixr5KQ
wKBaFAyIJ7OOiWgW0HV/NA1UeuSe0zmN
-----END CERTIFICATE-----
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
-----BEGIN CERTIFICATE-----
MIIEPjCCAyagAwIBAgIQFz3KYOqfjhAm2vzXKBDkjjANBgkqhkiG9w0BAQsFADB7
MQswCQYDVQQGEwJHQjEbMBkGA1UECAwSR3JlYXRlciBNYW5jaGVzdGVyMRAwDgYD
VQQHDAdTYWxmb3JkMRowGAYDVQQKDBFDb21vZG8gQ0EgTGltaXRlZDEhMB8GA1UE
AwwYQUFBIENlcnRpZmljYXRlIFNlcnZpY2VzMB4XDTI1MDgwMTAwMDAwMFoXDTI4
MTIzMTIzNTk1OVowTjELMAkGA1UEBhMCVVMxGDAWBgNVBAoMD1NTTCBDb3Jwb3Jh
dGlvbjElMCMGA1UEAwwcU1NMLmNvbSBUTFMgRUNDIFJvb3QgQ0EgMjAyMjB2MBAG
ByqGSM49AgEGBSuBBAAiA2IABEUpNXP6wrgjzhR9qLFNoFs27iosU8NgCTWyJGYm
acCzldZdkkAZDsalE3D07xJRKF3nzL35PIXBz5SQySvOkkJYWWf9lCcQZIxPBLFN
SeR7T5v15wj4A4j3p8OSSxlUgaOCAZcwggGTMB8GA1UdIwQYMBaAFKARCiM+lvEH
7OKvKe+CpX/QMKS0MB0GA1UdDgQWBBSJjy+j6CugFFR781a4Jl9nOAuc0DAOBgNV
HQ8BAf8EBAMCAYYwEgYDVR0TAQH/BAgwBgEB/wIBAjAdBgNVHSUEFjAUBggrBgEF
BQcDAQYIKwYBBQUHAwIwgZIGA1UdIASBijCBhzAHBgVngQwBATAIBgZngQwBAgEw
CAYGZ4EMAQICMAgGBmeBDAECAzAOBgwrBgEEAYKpMAEDAQEwDgYMKwYBBAGCqTAB
AwECMA4GDCsGAQQBgqkwAQMBAzAOBgwrBgEEAYKpMAEDAQQwDgYMKwYBBAGCqTAB
AwEFMA4GDCsGAQQBgqkwAQMBBjBDBgNVHR8EPDA6MDigNqA0hjJodHRwOi8vY3Js
LmNvbW9kb2NhLmNvbS9BQUFDZXJ0aWZpY2F0ZVNlcnZpY2VzLmNybDA0BggrBgEF
BQcBAQQoMCYwJAYIKwYBBQUHMAGGGGh0dHA6Ly9vY3NwLmNvbW9kb2NhLmNvbTAN
BgkqhkiG9w0BAQsFAAOCAQEAQ+Vw+0vuJDzwOCiGy95GwysrnGBYAFdba+jQTkXY
vkJWGtID1xfyUhKf8tZupwURpkOoVB+9ZvsR15BZ8OSZrRw8Uh32Qz6bYale3PZ8
0izAhlAwSWR0PD7MQxMUxY9b2GsCvSb8z1XgJxfMoZSRRCTVgWDhua7WB2MBdtN+
A88zoXdY/PhVnox0NZbMxXdCSWc2yojUEO3AwcGEcTL9+I1w6A89onNQ0SKfGXs/
Xz6UajT8m0gH1BtdUUbur3aB3+n0zJ/U7u35DKiGv5mmNG81ldZrWjBTJ1T9fxVI
WmmbTVzZvygNMtUumSs5DelljhlJAidAsTc+5iCBJmqRFg==
-----END CERTIFICATE-----
"""


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _seed_rtc(now_utc_tuple: tuple) -> None:
    """Set the device RTC so cert validity-time checks pass.

    Boot RTC on most ports lands at 2021-01-01 / epoch.  Without
    seeding, mbedTLS rejects every cert with "validity starts in
    the future" because the chain's NotBefore is well after epoch.
    Real deployments NTP-sync; this test bakes in the host's clock
    at session start (see conftest.py) so we don't drag NTP in.
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


def _bring_wifi_up(timeout_ms: int = _WIFI_CONNECT_TIMEOUT_MS) -> WifiService:
    wifi = WifiService(
        WifiConfig(
            ssid=SSID,
            password=PASSWORD,
            connect_timeout_ms=timeout_ms,
        ),
    )
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


def test_real_https_get_completes_runner_shaped() -> None:
    """Live HTTPS GET drives to completion via pinned-CA TLS context."""
    if not (_HAS_CREDS and _IS_DEVICE_RUNTIME):
        return

    _seed_rtc(NOW_UTC_TUPLE)

    wifi = _bring_wifi_up()
    print(f"WIFI_OK ip={wifi.ip}")

    ssl_context = ssl_context_with_ca(_CA_BUNDLE_PEM)
    client = HttpClient(
        connection_factory=chumicro_sockets_factory(
            radio=wifi.adapter.radio,
            ssl_context=ssl_context,
        ),
        default_timeout_ms=_REQUEST_TIMEOUT_MS,
        max_body_bytes=8192,
    )
    request = client.get(_TARGET_URL, timeout_ms=_REQUEST_TIMEOUT_MS)

    led_counter = 0
    deadline = _ticks_ms() + _REQUEST_TIMEOUT_MS + 5_000
    while not request.done:
        if _ticks_ms() > deadline:
            raise AssertionError(
                f"request did not complete within deadline; "
                f"state={request.state if hasattr(request, 'state') else 'unknown'}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        if client.check(_ticks_ms()):
            client.handle(_ticks_ms())
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
    # No LED-counter assertion here: TLS handshake in the
    # underlying socket factory is synchronous, so a fast small
    # response can complete in 1–2 outer ticks.  The cooperative
    # invariant for plain HTTP is verified by test_real_get.py;
    # this test's job is the HTTPS round-trip itself.


def test_real_https_get_skip_when_no_creds_configured() -> None:
    """Document the no-creds path; always passes."""
    if _HAS_CREDS:
        return
