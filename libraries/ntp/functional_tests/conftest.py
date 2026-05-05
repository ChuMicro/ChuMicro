"""Host-side fixture: register the merged runtime-config dict for staging.

Mirrors ``libraries/wifi/functional_tests/conftest.py`` — see that
file for the shared rationale.  chumicro-ntp's tests only need the
``[wifi]`` section (the NTP server is a public hostname, no host-side
counterparty fixture).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_pytest_device.runtime_config import set_runtime_config
from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_WORKSPACE_YAML = _REPO_ROOT / "workspace.yml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only


def _merged_runtime_config() -> dict | None:
    """Return the deep-merged runtime-config dict, or ``None`` to silent-skip."""
    if not _WORKSPACE_YAML.is_file():
        return None
    try:
        merged = compose_runtime_config(
            workspace_yaml=_WORKSPACE_YAML,
            project_config=_LIBRARY_CONFIG,
        )
    except Exception:  # noqa: BLE001 — silent skip on any config error
        return None
    wifi = merged.get("wifi")
    if not isinstance(wifi, dict):
        return None
    ssid = wifi.get("ssid")
    password = wifi.get("password")
    if not isinstance(ssid, str) or not isinstance(password, str):
        return None
    if ssid == "replace-with-your-ap-ssid":
        return None
    return merged


def pytest_configure(config: pytest.Config) -> None:
    """Register the runtime-config payload pytest-device will stage."""
    set_runtime_config(config, _merged_runtime_config())
