"""Host-side fixture: register the merged runtime-config dict for staging.

Reads the merged runtime-config dict from
``workspace.yml`` + this library's optional
``functional_tests/config.toml``, then hands it to
``chumicro_pytest_device.runtime_config.set_runtime_config`` so the
plugin msgpack-encodes it once and stages it at
``/runtime_config.msgpack`` on the device.  On-device tests read it
back via ``chumicro_config.load_runtime_config()``.

Bakes the host's current UTC into ``requests.now_utc_tuple`` (a
6-tuple) so the HTTPS test (``test_real_get_tls.py``) can seed the
device RTC before TLS validation — boot RTC lands at 2021-01-01 on
most ports, which makes mbedTLS reject any cert with NotBefore after
that.  Real deployments NTP-sync; this is the bench-test equivalent.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from chumicro_pytest_device.runtime_config import set_runtime_config
from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_WORKSPACE_YAML = _REPO_ROOT / "workspace.yml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only


def _merged_runtime_config() -> dict | None:
    """Return the deep-merged runtime-config dict, or ``None`` to silent-skip.

    Adds ``requests.now_utc_tuple`` — the bench-test RTC seed used by
    the HTTPS test — into the merged dict so the on-device test reads
    it via ``load_runtime_config()["requests"]["now_utc_tuple"]``.
    """
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
    now = datetime.now(UTC)
    now_tuple = (now.year, now.month, now.day, now.hour, now.minute, now.second)
    merged.setdefault("requests", {})["now_utc_tuple"] = now_tuple
    return merged


def pytest_configure(config: pytest.Config) -> None:
    """Register the runtime-config payload pytest-device will stage."""
    set_runtime_config(config, _merged_runtime_config())
