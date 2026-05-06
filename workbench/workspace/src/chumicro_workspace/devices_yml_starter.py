"""Canonical ``devices.yml`` starter content.

Owned by ``chumicro-workspace`` so the same empty-registry +
three-zone-headed shape ships from one source to every consumer
that needs to materialise an empty ``devices.yml`` — most commonly
``chumicro-workspace setup`` on first run.

The actual file content travels with the wheel inside
``_payloads/devices.yml.template`` so reads work in both editable
installs (live source tree) and pip-installed wheels (unpacked into
site-packages).

The only public surface is :func:`read_devices_yml_starter` —
returning the file's content as a string.  Callers decide where
to write it.
"""

from __future__ import annotations

from pathlib import Path

#: Path to the canonical ``devices.yml`` starter inside the
#: ``chumicro_workspace`` package.  Resolved at import time so
#: filesystem reads stay simple — the wheel ships the same path.
_DEVICES_YML_STARTER_PATH = (
    Path(__file__).resolve().parent
    / "_payloads"
    / "devices.yml.template"
)


def read_devices_yml_starter() -> str:
    """Return the canonical empty-registry ``devices.yml`` content.

    The content is the three-zone-headed shape with ``defaults.{micropython,
    circuitpython}: null`` (filled by ``add-device``), ``deploy_mode:
    flash``, ``ide_runtime: micropython``, and ``devices: []``.  Same
    bytes used by every consumer — single source of truth.
    """
    return _DEVICES_YML_STARTER_PATH.read_text(encoding="utf-8")
