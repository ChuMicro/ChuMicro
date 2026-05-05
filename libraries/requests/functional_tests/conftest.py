"""Host-side fixture: materialise ``_test_creds.py`` from the unified config sources.

Reads the merged runtime-config dict from
``workspace.yml`` + this library's optional
``functional_tests/config.toml`` , then renders the
``[wifi]`` section into the gitignored ``_test_creds.py`` shim that
the on-device test imports.

Phase 4 of the unification workstream
(``plans/workstreams/scripts-workbench-config-unification.md``)
retired the legacy ``chumicro-dev-config.toml`` source — every
networking library's conftest reads from the same
gitignored ``workspace.yml`` the workspace-template's
user projects use.

Tests that import ``_test_creds`` skip silently when the shim
isn't present, so committing this conftest is safe even on a
clone without local credentials.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_WORKSPACE_YAML = _REPO_ROOT / "workspace.yml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only
_SHIM_PATH = _HERE / "_test_creds.py"


def _read_wifi_section() -> tuple[str, str] | None:
    """Return ``(ssid, password)`` from the unified config, or ``None``.

    Silent-skip on every "creds not configured" path: missing
    workspace.yml, missing wifi section, missing keys,
    parse failure, placeholder SSID still in place.
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
    return ssid, password


def pytest_configure(config) -> None:  # noqa: ARG001 - pytest hook signature
    """Write/refresh ``_test_creds.py`` from the dev config.

    Also bakes the host's current UTC into ``NOW_UTC_TUPLE`` so the
    HTTPS test (``test_real_get_tls.py``) can seed the device RTC
    before TLS validation — boot RTC lands at 2021-01-01 on most
    ports, which makes mbedTLS reject any cert with NotBefore after
    that.  Real deployments NTP-sync; this is the bench-test
    equivalent.
    """
    creds = _read_wifi_section()
    if creds is None:
        if _SHIM_PATH.exists():
            _SHIM_PATH.unlink()
        return
    ssid, password = creds
    now = datetime.now(UTC)
    now_tuple = (now.year, now.month, now.day, now.hour, now.minute, now.second)
    _SHIM_PATH.write_text(
        '"""Auto-generated test creds shim — do not check in."""\n'
        f"SSID = {ssid!r}\n"
        f"PASSWORD = {password!r}\n"
        f"NOW_UTC_TUPLE = {now_tuple!r}\n",
    )
