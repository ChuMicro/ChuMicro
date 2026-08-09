"""Host-side fixture: register the merged runtime-config dict for staging.

Each library owns its own copy of this fixture because the per-library
``functional_tests/config.toml`` overrides land relative to that
library's directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_pytest_device.runtime_config import set_runtime_config
from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_SECRETS_TOML = _REPO_ROOT / "secrets.toml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only


def _merged_runtime_config() -> dict | None:
    """Return the deep-merged + flattened runtime-config dict, or ``None``."""
    if not _SECRETS_TOML.is_file():
        return None
    # Any exception from ``compose_runtime_config`` propagates — a
    # malformed ``secrets.toml`` is a real bug to surface, not the
    # same shape as a fresh-clone "user hasn't filled it in yet."
    # The missing-file path above is the only silent-skip case.
    merged = compose_runtime_config(
        secrets_toml=_SECRETS_TOML,
        project_config=_LIBRARY_CONFIG,
    )
    ssid = merged.get("wifi.ssid")
    password = merged.get("wifi.password")
    if not isinstance(ssid, str) or not isinstance(password, str):
        return None
    if ssid == "replace-with-your-ap-ssid":
        return None
    return merged


def pytest_configure(config: pytest.Config) -> None:
    """Register the runtime-config payload pytest-device will stage."""
    set_runtime_config(
        config,
        _merged_runtime_config(),
        required_keys=("wifi.ssid", "wifi.password"),
    )
