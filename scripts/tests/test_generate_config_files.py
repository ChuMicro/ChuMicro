"""Tests for ``scripts/generate_config_files.py``.

Validates two contracts:

1. The mono-repo's ``devices.yml.template`` (a contributor-facing
   starter with pre-filled ``sample-{micropython,circuitpython}-board``
   entries) parses cleanly through ``chumicro_deploy.config.default``'s
   schema validator.  Catches drift between the template payload and
   the schema the loader enforces — e.g. someone renames a field on
   the schema side and forgets to update the template.
2. ``generate_config_files`` is idempotent — running it twice produces
   identical content and never overwrites an edited file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_deploy.config.default import (
    DeviceConfigError,
    load_device_registry,
)


def test_devices_yml_template_validates_against_schema(tmp_path: Path) -> None:
    """The starter ``devices.yml.template`` must satisfy the production schema.

    Materialises the template into a temp dir and runs the same
    loader the IDE / functional-test runner uses.  A schema change
    that breaks the template fails here at unit-test time instead of
    surfacing as a confusing "Run setup to generate it" error from
    a contributor's first pytest invocation.
    """
    from generate_config_files import _CONFIGS  # noqa: PLC0415
    from shared import TEMPLATES_DIR  # noqa: PLC0415

    devices_template_name = next(
        template
        for relative, template in _CONFIGS
        if relative == "devices.yml"
    )
    template_text = (TEMPLATES_DIR / devices_template_name).read_text()
    devices_yml = tmp_path / "devices.yml"
    devices_yml.write_text(template_text)

    # ``load_device_registry`` raises ``DeviceConfigError`` on any
    # schema violation — required-field misses, wrong runtime values,
    # malformed defaults, etc.
    devices, defaults = load_device_registry(workspace_root=tmp_path)

    # Sanity checks on the template's contents — these mirror the
    # starter's documented shape, so a deletion of either sample
    # entry surfaces as a clear test failure.
    assert len(devices) >= 2, (
        "template should ship both a circuitpython and micropython sample"
    )
    runtimes = {device.runtime for device in devices}
    assert runtimes == {"circuitpython", "micropython"}, (
        f"template should cover both runtimes, got {runtimes}"
    )
    assert defaults.deploy_mode in ("ram", "flash"), (
        f"defaults.deploy_mode must be valid, got {defaults.deploy_mode}"
    )
    assert defaults.ide_runtime in ("micropython", "circuitpython", "both"), (
        f"defaults.ide_runtime must be valid, got {defaults.ide_runtime}"
    )


def test_devices_yml_template_passes_validation_pure(tmp_path: Path) -> None:
    """A second-tier check: every sample device's id is referenced by defaults.

    Catches the failure mode where a contributor renames a sample
    entry but forgets to update ``defaults.{micropython,circuitpython}``,
    leaving the mono-repo template in a state where ``setup`` writes
    a ``devices.yml`` whose IDE play buttons immediately fail.
    """
    from generate_config_files import _CONFIGS  # noqa: PLC0415
    from shared import TEMPLATES_DIR  # noqa: PLC0415

    devices_template_name = next(
        template
        for relative, template in _CONFIGS
        if relative == "devices.yml"
    )
    template_text = (TEMPLATES_DIR / devices_template_name).read_text()
    devices_yml = tmp_path / "devices.yml"
    devices_yml.write_text(template_text)

    devices, defaults = load_device_registry(workspace_root=tmp_path)
    device_ids = {device.identifier for device in devices}

    if defaults.micropython is not None:
        assert defaults.micropython in device_ids, (
            f"defaults.micropython='{defaults.micropython}' is not a "
            f"registered device id (devices: {sorted(device_ids)})"
        )
    if defaults.circuitpython is not None:
        assert defaults.circuitpython in device_ids, (
            f"defaults.circuitpython='{defaults.circuitpython}' is not a "
            f"registered device id (devices: {sorted(device_ids)})"
        )


def test_generate_config_files_idempotent(tmp_path: Path, monkeypatch) -> None:
    """Running ``generate_config_files`` twice doesn't overwrite existing files.

    The function's contract: write-if-missing, never clobber.  A
    contributor who edits ``devices.yml`` after first ``setup`` and
    later runs setup again must keep their edits.
    """
    import generate_config_files as module  # noqa: PLC0415

    monkeypatch.setattr(module, "ROOT", tmp_path)

    # First run — creates files.
    assert module.generate_config_files() == 0
    devices_yml = tmp_path / "devices.yml"
    assert devices_yml.is_file()
    devices_yml.write_text("# user edited\ndevices: []\n")

    # Second run — must not overwrite the edit.
    assert module.generate_config_files() == 0
    assert devices_yml.read_text() == "# user edited\ndevices: []\n"


def test_devices_yml_template_invalid_runtime_caught_by_schema(
    tmp_path: Path,
) -> None:
    """Sanity-check the validator fires on a deliberately corrupted template.

    Belt-and-suspenders: if the schema validator silently accepts
    bad input the first test above would pass spuriously.  This
    test corrupts the runtime value and expects a hard failure,
    proving the validator is actually doing work.
    """
    from generate_config_files import _CONFIGS  # noqa: PLC0415
    from shared import TEMPLATES_DIR  # noqa: PLC0415

    devices_template_name = next(
        template
        for relative, template in _CONFIGS
        if relative == "devices.yml"
    )
    template_text = (TEMPLATES_DIR / devices_template_name).read_text()
    # Match the device-entry indentation specifically — the
    # ``defaults:`` block also carries ``micropython:`` and ``ide_runtime:
    # micropython`` keys with looser indentation, and a naive replace
    # corrupts those first.
    corrupted = template_text.replace(
        "    runtime: micropython", "    runtime: arduino",
    )
    assert corrupted != template_text, "fixture corruption produced no change"
    devices_yml = tmp_path / "devices.yml"
    devices_yml.write_text(corrupted)

    with pytest.raises(DeviceConfigError, match="invalid runtime"):
        load_device_registry(workspace_root=tmp_path)
