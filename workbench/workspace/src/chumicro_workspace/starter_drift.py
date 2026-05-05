"""Compare a materialised ``workspace.yml`` to its canonical starter
and report fields the user is missing.

Strategy B from the setup-schema-reconciliation workstream — print
the diff during ``setup``, no auto-application.  Walks the parsed
YAML; commented examples in the starter are intentionally not
surfaced (they are guidance, not schema obligations).

The "canonical starter" is whichever source ``materialize_templates``
+ ``materialize_workbench_starters`` would land if the user's
``workspace.yml`` did not already exist:

* ``<workspace_root>/_workspace_template/workspace.yml`` when present
  (a repo-specific override — the mono-repo's case).
* the workbench-owned starter from
  :func:`read_workspace_yml_starter` otherwise.

Both readers strip nothing; the YAML parse only sees uncommented
keys, which is the schema we expect users to track.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import IO, Any

from ruamel.yaml import YAML, YAMLError

from chumicro_workspace.workspace_yml_starter import (
    read_workspace_yml_starter,
)

#: Filename that, when present at ``<workspace_root>/_workspace_template/``,
#: overrides the workbench-owned starter as the materialisation source.
_REPO_OVERRIDE_RELATIVE = Path("_workspace_template") / "workspace.yml"

#: Workspace-root-relative path of the user-edited file we diff.
_USER_FILE_RELATIVE = Path("workspace.yml")


def collect_missing_starter_paths(
    *,
    workspace_root: Path,
) -> list[str]:
    """Return dotted-path keys present in the canonical starter but
    absent from the user's ``workspace.yml``.

    Returns an empty list when:

    * The user's ``workspace.yml`` doesn't exist (still un-materialised
      — :func:`materialize_workbench_starters` will land it on this
      ``setup`` run; nothing to drift against yet).
    * Either YAML parses to an empty document or non-mapping top
      level — drift checking only makes sense between two mapping
      shapes.
    * Either YAML fails to parse — fail-soft so a bad file never
      breaks ``setup``; the loader's error path surfaces parse
      problems through other channels.

    Args:
        workspace_root: Workspace root containing ``workspace.yml``
            (after materialisation).
    """
    user_path = workspace_root / _USER_FILE_RELATIVE
    if not user_path.is_file():
        return []
    try:
        user_dict = _load_yaml_text(user_path.read_text(encoding="utf-8"))
        starter_dict = _load_yaml_text(_resolve_starter_text(workspace_root))
    except YAMLError:
        return []
    if not isinstance(user_dict, dict) or not isinstance(starter_dict, dict):
        return []
    return _diff_dotted_paths(starter_dict, user_dict, prefix="")


def print_starter_drift_report(
    workspace_root: Path,
    *,
    stream: IO[str] | None = None,
) -> int:
    """Print Strategy-B drift report for *workspace_root* to *stream*.

    Returns the count of missing fields printed (zero when the user's
    file already covers the starter's schema).  Caller-friendly
    return so a test or wrapper can assert "no drift" without
    re-parsing the printed output.

    The output names the source path the user can copy from — the
    repo-specific override when present, else the workbench-owned
    starter (qualified as such so the user knows the canonical
    bytes live inside the ``chumicro-workspace`` package, not on
    disk).
    """
    output_stream = stream if stream is not None else sys.stdout
    missing = collect_missing_starter_paths(workspace_root=workspace_root)
    if not missing:
        return 0
    starter_label = _starter_source_label(workspace_root)
    plural = "field" if len(missing) == 1 else "fields"
    print(
        f"setup: workspace.yml is missing {len(missing)} {plural} "
        "from the upstream starter:",
        file=output_stream,
    )
    for path in missing:
        print(f"  - {path}", file=output_stream)
    print(
        f"  Copy them in from {starter_label} if you want them.",
        file=output_stream,
    )
    return len(missing)


def _resolve_starter_text(workspace_root: Path) -> str:
    """Return the YAML text of whichever starter would materialise
    a fresh ``workspace.yml`` at *workspace_root*.
    """
    repo_override = workspace_root / _REPO_OVERRIDE_RELATIVE
    if repo_override.is_file():
        return repo_override.read_text(encoding="utf-8")
    return read_workspace_yml_starter()


def _starter_source_label(workspace_root: Path) -> str:
    """Return a human-readable path the user can copy from."""
    repo_override = workspace_root / _REPO_OVERRIDE_RELATIVE
    if repo_override.is_file():
        return _REPO_OVERRIDE_RELATIVE.as_posix()
    return "the workbench-owned starter (chumicro_workspace.read_workspace_yml_starter())"


def _load_yaml_text(text: str) -> Any:
    """Parse YAML text; return ``{}`` for empty/comment-only input.

    Uses the same ``YAML(typ="safe")`` shape as
    :mod:`chumicro_workspace.loaders` so parser semantics stay
    aligned.
    """
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
