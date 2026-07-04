"""TLS trust-matrix smoke test for chumicro-sockets.

Category 2 — public endpoint, `expired.badssl.com:443` +
`valid-isrgrootx1.letsencrypt.org:443` interop.

Three legs in one file, run on Lolin S2 + Pi Pico W × CP / MP:

1. **no-verify** — `ssl_context_no_verify()` against an expired-cert
   host succeeds: the explicit opt-out really disables validation on
   every runtime.
2. **default rejects** — `context=None` against the same expired host
   raises: default validation rejects a bad chain (CP firmware
   bundle / MP shipped bundle / CPython store).
3. **default accepts** — `context=None` against the Let's Encrypt
   ISRG-Root-X1 endpoint handshakes: the trust set actually validates
   a real cert.

Why public endpoints? Trust-set coverage is the point — a controlled
fixture would chain through our own CA bundle and prove nothing about
whether the runtime's shipped trust set anchors a real public cert.

All three legs seed the device RTC from the host clock first
(`sockets.now_utc_tuple`, published by conftest). Legs 1-2 don't
strictly need it (no-check / reject-regardless-of-skew), but leg 3
does — default validation rejects a valid cert as "validity starts in
the future" when the board boots at epoch. Real deployments NTP-sync
instead.

Skipped at collection time when wifi credentials are missing.
"""

import time

from chumicro_sockets import connector, ssl_context_no_verify
from chumicro_test_harness.network import runtime_config, wifi_up
from chumicro_timing import ticks_add, ticks_diff, ticks_ms

_CONNECT_DEADLINE_MS = 30_000

_EXPIRED_HOST = "expired.badssl.com"
_EXPIRED_PORT = 443
#: Let's Encrypt's purpose-built endpoint whose chain terminates at
#: ISRG Root X1 — the anchor in chumicro_sockets' bundled trust set
#: and present in CircuitPython's firmware bundle.
_VALID_LE_HOST = "valid-isrgrootx1.letsencrypt.org"
_VALID_LE_PORT = 443


def _sleep_ms(duration_ms: int) -> None:
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _connect_tls(
    host: str,
    port: int,
    *,
    context: object | None = None,
    radio: object | None = None,
) -> object:
    """Drive ``connector(tls=True)`` to terminal inline; return the connected socket.

    The tick-and-sleep loop is the one-shot connect form on-device:
    the same state machine the runner would drive, without a runner.
    Raises the connector's ``last_error`` on failure and
    ``AssertionError`` when the dial exceeds the connect deadline.
    """
    dial = connector(host, port, tls=True, context=context, radio=radio)
    deadline = ticks_add(ticks_ms(), _CONNECT_DEADLINE_MS)
    while dial.state not in ("ready", "failed"):
        if ticks_diff(deadline, ticks_ms()) <= 0:
            dial.cancel()
            raise AssertionError(
                f"TLS connect to {host}:{port} exceeded "
                f"{_CONNECT_DEADLINE_MS} ms (state {dial.state!r})",
            )
        dial.tick(ticks_ms())
        _sleep_ms(10)
    if dial.state == "failed":
        raise dial.last_error
    return dial.socket


def _seed_rtc(now_utc_tuple: tuple) -> None:
    """Set the device RTC from `now_utc_tuple` so cert validity-time checks pass.

    Boot RTC on most ports lands at epoch / 2021; without seeding,
    mbedTLS rejects every valid cert with "validity starts in the
    future". Real deployments NTP-sync; conftest bakes the host clock
    from session start so the test stays off the network for time.
    MP exposes `machine.RTC`; CP exposes `rtc.RTC`.
    """
    try:
        import machine  # noqa: PLC0415 — MP-only

        machine.RTC().datetime((
            now_utc_tuple[0], now_utc_tuple[1], now_utc_tuple[2],
            0,
            now_utc_tuple[3], now_utc_tuple[4], now_utc_tuple[5], 0,
        ))
        return
    except (ImportError, AttributeError):
        pass
    try:
        from time import struct_time  # noqa: PLC0415 — CP path

        import rtc  # noqa: PLC0415 — CP-only

        rtc.RTC().datetime = struct_time((
            now_utc_tuple[0], now_utc_tuple[1], now_utc_tuple[2],
            now_utc_tuple[3], now_utc_tuple[4], now_utc_tuple[5],
            0, 0, -1,
        ))
    except (ImportError, AttributeError):
        pass


def _prepare() -> object:
    """Read runtime config, seed the RTC, bring wifi up, return the radio."""
    config = runtime_config()
    ssid = config.get("wifi.ssid", "")
    password = config.get("wifi.password", "")
    if not ssid:
        raise AssertionError(
            "wifi runtime config missing — conftest should have "
            "skipped this test at collection time.",
        )
    _seed_rtc(config["sockets.now_utc_tuple"])
    radio, ip = wifi_up(ssid, password)
    print(f"WIFI_OK ip={ip}")
    return radio


def test_no_verify_accepts_expired_cert() -> None:
    """Leg 1: `ssl_context_no_verify()` opts out of validation; expired-cert handshake completes."""
    radio = _prepare()
    context = ssl_context_no_verify()
    socket = _connect_tls(
        _EXPIRED_HOST, _EXPIRED_PORT, context=context, radio=radio,
    )
    print(f"NO_VERIFY_OK host={_EXPIRED_HOST}")
    assert socket is not None, (
        "ssl_context_no_verify() should let the handshake to an "
        "expired-cert host complete and return a socket"
    )
    socket.close()


def test_default_context_rejects_expired_cert() -> None:
    """Leg 2: `context=None` validates and rejects the expired chain on every runtime."""
    radio = _prepare()
    rejected: BaseException | None = None
    socket = None
    try:
        socket = _connect_tls(_EXPIRED_HOST, _EXPIRED_PORT, radio=radio)
    except Exception as error:  # noqa: BLE001 — mbedTLS surface varies
        rejected = error
        print(f"REJECTED expected={type(error).__name__} {error!r}")
    else:
        if socket is not None:
            try:
                socket.close()
            except Exception:  # pragma: no cover — best-effort
                pass
    assert rejected is not None, (
        f"default-context handshake to {_EXPIRED_HOST} unexpectedly "
        f"succeeded — validation disabled or trust set includes the "
        f"expired signer."
    )


def test_default_context_accepts_real_letsencrypt_host() -> None:
    """Leg 3: `context=None` validates the live ISRG-Root-X1 chain and completes the handshake.

    Proves the shipped / firmware trust set anchors a real public cert
    (the RTC is seeded by `_prepare` so cert validity-time checks
    pass).
    """
    radio = _prepare()
    socket = _connect_tls(_VALID_LE_HOST, _VALID_LE_PORT, radio=radio)
    print(f"VALID_OK host={_VALID_LE_HOST}")
    assert socket is not None, (
        "default context should validate the ISRG-Root-X1 chain and "
        "return a connected socket"
    )
    socket.close()
