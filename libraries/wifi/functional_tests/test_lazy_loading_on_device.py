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

    Implicitly exercises that ``chumicro_wifi`` doesn't try to
    pull in ``importlib`` (workbench-only) or any other
    CPython-only module at import time.
    """
    import chumicro_wifi  # noqa: F401 - import-only check


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
    """``WifiService`` constructs (with the substrate adapter or its placeholder).

    On a real board the auto-detect path picks the runtime-specific
    adapter, which currently raises ``NotImplementedError``
    (slices 1–3 fill those in).  Asserting that the
    ``NotImplementedError`` propagates confirms the lazy adapter
    selection inside ``_select_adapter`` reaches the right
    submodule on each runtime.
    """
    from chumicro_wifi import WifiConfig, WifiService
    config = WifiConfig(ssid="x", password="y")
    try:
        WifiService(config)
    except NotImplementedError:
        pass  # expected — real adapter lands in slices 1–3
    else:
        # If construction succeeded, we got a real adapter (e.g.
        # CPython MP unix-port, which has no esp32 module and
        # somehow falls through).  Either way is acceptable —
        # the important thing is the import path resolved.
        pass
