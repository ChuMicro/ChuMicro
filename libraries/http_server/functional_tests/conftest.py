"""Host-side fixture: materialise ``_test_creds.py`` from the unified config sources.

See ``libraries/requests/functional_tests/conftest.py`` for the
shared rationale.  Each library owns its own copy because the
generated shim must sit alongside the tests that import it.

Phase 4 of the unification workstream
(``plans/workstreams/scripts-workbench-config-unification.md``)
retired the legacy ``chumicro-dev-config.toml`` source — every
networking library's conftest reads from the same
``workspace.yml`` + ``workspace.local.yml`` pair the workspace-template's
user projects use.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_WORKSPACE_YAML = _REPO_ROOT / "workspace.yml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only
_WORKSPACE_LOCAL_YAML = _REPO_ROOT / "workspace.local.yml"
_SHIM_PATH = _HERE / "_test_creds.py"


def _read_wifi_section() -> tuple[str, str] | None:
    """Return ``(ssid, password)`` from the unified config, or ``None``.

    Silent-skip on every "creds not configured" path: missing
    workspace.yml, missing wifi section, missing keys, secrets
    resolution failure, placeholder SSID still in place.
    """
    if not _WORKSPACE_YAML.is_file():
        return None
    try:
        merged = compose_runtime_config(
            workspace_yaml=_WORKSPACE_YAML,
            project_config=_LIBRARY_CONFIG,
            workspace_local_yaml=_WORKSPACE_LOCAL_YAML,
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
    """Write/refresh ``_test_creds.py`` from the unified config sources."""
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
