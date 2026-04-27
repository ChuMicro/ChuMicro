"""Host-side fixture: materialise ``_test_creds.py`` from ``chumicro-dev-config.toml``.

See ``libraries/requests/functional_tests/conftest.py`` for the
shared rationale.  Pre-2026-04-27 the wifi acceptance test
documented its ``_test_creds`` import as "the host-side runner
generates it" — that runner now lives here as a per-functional-
tests pytest hook.
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
