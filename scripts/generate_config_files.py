"""Generate starter device configuration files during workspace setup.

When ``devices.yml`` or ``device-config.yml`` do not exist, this module
writes them with sensible placeholder content so the user can fill in
their board details immediately.  Existing files are never overwritten.

Called by ``python scripts/run.py setup``.
"""

from __future__ import annotations

from pathlib import Path

from workspace import ROOT

_TEMPLATES_DIR = Path(__file__).parent / "templates"

#: Files to generate: (relative path, template filename).
_CONFIGS: list[tuple[str, str]] = [
    ("devices.yml", "devices.yml.template"),
    ("device-config.yml", "device-config.yml.template"),
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
            content = (_TEMPLATES_DIR / template_name).read_text()
            target.write_text(content)
            print(f"  Created {relative_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(generate_config_files())
