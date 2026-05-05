"""Canonical ``workspace.local.yml`` starter content.

Owned by ``chumicro-workspace`` so the same gitignored-overrides
starter ships from one source to:

* the ChuMicro mono-repo's ``python scripts/run.py setup`` (via
  ``scripts/generate_config_files.py``)
* the workspace-template repo's first-clone setup flow (via
  ``chumicro-workspace setup`` materialising user workspaces)
* any other consumer that needs to materialise an empty
  ``workspace.local.yml``

The actual file content travels with the wheel inside
``_payloads/workspace_local_yml/starter.yml.template`` so reads work
in both editable installs (live source tree) and pip-installed wheels
(unpacked into site-packages).

The only public surface is :func:`read_workspace_local_yml_starter` —
returning the file's content as a string.  Callers decide where to
write it.

Pairs with :mod:`chumicro_workspace.devices_yml_starter` — same
pattern, same reason: workbench packages own the canonical content
that consumer repos materialise.
"""

from __future__ import annotations

from pathlib import Path

#: Path to the canonical ``workspace.local.yml`` starter inside the
#: ``chumicro_workspace`` package.  Resolved at import time so
#: filesystem reads stay simple — the wheel ships the same path.
_WORKSPACE_LOCAL_YML_STARTER_PATH = (
    Path(__file__).resolve().parent
    / "_payloads"
    / "workspace_local_yml"
    / "starter.yml.template"
)


def read_workspace_local_yml_starter() -> str:
    """Return the canonical empty ``workspace.local.yml`` content.

    The content is the documented commented-out example shape with
    a ``defaults.wifi.password`` placeholder showing the section-
    namespaced overlay schema.  Same bytes used by every consumer —
    single source of truth.
    """
    return _WORKSPACE_LOCAL_YML_STARTER_PATH.read_text(encoding="utf-8")
