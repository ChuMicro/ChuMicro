"""Host-side fixture: materialise ``_test_creds.py`` from ``chumicro-dev-config.toml``.

Functional tests in this directory want real wifi creds without
checking them in.  This conftest writes a gitignored
``_test_creds.py`` shim alongside the test files when the repo
root has a ``chumicro-dev-config.toml`` with a ``[wifi]`` section,
and removes the shim when the source goes away.

Source path: ``<repo-root>/chumicro-dev-config.toml`` — generated
by ``python scripts/run.py setup`` from
``scripts/templates/chumicro-dev-config.toml.template``.

Tests that import ``_test_creds`` skip silently when the shim
isn't present, so committing this conftest is safe even on a
clone without local credentials.

Until ``pytest_device.py`` learns to deploy this sibling to the
device automatically (see ``plans/next-up.md``), tests skip
silently on hardware even when creds are configured.  Host-side
``pytest`` runs that don't involve a device pick up the shim
directly from the local filesystem.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parents[2]
_DEV_CONFIG = _REPO_ROOT / "chumicro-dev-config.toml"
# Backward compat: the pre-2026-04-27 location.  Read it as a fallback
# so migrating contributors don't need to copy creds in two places at once.
_LEGACY_CREDS_TOML = _REPO_ROOT / ".scratch" / "wifi-creds.toml"
_SHIM_PATH = _HERE / "_test_creds.py"


def _read_wifi_section() -> tuple[str, str] | None:
    """Return ``(ssid, password)`` from the dev config, or ``None``."""
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
