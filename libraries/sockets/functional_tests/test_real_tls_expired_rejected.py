"""Real-network test that ``tls_client_socket(context=None)`` rejects
expired certificates on every supported runtime.

Companion to ``test_real_tls.py`` (which covers the happy path against
a known-good public HTTPS endpoint).  This test is the regression
harness for the Shape Y default-secure rollout:

* CircuitPython — firmware mbedTLS CA store rejects with
  ``MBEDTLS_ERR_X509_FATAL_ERROR``.
* MicroPython — library-shipped CA bundle (``chumicro_sockets._ca_bundle``)
  is loaded into a default :class:`ssl.SSLContext` with
  ``verify_mode = CERT_REQUIRED``; mbedTLS rejects the expired chain.

Before Shape Y landed, MP would silently accept the expired cert
(2026-05-11 audit finding).  This test pins that regression in
place — passing it on every board in the four-board canonical matrix
(Lolin S2 + Pi Pico W × CP/MP) is the acceptance criterion for the
fix.

Endpoint: ``expired.badssl.com:443`` — purpose-built test endpoint
serving an expired certificate signed by a real public CA.

Skipped at collection time when no wifi credentials are configured.
"""

import time

from chumicro_config import config
from chumicro_sockets import tls_client_socket
from chumicro_timing import ticks_ms as _ticks_ms
from chumicro_wifi import WifiConfig, WifiService, WifiState

_EXPIRED_HOST = "expired.badssl.com"
_EXPIRED_PORT = 443
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
                f"wifi did not link within "
                f"{_WIFI_CONNECT_TIMEOUT_MS} ms; state={wifi.state}",
            )
        if wifi.check(_ticks_ms()):
            wifi.handle(_ticks_ms())
        _sleep_ms(50)
    return wifi


def test_default_context_rejects_expired_cert() -> None:
    """``tls_client_socket(context=None)`` against ``expired.badssl.com``
    raises rather than completing the handshake.

    Acceptance criterion for Shape Y on the four-board canonical
    matrix.  Catches a future regression where the MP adapter slips
    back to insecure-by-default, or where the shipped CA bundle ends
    up with ``verify_mode != CERT_REQUIRED``.
    """
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        raise AssertionError(
            "wifi runtime config missing — conftest should have "
            "skipped this test at collection time.",
        )

    wifi = _bring_wifi_up(wifi_cfg)
    print(f"WIFI_OK ip={wifi.ip}")

    handshake_error: BaseException | None = None
    socket = None
    try:
        socket = tls_client_socket(
            _EXPIRED_HOST, _EXPIRED_PORT, radio=wifi.adapter.radio,
        )
    except OSError as error:
        handshake_error = error
        print(f"TLS_REJECTED expected={type(error).__name__} {error!r}")
    except Exception as error:  # pragma: no cover — mbedTLS/portable surface drift
        handshake_error = error
        print(f"TLS_REJECTED expected={type(error).__name__} {error!r}")
    else:
        # The handshake should not have succeeded.  Close before
        # asserting so an unexpected open socket doesn't leak.
        if socket is not None:
            try:
                socket.close()
            except Exception:  # pragma: no cover — best-effort close
                pass

    assert handshake_error is not None, (
        f"TLS handshake to {_EXPIRED_HOST}:{_EXPIRED_PORT} unexpectedly "
        f"succeeded — verification is disabled or the trust set "
        f"includes the expired cert's signer.  Shape Y regression."
    )
