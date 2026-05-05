"""Generate starter config files during workspace setup.

When the listed files do not exist, this module writes them with
sensible placeholder content so the contributor can fill in their
values immediately.  Existing files are never overwritten.

Files generated:

* ``devices.yml`` — board registry used by the functional-test
  runner.  Content owned by ``chumicro-workspace`` (single source
  of truth, shared with the workspace-template repo); schema owned
  by ``chumicro-deploy``.  See
  ``chumicro_workspace.read_devices_yml_starter``.
* ``workspace.local.yml`` — gitignored credential overlay (Decision
  0057).  Same section-namespaced shape as ``workspace.yml``;
  deep-merged on top so any key set here wins over the committed
  defaults.  Content owned by ``chumicro-workspace`` (same
  source-of-truth pattern as devices.yml; shared with the
  workspace-template repo).  See
  ``chumicro_workspace.read_workspace_local_yml_starter``.

Called by ``python scripts/run.py setup``.

Phase 4 of ``plans/workstreams/scripts-workbench-config-unification.md``
retired ``chumicro-dev-config.toml`` — the unified
``workspace.yml`` + ``workspace.local.yml`` pair (read via
``chumicro_workspace.compose_runtime_config``) is the canonical
shape every networking-library functional-test conftest now reads.
Decision 0057 then retired the ``!secret`` marker + ``secrets.yml``
in favour of the structural overlay this script materialises.
"""

from __future__ import annotations

from chumicro_workspace import (
    read_devices_yml_starter,
    read_workspace_local_yml_starter,
)
from repo_layout import ROOT


def generate_config_files() -> int:
    """Write starter config files that do not yet exist.

    Returns 0 always (missing configs are not errors).
    """
    devices_yml_was_created = _materialise_from_workbench(
        relative_path="devices.yml",
        starter_reader=read_devices_yml_starter,
    )
    _materialise_from_workbench(
        relative_path="workspace.local.yml",
        starter_reader=read_workspace_local_yml_starter,
    )

    if devices_yml_was_created:
        # The starter ``devices.yml`` ships with an empty ``devices: []``
        # registry — same shape as the workspace-template repo's
        # ``_workspace_template/devices.yml`` (and from the same source
        # of truth: ``chumicro_workspace.read_devices_yml_starter``).
        # Point the contributor at the unified ``add-device`` flow so
        # functional tests can target real hardware without hand-editing
        # YAML.  See workstream
        # ``plans/workstreams/scripts-workbench-config-unification.md``.
        print(
            "\n  next: register a board with "
            "`python scripts/run.py add-device <id> --address <port>` "
            "(probes hardware identity + fills in defaults on first "
            "registration).",
        )
    return 0


def _materialise_from_workbench(
    *,
    relative_path: str,
    starter_reader,
) -> bool:
    """Write a workbench-owned starter file when the target is missing.

    Returns True when a fresh starter was written, False when the
    file already exists (so callers can suppress follow-up hints
    that don't apply to contributors who already have populated
    files).
    """
    target = ROOT / relative_path
    if target.exists():
        print(f"  {relative_path} already exists — skipped")
        return False
    target.write_text(starter_reader())
    print(f"  Created {relative_path}")
    return True


if __name__ == "__main__":
    raise SystemExit(generate_config_files())
