"""Host-side fixture: materialise ``_test_creds.py`` from the unified config sources.

Reads the merged runtime-config dict from the gitignored
``workspace.yml`` (workspace-wide defaults + credentials in one
place per Decision 0057) deep-merged with this library's optional
``functional_tests/config.toml``, then renders the ``[wifi]``
section into the gitignored ``_test_creds.py`` shim that the
on-device test imports.

Per Decision 0057, credentials live in the gitignored
``workspace.yml`` directly — no ``!secret`` marker, no resolver,
the file never reaches git.

The on-device side is unchanged — tests still ``from _test_creds
import SSID, PASSWORD``.  A follow-up will extend
``chumicro-pytest-device`` to stage a binary
``runtime_config.msgpack`` so on-device tests can call
``chumicro_config.load_runtime_config()`` directly (full
dogfooding of the user-facing path); gated on a transport-API
change.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_workspace import compose_runtime_config

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_WORKSPACE_YAML = _REPO_ROOT / "workspace.yml"
_LIBRARY_CONFIG = _HERE / "config.toml"  # optional; absent → workspace defaults only
_SHIM_PATH = _HERE / "_test_creds.py"


def _read_wifi_section() -> tuple[str, str] | None:
    """Return ``(ssid, password)`` from the unified config, or ``None``.

    Returns ``None`` when:

    * ``workspace.yml`` is missing (fresh-clone before ``setup``).
    * The merged config has no ``[wifi]`` section, or it lacks
      ``ssid`` / ``password`` (typically because the gitignored
      ``workspace.yml`` hasn't been filled in yet).
    * The merged config carries the placeholder SSID — same
      silent-skip path so a fresh-clone contributor isn't
      surprised by a "real network error" against a nonsense SSID.
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
    # The literal placeholder shipped in the unified workspace.yml
    # starter — treat it as "no creds yet".
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
