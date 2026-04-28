"""Host-side fixture: materialise ``_test_creds.py`` from ``chumicro-dev-config.toml``.

Mirrors ``libraries/requests/functional_tests/conftest.py`` — see that
file for the shared rationale.  chumicro-ntp's tests only need the
``[wifi]`` section (the NTP server is a public hostname, no host-side
counterparty fixture).
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_DEV_CONFIG = _REPO_ROOT / "chumicro-dev-config.toml"
_SHIM_PATH = _HERE / "_test_creds.py"


def _read_wifi_section() -> tuple[str, str] | None:
    if not _DEV_CONFIG.exists():
        return None
    try:
        data = tomllib.loads(_DEV_CONFIG.read_text())
        wifi = data["wifi"]
        return wifi["ssid"], wifi["password"]
    except (KeyError, ValueError):
        return None


def pytest_configure(config) -> None:  # noqa: ARG001 - pytest hook signature
    """Write/refresh ``_test_creds.py`` from the dev config."""
    creds = _read_wifi_section()
    if creds is None:
        if _SHIM_PATH.exists():
            _SHIM_PATH.unlink()
        return
    ssid, password = creds
    _SHIM_PATH.write_text(
        '"""Auto-generated test creds shim — do not check in."""\n'
        f"SSID = {ssid!r}\n"
        f"PASSWORD = {password!r}\n",
    )
