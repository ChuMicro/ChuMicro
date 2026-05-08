"""Generate starter config files during workspace setup.

When the listed files do not exist, this module writes them with
sensible placeholder content so the contributor can fill in their
values immediately.  Existing files are never overwritten.

``materialize_workbench_starters`` fills in workbench-owned starters
(``devices.yml``, ``workspace.yml``, ``secrets.toml``) from the
canonical content in ``chumicro_workspace``'s ``_payloads/``.

Files generated:

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
    materialize_workbench_starters,
)
from repo_layout import ROOT


def generate_config_files() -> int:
    """Write starter config files that do not yet exist.

    Returns 0 always (missing configs are not errors).
    """
    workbench_report = materialize_workbench_starters(ROOT)

    devices_yml_was_created = any(
        path == "devices.yml" and action == ApplyAction.MATERIALIZED
        for path, action in workbench_report
    )

    for relative_path, action in workbench_report:
        if action == ApplyAction.MATERIALIZED:
            print(f"  Created {relative_path}")
        elif action == ApplyAction.UNCHANGED:
            print(f"  {relative_path} already exists — skipped")

    if devices_yml_was_created:
        # The starter ``devices.yml`` ships with an empty
        # ``devices: []`` registry; point the contributor at the
        # add-device flow so functional tests can target real
        # hardware without hand-editing YAML.
        print(
            "\n  next: register a board with "
            "`python scripts/run.py add-device <id> --address <port>` "
            "(probes hardware identity + fills in defaults on first "
            "registration).",
        )

    # Schema-drift surface: when the user's ``workspace.yml`` /
    # ``secrets.toml`` was materialised before a recent starter
    # update, list the fields the upstream starter has gained.
    # No-op when the user's file already covers the starter's schema.
    print_starter_drift_report(ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(generate_config_files())
