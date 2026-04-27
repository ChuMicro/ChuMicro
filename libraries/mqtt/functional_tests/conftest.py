"""Host-side fixture: materialise ``_test_creds.py`` from ``.scratch/wifi-creds.toml``.

See ``libraries/requests/functional_tests/conftest.py`` for the
shared rationale.
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
        return

    _SHIM_PATH.write_text(
        '"""Auto-generated test creds shim — do not check in."""\n'
        f"SSID = {ssid!r}\n"
        f"PASSWORD = {password!r}\n",
    )
