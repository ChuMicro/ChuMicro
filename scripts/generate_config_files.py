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
* ``chumicro-dev-config.toml`` — local-machine config for
  contributors: wifi creds for real-network functional tests,
  MQTT broker overrides, etc.  Gitignored.  See the file header
  for schema.  (Phase 4 of
  ``plans/workstreams/scripts-workbench-config-unification.md``
  retires this file in favour of the unified workspace.yml +
  secrets.yml + per-library config.toml pipeline.)

Called by ``python scripts/run.py setup``.
"""

from __future__ import annotations

from chumicro_workspace import read_devices_yml_starter
from repo_layout import ROOT
from shared import TEMPLATES_DIR

#: Mono-repo-only files to generate from ``scripts/templates/``.
#: ``devices.yml`` is *not* in this list — its content is owned by
#: the ``chumicro-workspace`` workbench package (see
#: ``read_devices_yml_starter``) so the same bytes ship from one
#: source to both the mono-repo and the workspace-template repo.
_CONFIGS: list[tuple[str, str]] = [
    ("chumicro-dev-config.toml", "chumicro-dev-config.toml.template"),
]


def generate_config_files() -> int:
    """Write starter config files that do not yet exist.

    Returns 0 always (missing configs are not errors).
    """
    devices_yml_was_created = _materialise_devices_yml()

    for relative_path, template_name in _CONFIGS:
        target = ROOT / relative_path
        if target.exists():
            print(f"  {relative_path} already exists — skipped")
        else:
            content = (TEMPLATES_DIR / template_name).read_text()
            target.write_text(content)
            print(f"  Created {relative_path}")

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


def _materialise_devices_yml() -> bool:
    """Write ``devices.yml`` from the workbench payload when missing.

    Returns True when a fresh starter was written, False when the
    file already exists (so callers don't print stale follow-up
    hints to a contributor who already has a populated registry).
    """
    target = ROOT / "devices.yml"
    if target.exists():
        print("  devices.yml already exists — skipped")
        return False
    target.write_text(read_devices_yml_starter())
    print("  Created devices.yml")
    return True


if __name__ == "__main__":
    raise SystemExit(generate_config_files())
