"""Exhaustive policy tests for :func:`resolve_deploy_mode`.

This is the one shared deploy-mode policy.  The
:class:`~chumicro_deploy.Deployer` integration contract is covered by
``test_deployer.py``'s ``TestPreflight*`` classes.  Here we drive the
pure function directly so every branch is pinned, including the ones
the Deployer caller never reaches (a non-RAM-capable board, a named
resolution unit).
"""

from chumicro_deploy import DeviceCaps, resolve_deploy_mode


def _resolve(
    configured_mode,
    *,
    staged_files=("/code.py",),
    device_caps=None,
    requires_flash_libs=(),
    resolution_unit=None,
    force=None,
):
    """Call the resolver with explicit, RAM-by-default inputs."""
    return resolve_deploy_mode(
        configured_mode,
        staged_files=list(staged_files),
        device_caps=device_caps if device_caps is not None else DeviceCaps(),
        requires_flash_libs=list(requires_flash_libs),
        resolution_unit=resolution_unit,
        force=force,
    )


class TestForceEscapeHatch:
    """*force* short-circuits the entire policy, silently."""

    def test_force_ram_ignores_every_override_trigger(self):
        mode, message = _resolve(
            "ram",
            staged_files=["/code.py", "/data.der"],
            device_caps=DeviceCaps(supports_ram_mode=False),
            requires_flash_libs=["chumicro-requests"],
            force="ram",
        )
        assert mode == "ram"
        assert message is None

    def test_force_flash_when_configured_ram(self):
        mode, message = _resolve("ram", force="flash")
        assert mode == "flash"
        assert message is None


class TestNonRamConfiguredStaysPut:
    """A flash preference never triggers a switch.  The RAM-only
    triggers are not even evaluated.
    """

    def test_flash_configured_ignores_data_file_and_flagged_libs(self):
        mode, message = _resolve(
            "flash",
            staged_files=["/code.py", "/bundle.der"],
            device_caps=DeviceCaps(supports_ram_mode=False),
            requires_flash_libs=["chumicro-mqtt"],
        )
        assert mode == "flash"
        assert message is None


class TestDeviceCapability:
    """A board that cannot RAM forces flash, ahead of the
    requires_flash / data-file triggers.
    """

    def test_no_ram_capability_switches_with_message(self):
        mode, message = _resolve(
            "ram", device_caps=DeviceCaps(supports_ram_mode=False),
        )
        assert mode == "flash"
        assert "does not support RAM mode" in message

    def test_capability_precedes_requires_flash(self):
        mode, message = _resolve(
            "ram",
            device_caps=DeviceCaps(supports_ram_mode=False),
            requires_flash_libs=["chumicro-requests"],
        )
        assert mode == "flash"
        assert "does not support RAM mode" in message
        assert "requires_flash" not in message


class TestRequiresFlashClosure:
    """A ``requires_flash`` library anywhere in the transitive
    closure forces flash.  The recommendation is keyed off
    *resolution_unit*.
    """

    def test_flagged_lib_switches_and_names_it(self):
        mode, message = _resolve(
            "ram", requires_flash_libs=["chumicro-requests"],
        )
        assert mode == "flash"
        assert "chumicro-requests" in message
        assert "switching to flash mode" in message

    def test_no_recommendation_when_resolution_unit_is_none(self):
        _, message = _resolve(
            "ram", requires_flash_libs=["chumicro-requests"],
        )
        assert "pyproject.toml" not in message

    def test_recommendation_when_unit_not_itself_flagged(self):
        _, message = _resolve(
            "ram",
            requires_flash_libs=["chumicro-requests"],
            resolution_unit="chumicro-ntp",
        )
        assert "chumicro-ntp" in message
        assert "declare `[tool.chumicro] requires_flash = true`" in message
        assert "pyproject.toml" in message

    def test_no_recommendation_when_unit_already_flagged(self):
        _, message = _resolve(
            "ram",
            requires_flash_libs=["chumicro-requests"],
            resolution_unit="chumicro-requests",
        )
        assert "pyproject.toml" not in message

    def test_requires_flash_precedes_data_file(self):
        _, message = _resolve(
            "ram",
            staged_files=["/code.py", "/bundle.der"],
            requires_flash_libs=["chumicro-mqtt"],
        )
        assert "chumicro-mqtt" in message
        assert "bundle.der" not in message


class TestDataFileTrigger:
    """A non-``.py`` file in the staged set forces flash when
    nothing earlier did.
    """

    def test_data_file_switches_and_lists_sorted_names(self):
        mode, message = _resolve(
            "ram",
            staged_files=["/code.py", "/z.bin", "/a.der"],
        )
        assert mode == "flash"
        assert "switching to flash mode" in message
        assert message.index("/a.der") < message.index("/z.bin")

    def test_all_python_set_stays_ram_silently(self):
        mode, message = _resolve(
            "ram", staged_files=["/code.py", "/lib/helper.py"],
        )
        assert mode == "ram"
        assert message is None


class TestRamPreferenceSurvives:
    """A RAM preference with no overriding trigger stays RAM."""

    def test_plain_ram_unchanged(self):
        mode, message = _resolve("ram")
        assert mode == "ram"
        assert message is None


class TestDeviceCapsShape:
    def test_default_is_ram_capable(self):
        assert DeviceCaps().supports_ram_mode is True

    def test_is_frozen(self):
        import dataclasses

        import pytest

        caps = DeviceCaps()
        with pytest.raises(dataclasses.FrozenInstanceError):
            caps.supports_ram_mode = False
