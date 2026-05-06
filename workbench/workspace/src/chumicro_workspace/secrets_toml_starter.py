"""Canonical ``secrets.toml`` starter content.

Owned by ``chumicro-workspace`` so the same gitignored-secrets.toml
starter ships from one source to every consumer that needs to
materialise an empty ``secrets.toml`` — most commonly
``chumicro-workspace setup`` on first run.

The actual file content travels with the wheel inside
``_payloads/secrets_toml/starter.toml.template`` so reads work in
both editable installs (live source tree) and pip-installed wheels
(unpacked into site-packages).

The only public surface is :func:`read_secrets_toml_starter` —
returning the file's content as a string.  Callers decide where to
write it.

Pairs with :mod:`chumicro_workspace.workspace_yml_starter` and
:mod:`chumicro_workspace.devices_yml_starter` — same pattern, same
reason: workbench packages own the canonical content that consumer
repos materialise.

The starter ships real placeholder values (``"replace-with-your-..."``)
rather than commented-out examples so the parser round-trip preserves
them and the additive setup re-apply path can append new keys without
clobbering user edits.
"""

from __future__ import annotations

from pathlib import Path

#: Path to the canonical ``secrets.toml`` starter inside the
#: ``chumicro_workspace`` package.  Resolved at import time so
#: filesystem reads stay simple — the wheel ships the same path.
_SECRETS_TOML_STARTER_PATH = (
    Path(__file__).resolve().parent
    / "_payloads"
    / "secrets_toml"
    / "starter.toml.template"
)


def read_secrets_toml_starter() -> str:
    """Return the canonical ``secrets.toml`` starter content.

    The content is a complete TOML file carrying ``[wifi]`` and
    ``[mqtt.broker]`` sections with placeholder values that fail
    sanity at deploy time but parse cleanly.  Same bytes used by
    every consumer — single source of truth.
    """
    return _SECRETS_TOML_STARTER_PATH.read_text(encoding="utf-8")
