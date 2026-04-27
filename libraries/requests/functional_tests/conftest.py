"""Host-side fixture: materialise ``_test_creds.py`` from ``.scratch/wifi-creds.toml``.

Functional tests in this directory want real wifi creds without
checking them in.  This conftest writes a gitignored
``_test_creds.py`` shim alongside the test files when the host has
``.scratch/wifi-creds.toml`` with a ``[wifi]`` section, and removes
it when the source goes away.

The shim is the same shape the wifi acceptance test (``libraries/
wifi/functional_tests/test_acceptance.py``) expects, so the same
``try: from _test_creds import SSID, PASSWORD`` pattern lights up
across libraries.

Until ``pytest_device.py`` learns to deploy this sibling to the
device automatically, tests that import ``_test_creds`` skip
silently on hardware — which matches the documented "no creds, no
acceptance" behaviour.  Host-side ``pytest`` runs that don't
involve a device pick up the shim from the local filesystem
directly.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_CREDS_TOML = _REPO_ROOT / ".scratch" / "wifi-creds.toml"
_SHIM_PATH = _HERE / "_test_creds.py"


def pytest_configure(config) -> None:  # noqa: ARG001 - pytest hook signature
    """Write/refresh ``_test_creds.py`` from ``.scratch/wifi-creds.toml``."""
    if not _CREDS_TOML.exists():
        if _SHIM_PATH.exists():
            _SHIM_PATH.unlink()
        return

    try:
        wifi = tomllib.loads(_CREDS_TOML.read_text())["wifi"]
        ssid = wifi["ssid"]
        password = wifi["password"]
    except (KeyError, ValueError):
        # Malformed creds file — leave any prior shim in place; tests
        # that depend on it will surface the error themselves.
        return

    _SHIM_PATH.write_text(
        '"""Auto-generated test creds shim — do not check in."""\n'
        f"SSID = {ssid!r}\n"
        f"PASSWORD = {password!r}\n",
    )
