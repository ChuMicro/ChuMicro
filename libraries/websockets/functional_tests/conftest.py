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

Mirrors :mod:`chumicro_requests` / :mod:`chumicro_http_server`'s
functional-test conftest exactly — when the dev-config glue
factors out (next time we add a fourth library that needs creds)
this becomes the third instance of copy-don't-couple worth
extracting.
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
