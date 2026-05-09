"""wifi acceptance — connect to a real AP across all four boards.

Reads credentials from ``/runtime_config.msgpack`` on the device via
``WifiConfig.try_from_config(config)`` — same surface user app code
uses.  The host-side ``functional_tests/conftest.py`` builds the
merged config dict (workspace defaults + per-library overrides) and
hands it to ``chumicro_pytest_device.set_runtime_config()``; the
plugin encodes + stages the file alongside the test sources.

When the wifi section isn't deployed (fresh-clone without
credentials, RAM-mode skip) ``try_from_config`` returns ``None`` and
every test early-returns cleanly so the suite stays committable.

The test source itself never contains credentials — only the
loader pattern + assertions about the resulting state machine.

Per-board scenarios:

1. **Connect to the configured AP, observe state transitions** —
   `WifiState.DISCONNECTED → CONNECTING → CONNECTED`, IP populated,
   adapter reports linked.
2. **Reconnect after deliberate disconnect** — call
   `service.handle()` until linked, then drop the substrate's
   association via `adapter.disconnect()`, drive ticks, watch
   `CONNECTED → RECONNECTING → CONNECTED` cycle.
3. **state-change observability** — register an
   `on_state_change` listener, count transitions across the
   connect / drop / reconnect sequence.

Output deliberately prints SSID + state names + IP but **never**
the password.  Commit messages never reference the SSID or password
values either.
"""

import time

from chumicro_config import config
from chumicro_wifi import WifiConfig, WifiService, WifiState


def _sleep_ms(duration_ms):
    """Sleep duration with the runtime's best API."""
    runtime_sleep_ms = getattr(time, "sleep_ms", None)
    if callable(runtime_sleep_ms):
        runtime_sleep_ms(duration_ms)
        return
    time.sleep(duration_ms / 1000)


def _drive_until(service, predicate, *, deadline_ms):
    """Tick the service until *predicate(service)* is true or *deadline_ms* elapses.

    Returns ``True`` on success, ``False`` on deadline timeout.
    """
    runtime_ticks_ms = service._ticks_ms  # noqa: SLF001 - reuse the wired clock
    start = runtime_ticks_ms()
    while True:
        now = runtime_ticks_ms()
        if predicate(service):
            return True
        elapsed = service._ticks_diff(now, start)  # noqa: SLF001
        if elapsed >= deadline_ms:
            return False
        if service.check(now):
            service.handle(now)
        _sleep_ms(50)


def _make_service(wifi_config):
    """Tighten timeouts on the loaded ``WifiConfig`` and wrap in a ``WifiService``.

    Uses the runtime's auto-detected adapter (CP / MP-ESP32 /
    MP-RP2 / fake on host).  Tighter timeouts than production keep
    the test suite snappy.
    """
    wifi_config.connect_timeout_ms = 10_000
    wifi_config.reconnect_backoff_start_ms = 500
    wifi_config.reconnect_backoff_max_ms = 5_000
    return WifiService(wifi_config)


def test_connects_to_real_ap() -> None:
    """End-to-end: associate with the configured AP, observe linked state."""
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time.  Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )
    service = _make_service(wifi_cfg)
    assert service.state == WifiState.DISCONNECTED

    # Drive the service until linked or 15 s elapses.
    print(f"Connecting to SSID {wifi_cfg.ssid!r}...")
    ok = _drive_until(
        service,
        lambda svc: svc.state == WifiState.CONNECTED,
        deadline_ms=15_000,
    )
    print(f"State after connect attempts: {service.state}, IP: {service.ip}")
    assert ok, f"Failed to reach CONNECTED state; current={service.state}"
    assert service.connected is True
    assert service.ip is not None
    assert service.adapter_name in ("cp", "mp_esp32", "mp_rp2")


def test_reconnect_after_deliberate_disconnect() -> None:
    """Drop the link via ``adapter.disconnect``, watch the reconnect cycle."""
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time.  Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )
    service = _make_service(wifi_cfg)
    ok = _drive_until(
        service,
        lambda svc: svc.state == WifiState.CONNECTED,
        deadline_ms=15_000,
    )
    assert ok, "Initial connect failed; can't test reconnect"

    # Drop the substrate association directly so the service detects
    # link-down on the next tick.
    service._adapter.disconnect()  # noqa: SLF001 - test introspection
    print("Substrate link dropped; driving service through reconnect...")

    # First detect the drop.
    drop_detected = _drive_until(
        service,
        lambda svc: svc.state == WifiState.RECONNECTING,
        deadline_ms=2_000,
    )
    print(f"After drop: state={service.state}")
    assert drop_detected, "Service did not detect the link drop"

    # Then re-establish.
    reconnected = _drive_until(
        service,
        lambda svc: svc.state == WifiState.CONNECTED,
        deadline_ms=15_000,
    )
    print(f"After reconnect: state={service.state}, IP: {service.ip}")
    assert reconnected, f"Reconnect failed; current={service.state}"


def test_state_callback_observes_transitions() -> None:
    """Registered ``on_state_change`` listener sees the full transition sequence."""
    wifi_cfg = WifiConfig.try_from_config(config)
    if wifi_cfg is None:
        raise AssertionError(
            "wifi runtime config missing — the conftest's "
            "`set_runtime_config(..., required_keys=...)` should have "
            "skipped this test at collection time.  Reaching this body "
            "means the conftest's required_keys list is incomplete.",
        )
    transitions = []
    service = _make_service(wifi_cfg)
    service.on_state_change(lambda old, new: transitions.append((old, new)))

    ok = _drive_until(
        service,
        lambda svc: svc.state == WifiState.CONNECTED,
        deadline_ms=15_000,
    )
    assert ok, "Did not reach CONNECTED"

    # The CONNECTED transition is the canonical signal apps register
    # for; assert it's in the captured sequence.
    print(f"Captured {len(transitions)} transitions: {transitions}")
    assert (WifiState.CONNECTING, WifiState.CONNECTED) in transitions
