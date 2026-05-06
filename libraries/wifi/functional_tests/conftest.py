"""Host-side fixture: register the merged runtime-config dict for staging.

Reads the gitignored ``secrets.toml`` (workspace-wide credentials +
device defaults) deep-merged with this library's optional
``functional_tests/config.toml``, then hands the flattened result to
``chumicro_pytest_device.set_runtime_config`` so the plugin
msgpack-encodes it once and stages it at
``/runtime_config.msgpack`` on the device.  On-device tests read
the same payload via ``chumicro_config.load_runtime_config()`` —
the same API user code uses.

When the merged config has no usable wifi credentials (fresh-clone
state, placeholder SSID still in the starter), nothing is
registered — staging is suppressed and the on-device test's
import block falls through to the silent-skip path
(``OSError`` from ``open()``).
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
    """Return the deep-merged + flattened runtime-config dict, or ``None``.

    Returns ``None`` when:

    * ``workspace.yml`` is missing (fresh-clone before ``setup``).
    * The merged flat config lacks ``wifi.ssid`` / ``wifi.password``
      (typically because the gitignored ``workspace.yml`` hasn't been
      filled in yet).
    * The merged config carries the placeholder SSID — same silent-
      skip path so a fresh-clone contributor isn't surprised by a
      "real network error" against a nonsense SSID.
    """
    if not _SECRETS_TOML.is_file():
        return None
    try:
        merged = compose_runtime_config(
            secrets_toml=_SECRETS_TOML,
            project_config=_LIBRARY_CONFIG,
        )
    except Exception:  # noqa: BLE001 — silent skip on any config error
        return None
    ssid = merged.get("wifi.ssid")
    password = merged.get("wifi.password")
    if not isinstance(ssid, str) or not isinstance(password, str):
        return None
    if ssid == "replace-with-your-ap-ssid":
        return None
    return merged


def pytest_configure(config: pytest.Config) -> None:
    """Register the runtime-config payload pytest-device will stage."""
    set_runtime_config(config, _merged_runtime_config())
