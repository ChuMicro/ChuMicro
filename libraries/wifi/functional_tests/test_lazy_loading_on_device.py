"""On-device validation of `chumicro-wifi`'s import shape.

Confirms the package + key public attributes resolve cleanly on
real CircuitPython + MicroPython boards (not just the unix-ports).
Also documents — by demonstrating the eager-import shape — the
finding that PEP 562 module-level ``__getattr__`` is silently
bypassed by CircuitPython's RAM-mode class-as-module wrapper, so
package-level lazy attrs can't actually fire on CP RAM deploys.
The lazy benefit lives in :func:`_select_adapter` (named
``from X import Y`` inside a function — works everywhere).

This is part of the Phase 3a Slice 0 hardware verification.
"""


def test_chumicro_wifi_imports_cleanly_on_device() -> None:
    """The package + transitive deps load on real flash.

    Exercises that ``chumicro_wifi`` doesn't try to pull in
    ``importlib`` (workbench-only) or any other CPython-only module
    at import time.  The post-import ``getattr`` confirms the
    package object actually exposed its eager attribute set, so a
    silent import-as-empty-module regression would fail the test
    (rather than passing on the import-not-raising alone).
    """
    import chumicro_wifi
    assert getattr(chumicro_wifi, "WifiConfig", None) is not None


def test_wifi_config_resolves_on_device() -> None:
    """``WifiConfig`` is reachable through the package's eager exports."""
    import chumicro_wifi
    instance = chumicro_wifi.WifiConfig(ssid="x", password="y")
    assert instance.ssid == "x"


def test_wifi_state_resolves_on_device() -> None:
    """``WifiState`` constants are reachable through the package's eager exports."""
    import chumicro_wifi
    assert chumicro_wifi.WifiState.CONNECTED == "connected"


def test_wifi_service_resolves_on_device() -> None:
    """``WifiService`` constructs against the substrate-selected adapter.

    The CP and MP adapters are both implemented now, so on every
    real-board target the lazy ``_select_adapter`` lookup finds a
    concrete adapter and ``WifiService`` constructs cleanly.  The
    post-construction assertion confirms the lazy import path
    resolved to a real object, not a placeholder or shim.
    """
    from chumicro_wifi import WifiConfig, WifiService
    config = WifiConfig(ssid="x", password="y")
    service = WifiService(config)
    assert service is not None
    assert service.adapter_name in ("cp", "mp_esp32", "mp_rp2")
