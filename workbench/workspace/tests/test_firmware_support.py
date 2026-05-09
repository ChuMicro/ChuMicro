"""Tests for the firmware-version floor check."""

from __future__ import annotations

from chumicro_deploy import DeviceImplementation
from chumicro_workspace.firmware_support import (
    MIN_CIRCUITPYTHON_VERSION,
    MIN_MICROPYTHON_VERSION,
    FirmwareSupportStatus,
    check_firmware_supported,
    explain,
    parse_version_tuple,
)


def _impl(name: str, version: str) -> DeviceImplementation:
    return DeviceImplementation(name=name, version=version, machine="", uid="")


class TestParseVersionTuple:
    def test_dotted_three_part(self) -> None:
        assert parse_version_tuple("1.27.0") == (1, 27, 0)

    def test_dotted_two_part(self) -> None:
        assert parse_version_tuple("1.27") == (1, 27)

    def test_strips_release_suffix(self) -> None:
        assert parse_version_tuple("1.27.0-rc1") == (1, 27, 0)

    def test_strips_plus_suffix(self) -> None:
        assert parse_version_tuple("1.27.0+local") == (1, 27, 0)

    def test_empty_returns_none(self) -> None:
        assert parse_version_tuple("") is None

    def test_non_numeric_returns_none(self) -> None:
        assert parse_version_tuple("alpha") is None

    def test_partial_non_numeric_returns_none(self) -> None:
        assert parse_version_tuple("1.alpha.0") is None

    def test_trailing_dot_from_cp_rc_build(self) -> None:
        """CircuitPython RC builds report ``sys.implementation.version``
        as a 4-tuple ``(10, 2, 0, '')`` where the empty string joins
        to a trailing dot.  The parser must take the leading run of
        ints and ignore the empty trailer; otherwise 10.2.0-rc.0
        boards parse as UNPARSEABLE on every probe.
        """
        assert parse_version_tuple("10.2.0.") == (10, 2, 0)

    def test_embedded_non_int_suffix_strips(self) -> None:
        """``"10.2.0.rc.0"`` (alternate join shape) yields the 3-tuple."""
        assert parse_version_tuple("10.2.0.rc.0") == (10, 2, 0)

    def test_micropython_three_part_typical(self) -> None:
        """MP final builds ship the canonical 3-tuple."""
        assert parse_version_tuple("1.28.0") == (1, 28, 0)

    def test_cpython_five_tuple_join_takes_leading_ints(self) -> None:
        """CPython's 5-tuple ``(3, 12, 0, 'final', 0)`` joins to
        ``"3.12.0.final.0"`` — must yield ``(3, 12, 0)`` (stop at 'final').

        Defensive: chumicro doesn't run on CPython firmware in practice,
        but unit tests do exercise this path against host CPython
        when probe captures are replayed.
        """
        assert parse_version_tuple("3.12.0.final.0") == (3, 12, 0)


class TestCheckFirmwareSupported:
    def test_micropython_at_floor_is_supported(self) -> None:
        result = check_firmware_supported(_impl("micropython", "1.27.0"))
        assert result.status is FirmwareSupportStatus.SUPPORTED
        assert result.running_version == (1, 27, 0)
        assert result.floor == MIN_MICROPYTHON_VERSION
        assert result.runtime_name == "micropython"

    def test_micropython_above_floor_is_supported(self) -> None:
        result = check_firmware_supported(_impl("micropython", "1.28.0"))
        assert result.status is FirmwareSupportStatus.SUPPORTED

    def test_micropython_below_floor_is_old(self) -> None:
        result = check_firmware_supported(_impl("micropython", "1.26.0"))
        assert result.status is FirmwareSupportStatus.OLD
        assert result.running_version == (1, 26, 0)
        assert result.floor == MIN_MICROPYTHON_VERSION

    def test_circuitpython_at_floor_is_supported(self) -> None:
        result = check_firmware_supported(_impl("circuitpython", "10.1.0"))
        assert result.status is FirmwareSupportStatus.SUPPORTED
        assert result.floor == MIN_CIRCUITPYTHON_VERSION

    def test_circuitpython_below_floor_is_old(self) -> None:
        result = check_firmware_supported(_impl("circuitpython", "9.2.0"))
        assert result.status is FirmwareSupportStatus.OLD

    def test_circuitpython_patch_above_floor_is_supported(self) -> None:
        """10.1.4 > 10.1.0 — tuple comparison handles patch versions."""
        result = check_firmware_supported(_impl("circuitpython", "10.1.4"))
        assert result.status is FirmwareSupportStatus.SUPPORTED

    def test_unknown_runtime_classifies_as_unknown(self) -> None:
        result = check_firmware_supported(_impl("cpython", "3.13.0"))
        assert result.status is FirmwareSupportStatus.UNKNOWN
        assert result.floor is None
        assert result.runtime_name == "cpython"

    def test_unparseable_version_classifies_as_unparseable(self) -> None:
        result = check_firmware_supported(_impl("micropython", "weird"))
        assert result.status is FirmwareSupportStatus.UNPARSEABLE
        assert result.running_version is None
        assert result.floor == MIN_MICROPYTHON_VERSION

    def test_runtime_name_lowercased(self) -> None:
        result = check_firmware_supported(_impl("MicroPython", "1.27.0"))
        assert result.status is FirmwareSupportStatus.SUPPORTED
        assert result.runtime_name == "micropython"


class TestExplain:
    def test_supported_is_silent(self) -> None:
        result = check_firmware_supported(_impl("micropython", "1.27.0"))
        assert explain(result) == []

    def test_old_mentions_running_and_floor(self) -> None:
        result = check_firmware_supported(_impl("micropython", "1.26.0"))
        lines = explain(result)
        joined = " ".join(lines)
        assert "1.26.0" in joined
        assert "1.27.0" in joined
        assert "install-firmware" in joined

    def test_old_circuitpython_mentions_runtime_name(self) -> None:
        result = check_firmware_supported(_impl("circuitpython", "9.2.0"))
        lines = explain(result)
        joined = " ".join(lines)
        assert "circuitpython" in joined
        assert "9.2.0" in joined
        assert "10.1.0" in joined

    def test_unknown_runtime_mentions_runtime_name(self) -> None:
        result = check_firmware_supported(_impl("cpython", "3.13.0"))
        lines = explain(result)
        joined = " ".join(lines)
        assert "cpython" in joined
        assert "tested matrix" in joined

    def test_unparseable_explains_what_failed(self) -> None:
        result = check_firmware_supported(_impl("micropython", "weird"))
        lines = explain(result)
        joined = " ".join(lines)
        assert "version" in joined.lower()
