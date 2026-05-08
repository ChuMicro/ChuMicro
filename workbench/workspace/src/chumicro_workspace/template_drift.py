"""Compare materialised user files to their canonical templates.

Walks the parsed file and surfaces dotted-path keys present in the
template but absent from the user's file.  Used by
:mod:`chumicro_workspace.additive_apply` to drive the comment-preserving
append pass during ``setup``.

Two files are checked: ``workspace.yml`` (workspace machinery) and
``secrets.toml`` (device-bound credentials + defaults).  Both diff
against the workbench-owned canonical template from
:mod:`chumicro_workspace.templates`.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError

from chumicro_workspace.templates import (
    read_secrets_toml_template,
    read_workspace_yml_template,
)


def collect_missing_template_paths(
    *,
    workspace_root: Path,
    filename: str = "workspace.yml",
) -> list[str]:
    """Return dotted-path keys present in the canonical template but
    absent from the user's materialised *filename*.

    Returns an empty list when:

    * The user's file doesn't exist (still un-materialised — the
      :func:`materialize_workspace_templates` call earlier in ``setup``
      will land it on this run; nothing to drift against yet).
    * Either parse fails — fail-soft so a bad file never breaks
      ``setup``; the loader's error path surfaces parse problems
      through other channels.
    * Either parse yields a non-mapping top level — drift checking
      only makes sense between two mapping shapes.

    Args:
        workspace_root: Workspace root containing *filename*.
        filename: Either ``"workspace.yml"`` or ``"secrets.toml"``.
    """
    user_path = workspace_root / filename
    if not user_path.is_file():
        return []
    try:
        user_dict = _parse(user_path.read_text(encoding="utf-8"), filename)
        template_dict = _parse(_resolve_template_text(filename), filename)
    except (YAMLError, tomllib.TOMLDecodeError):
        return []
    if not isinstance(user_dict, dict) or not isinstance(template_dict, dict):
        return []
    return _diff_dotted_paths(template_dict, user_dict, prefix="")


def _resolve_template_text(filename: str) -> str:
    """Return the text of the canonical template for *filename*.

    Looks up the reader by name on the module so tests can monkey-patch
    ``read_workspace_yml_template`` / ``read_secrets_toml_template``
    without per-test re-imports.
    """
    if filename == "secrets.toml":
        return read_secrets_toml_template()
    return read_workspace_yml_template()


def _parse(text: str, filename: str) -> Any:
    """Parse *text* as YAML or TOML based on *filename* extension.

    Empty / comment-only YAML returns ``{}``; empty TOML returns the
    same.  Both align with :mod:`chumicro_workspace.loaders` so parser
    semantics stay aligned.
    """
    if filename.endswith(".toml"):
        return tomllib.loads(text)
    parsed = YAML(typ="safe").load(text)
    return parsed if parsed is not None else {}


def _diff_dotted_paths(
    template: dict,
    user: dict,
    *,
    prefix: str,
) -> list[str]:
    """Walk *template*; collect dotted paths absent from *user*.

    Recurses into nested dicts so additions to existing sections
    surface alongside whole-section additions.  Stops at non-dict
    values: once a key matches in *user*, that subtree is the
    user's territory (matches ``merge_configs`` semantics — the
    higher-precedence layer wins outright at any non-dict node).
    """
    missing: list[str] = []
    for key, template_value in template.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if key not in user:
            missing.append(path)
            continue
        user_value = user[key]
        if isinstance(template_value, dict) and isinstance(user_value, dict):
            missing.extend(
                _diff_dotted_paths(template_value, user_value, prefix=path),
            )
    return missing
