"""Canonical ``workspace.yml`` starter content.

Owned by ``chumicro-workspace`` so the same gitignored-workspace.yml
starter ships from one source to every consumer that needs to
materialise an empty ``workspace.yml`` — most commonly
``chumicro-workspace setup`` on first run.

The actual file content travels with the wheel inside
``_payloads/workspace.yml.template`` so reads work in both editable
installs (live source tree) and pip-installed wheels (unpacked into
site-packages).

The only public surface is :func:`read_workspace_yml_starter` —
returning the file's content as a string.  Callers decide where to
write it.

Pairs with :mod:`chumicro_workspace.devices_yml_starter` — same
pattern, same reason: workbench packages own the canonical content
that consumer repos materialise.

The starter is a complete ``workspace.yml`` carrying defaults +
credentials in one place: schema as commented examples plus the
minimal placeholders a fresh user fills in.
"""

from __future__ import annotations

from pathlib import Path

#: Path to the canonical ``workspace.yml`` starter inside the
#: ``chumicro_workspace`` package.  Resolved at import time so
#: filesystem reads stay simple — the wheel ships the same path.
_WORKSPACE_YML_STARTER_PATH = (
    Path(__file__).resolve().parent
    / "_payloads"
    / "workspace.yml.template"
)


def read_workspace_yml_starter() -> str:
    """Return the canonical ``workspace.yml`` starter content.

    The content is a complete commented-example workspace.yml with
    schema for ``defaults:`` / ``library_sources:`` / ``deploy_targets:``
    / ``quality:`` / ``environments:`` blocks.  Same bytes used by
    every consumer — single source of truth.
    """
    return _WORKSPACE_YML_STARTER_PATH.read_text(encoding="utf-8")
