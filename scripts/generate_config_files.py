"""Generate starter config files during workspace setup.

When the listed files do not exist, this module writes them with
sensible placeholder content so the contributor can fill in their
values immediately.  Existing files are never overwritten.

Two-phase materialisation (matches ``chumicro-workspace setup``):

1. ``materialize_templates`` walks ``_workspace_template/`` and
   materialises any file under it whose target at the workspace
   root is missing.  The mono-repo's ``_workspace_template/secrets.toml``
   carries placeholder wifi creds and a placeholder
   ``mqtt.broker.host`` and lands at ``./secrets.toml``.

2. ``materialize_workbench_starters`` then fills in any remaining
   workbench-owned starters (``devices.yml``, ``workspace.yml``,
   ``secrets.toml``) from the canonical content in
   ``chumicro_workspace``'s ``_payloads/``.  Acts as the fallback
   when ``_workspace_template/`` doesn't carry a copy.

Files generated (lowest-precedence content shown — the
``_workspace_template/`` override wins when present):

* ``devices.yml`` — board registry used by the functional-test
  runner.  Content owned by ``chumicro-workspace`` (single source
  of truth, shared with the workspace-template repo); schema owned
  by ``chumicro-deploy``.
* ``workspace.yml`` — gitignored workspace machinery
  (``library_sources``, ``deploy_targets``, ``quality``).  Host-only;
  never reaches a device.
* ``secrets.toml`` — gitignored workspace-wide credentials + device
  defaults.  Flows through ``compose_runtime_config`` into
  ``runtime_config.msgpack`` at deploy time.
"""

from __future__ import annotations

from chumicro_workspace.starter_drift import print_starter_drift_report
from chumicro_workspace.template_apply import (
    ApplyAction,
    materialize_templates,
    materialize_workbench_starters,
)
from repo_layout import ROOT


def generate_config_files() -> int:
    """Write starter config files that do not yet exist.

    Returns 0 always (missing configs are not errors).
    """
    template_report = materialize_templates(ROOT)
    workbench_report = materialize_workbench_starters(ROOT)

    devices_yml_was_created = _was_materialised(
        relative_path="devices.yml",
        reports=(template_report, workbench_report),
    )

    for report in (template_report, workbench_report):
        for relative_path, action in report:
            if action == ApplyAction.MATERIALIZED:
                print(f"  Created {relative_path}")
            elif action == ApplyAction.UNCHANGED:
                print(f"  {relative_path} already exists — skipped")

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

    # Schema-drift surface: when the user's ``workspace.yml`` was
    # materialised before a recent starter update, list the fields
    # the upstream starter has gained.  No-op when the user's file
    # already covers the starter's schema.  See workstream
    # ``plans/workstreams/setup-schema-reconciliation.md``.
    print_starter_drift_report(ROOT)
    return 0


def _was_materialised(*, relative_path: str, reports: tuple) -> bool:
    """Return True when *relative_path* was MATERIALIZED in any report."""
    for report in reports:
        for path, action in report:
            if path == relative_path and action == ApplyAction.MATERIALIZED:
                return True
    return False


if __name__ == "__main__":
    raise SystemExit(generate_config_files())
