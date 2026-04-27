"""Host-side fixture: materialise ``_test_creds.py`` from ``chumicro-dev-config.toml``.

See ``libraries/requests/functional_tests/conftest.py`` for the
shared rationale.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_DEV_CONFIG = _REPO_ROOT / "chumicro-dev-config.toml"
_LEGACY_CREDS_TOML = _REPO_ROOT / ".scratch" / "wifi-creds.toml"
_SHIM_PATH = _HERE / "_test_creds.py"


def _read_wifi_section() -> tuple[str, str] | None:
    for path in (_DEV_CONFIG, _LEGACY_CREDS_TOML):
        if not path.exists():
            continue
        try:
            data = tomllib.loads(path.read_text())
            wifi = data["wifi"]
            return wifi["ssid"], wifi["password"]
        except (KeyError, ValueError):
            continue
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
