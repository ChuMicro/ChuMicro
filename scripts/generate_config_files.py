"""Generate starter config files during workspace setup.

When the listed files do not exist, this module writes them with
sensible placeholder content from ``scripts/templates/`` so the
contributor can fill in their values immediately.  Existing files
are never overwritten.

Files generated:

* ``devices.yml`` / ``device-config.yml`` — board registry + per-
  device deploy hints used by the functional-test runner.
* ``chumicro-dev-config.toml`` — local-machine config for
  contributors: wifi creds for real-network functional tests, MQTT
  broker overrides, etc.  Gitignored.  See the file header for
  schema.

Called by ``python scripts/run.py setup``.
"""

from __future__ import annotations

from shared import TEMPLATES_DIR
from workspace import ROOT

#: Files to generate: (relative path, template filename).
_CONFIGS: list[tuple[str, str]] = [
    ("devices.yml", "devices.yml.template"),
    ("device-config.yml", "device-config.yml.template"),
    ("chumicro-dev-config.toml", "chumicro-dev-config.toml.template"),
]


def _migrate_legacy_wifi_creds() -> None:
    """One-shot migration: copy `.scratch/wifi-creds.toml` content into the new file.

    Pre-2026-04-27 the wifi creds + functional-test creds lived at
    ``.scratch/wifi-creds.toml`` (gitignored).  ``.scratch/`` is
    explicitly throwaway agent-temp space, so when ``setup`` runs and
    finds the legacy file but no top-level ``chumicro-dev-config.toml``,
    we promote the credentials to the new home and tell the user.
    Idempotent — only fires when the legacy file exists and the new
    one is still the unedited template.
    """
    legacy_path = ROOT / ".scratch" / "wifi-creds.toml"
    new_path = ROOT / "chumicro-dev-config.toml"
    if not legacy_path.exists() or not new_path.exists():
        return
    new_text = new_path.read_text()
    # Only migrate if the new file is still the unedited template
    # (every wifi key is commented out).
    if "\nssid =" in new_text or "\npassword =" in new_text:
        return  # User has already edited the new file — don't touch it.
    try:
        legacy_text = legacy_path.read_text()
    except OSError:
        return
    new_path.write_text(
        new_text
        + "\n\n# -- Migrated 2026-04-27 from .scratch/wifi-creds.toml --\n"
        + legacy_text,
    )
    print(
        "  Migrated wifi creds from .scratch/wifi-creds.toml into "
        "chumicro-dev-config.toml.  You can delete the legacy file."
    )


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
    _migrate_legacy_wifi_creds()
    return 0


if __name__ == "__main__":
    raise SystemExit(generate_config_files())
