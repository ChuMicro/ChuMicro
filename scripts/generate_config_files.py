"""Generate template config files during workspace setup.

When the listed files do not exist, this module writes them with
sensible placeholder content so the contributor can fill in their
values immediately.  Existing files are never overwritten.

``materialize_workspace_templates`` fills in initial template text
for ``devices.yml`` / ``workspace.yml`` / ``secrets.toml`` from the
readers in :mod:`chumicro_workspace.templates` (``devices.yml`` ships
from ``chumicro_deploy`` since it owns the schema).

Files generated:

* ``devices.yml``: board registry used by the functional-test
  runner.  Schema and empty-registry template both owned by
  ``chumicro-deploy``.
* ``workspace.yml``: gitignored workspace machinery
  (``library_sources``, ``deploy_targets``, ``quality``).  Host-only;
  never reaches a device.
* ``secrets.toml``: gitignored workspace-wide credentials + device
  defaults.  Flows through ``compose_runtime_config`` into
  ``runtime_config.msgpack`` at deploy time.
"""

from __future__ import annotations

from chumicro_workspace.template_apply import (
    ApplyAction,
    materialize_workspace_templates,
)
from repo_layout import ROOT


def generate_config_files() -> int:
    """Write template config files that do not yet exist.

    Returns 0 always (missing configs are not errors).
    """
    template_report = materialize_workspace_templates(ROOT)

    devices_yml_was_created = any(
        path == "devices.yml" and action == ApplyAction.MATERIALIZED
        for path, action in template_report
    )

    for relative_path, action in template_report:
        if action == ApplyAction.MATERIALIZED:
            print(f"  Created {relative_path}")
        elif action == ApplyAction.UNCHANGED:
            print(f"  {relative_path} already exists — skipped")

    if devices_yml_was_created:
        # The template ``devices.yml`` ships with an empty
        # ``devices: []`` registry; point the contributor at the
        # add-device flow so functional tests can target real
        # hardware without hand-editing YAML.
        print(
            "\n  next: register a board with "
            "`python scripts/run.py add-device <id> --address <port>` "
            "(probes hardware identity + fills in defaults on first "
            "registration).",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(generate_config_files())
