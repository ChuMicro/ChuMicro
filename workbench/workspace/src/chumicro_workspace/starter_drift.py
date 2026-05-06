"""Compare materialised user files to their canonical starters and
report fields the user is missing.

Strategy B from the setup-schema-reconciliation workstream — print
the diff during ``setup``, no auto-application.  Walks the parsed
file; commented examples in the starter are intentionally not
surfaced (they are guidance, not schema obligations).

Two files are drift-checked: ``workspace.yml`` (workspace machinery)
and ``secrets.toml`` (device-bound credentials + defaults).  Both
follow the same pattern — repo-specific ``_workspace_template/<name>``
override beats the workbench-owned starter when present.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path
from typing import IO, Any

from ruamel.yaml import YAML, YAMLError

from chumicro_workspace.secrets_toml_starter import (
    read_secrets_toml_starter,
)
from chumicro_workspace.workspace_yml_starter import (
    read_workspace_yml_starter,
)

#: Drift-check entries: each tuple is the user-facing filename, the
#: parser function, and the canonical-starter reader function name on
#: ``chumicro_workspace``.  ``_workspace_template/<filename>`` always
#: wins over the workbench-owned default when present.
_DRIFT_CHECKS: tuple[tuple[str, str], ...] = (
    ("workspace.yml", "read_workspace_yml_starter"),
    ("secrets.toml", "read_secrets_toml_starter"),
)


def collect_missing_starter_paths(
    *,
    workspace_root: Path,
    filename: str = "workspace.yml",
) -> list[str]:
    """Return dotted-path keys present in the canonical starter but
    absent from the user's materialised *filename*.

    Returns an empty list when:

    * The user's file doesn't exist (still un-materialised — the
      :func:`materialize_workbench_starters` call earlier in ``setup``
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
        starter_dict = _parse(
            _resolve_starter_text(workspace_root, filename), filename,
        )
    except (YAMLError, tomllib.TOMLDecodeError):
        return []
    if not isinstance(user_dict, dict) or not isinstance(starter_dict, dict):
        return []
    return _diff_dotted_paths(starter_dict, user_dict, prefix="")


def print_starter_drift_report(
    workspace_root: Path,
    *,
    stream: IO[str] | None = None,
) -> int:
    """Print Strategy-B drift reports for every checked file.

    Returns the total count of missing fields printed (zero when the
    user's files already cover the starters' schemas).  Caller-friendly
    return so a test or wrapper can assert "no drift" without re-parsing
    the printed output.

    Walks :data:`_DRIFT_CHECKS` and emits one section per file with
    drift; files with no drift print nothing.
    """
    output_stream = stream if stream is not None else sys.stdout
    total_missing = 0
    for filename, _reader_attr in _DRIFT_CHECKS:
        missing = collect_missing_starter_paths(
            workspace_root=workspace_root, filename=filename,
        )
        if not missing:
            continue
        starter_label = _starter_source_label(workspace_root, filename)
        plural = "field" if len(missing) == 1 else "fields"
        print(
            f"setup: {filename} is missing {len(missing)} {plural} "
            "from the upstream starter:",
            file=output_stream,
        )
        for path in missing:
            print(f"  - {path}", file=output_stream)
        print(
            f"  Copy them in from {starter_label} if you want them.",
            file=output_stream,
        )
        total_missing += len(missing)
    return total_missing


def _resolve_starter_text(workspace_root: Path, filename: str) -> str:
    """Return the text of the starter that would materialise *filename*.

    Looks up the workbench reader by name on the module so tests can
    monkey-patch ``read_workspace_yml_starter`` / ``read_secrets_toml_starter``
    without per-test re-imports.
    """
    repo_override = workspace_root / "_workspace_template" / filename
    if repo_override.is_file():
        return repo_override.read_text(encoding="utf-8")
    if filename == "secrets.toml":
        return read_secrets_toml_starter()
    return read_workspace_yml_starter()


def _starter_source_label(workspace_root: Path, filename: str) -> str:
    """Return a human-readable path the user can copy from."""
    repo_override = workspace_root / "_workspace_template" / filename
    if repo_override.is_file():
        return f"_workspace_template/{filename}"
    if filename == "workspace.yml":
        return (
            "the workbench-owned starter "
            "(chumicro_workspace.read_workspace_yml_starter())"
        )
    return (
        "the workbench-owned starter "
        "(chumicro_workspace.read_secrets_toml_starter())"
    )


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
    starter: dict,
    user: dict,
    *,
    prefix: str,
) -> list[str]:
    """Walk *starter*; collect dotted paths absent from *user*.

    Recurses into nested dicts so additions to existing sections
    surface alongside whole-section additions.  Stops at non-dict
    values: once a key matches in *user*, that subtree is the
    user's territory (matches ``merge_configs`` semantics — the
    higher-precedence layer wins outright at any non-dict node).
    """
    missing: list[str] = []
    for key, starter_value in starter.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if key not in user:
            missing.append(path)
            continue
        user_value = user[key]
        if isinstance(starter_value, dict) and isinstance(user_value, dict):
            missing.extend(
                _diff_dotted_paths(starter_value, user_value, prefix=path),
            )
    return missing
