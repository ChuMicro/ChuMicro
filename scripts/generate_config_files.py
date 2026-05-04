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
* ``secrets.yml`` — gitignored credential store referenced from
  ``workspace.yml`` and per-library
  ``functional_tests/config.toml`` via ``!secret <name>``.  Content
  owned by ``chumicro-workspace`` (same source-of-truth pattern as
  devices.yml; shared with the workspace-template repo).  See
  ``chumicro_workspace.read_secrets_yml_starter``.
* ``chumicro-dev-config.toml`` — *legacy* local-machine config for
  contributors.  Phase 3 of
  ``plans/workstreams/scripts-workbench-config-unification.md``
  introduces ``workspace.yml`` + ``secrets.yml`` as the canonical
  shape; Phase 4 retires this file when functional-test conftests
  migrate onto the unified pipeline.  Materialised today so an
  in-flight contributor's tests keep working through the migration.

Called by ``python scripts/run.py setup``.
"""

from __future__ import annotations

from chumicro_workspace import (
    read_devices_yml_starter,
    read_secrets_yml_starter,
)
from repo_layout import ROOT
from shared import TEMPLATES_DIR

#: Mono-repo-only files to generate from ``scripts/templates/``.
#: ``devices.yml`` and ``secrets.yml`` are *not* in this list —
#: their content is owned by the ``chumicro-workspace`` workbench
#: package so the same bytes ship from one source to both the
#: mono-repo and the workspace-template repo.
_CONFIGS: list[tuple[str, str]] = [
    ("chumicro-dev-config.toml", "chumicro-dev-config.toml.template"),
]


def generate_config_files() -> int:
    """Write starter config files that do not yet exist.

    Returns 0 always (missing configs are not errors).
    """
    devices_yml_was_created = _materialise_from_workbench(
        relative_path="devices.yml",
        starter_reader=read_devices_yml_starter,
    )
    _materialise_from_workbench(
        relative_path="secrets.yml",
        starter_reader=read_secrets_yml_starter,
    )

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
