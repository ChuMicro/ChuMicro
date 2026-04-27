"""Generate starter config files during workspace setup.

When the listed files do not exist, this module writes them with
sensible placeholder content from ``scripts/templates/`` so the
contributor can fill in their values immediately.  Existing files
are never overwritten.

Files generated:

* ``devices.yml`` — board registry used by the functional-test
  runner.  Schema owned by ``chumicro_deploy.config.default``.
* ``chumicro-dev-config.toml`` — local-machine config for
  contributors: wifi creds for real-network functional tests,
  MQTT broker overrides, etc.  Gitignored.  See the file header
  for schema.

Called by ``python scripts/run.py setup``.
"""

from __future__ import annotations

from shared import TEMPLATES_DIR
from workspace import ROOT

#: Files to generate: (relative path, template filename).
_CONFIGS: list[tuple[str, str]] = [
    ("devices.yml", "devices.yml.template"),
    ("chumicro-dev-config.toml", "chumicro-dev-config.toml.template"),
]


def generate_config_files() -> int:
    """Write starter config files that do not yet exist.

    Returns 0 always (missing configs are not errors).
    """
    for relative_path, template_name in _CONFIGS:
        target = ROOT / relative_path
        if target.exists():
            print(f"  {relative_path} already exists — skipped")
        else:
            content = (TEMPLATES_DIR / template_name).read_text()
            target.write_text(content)
            print(f"  Created {relative_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(generate_config_files())
