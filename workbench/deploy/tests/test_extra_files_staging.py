"""Tests for ``transport.stage(extra_files=...)``.

Verifies the per-transport behavior of the ``extra_files``
keyword.  Three concrete transports + the host-side
:class:`FakeTransport` each get a slice:

* CircuitPython RAM mode: raises :class:`UnsupportedExtraFilesError`
  when ``extra_files`` is non-empty (RAM mode bypasses the device
  filesystem; there's nowhere to land bytes).
* CircuitPython flash mode: writes each ``(device_path, bytes)``
  pair into the local staging tree at the matching relative path,
  ready for rsync to push to the CIRCUITPY drive.
* MicroPython copy / mount mode: writes each pair into the staging
  tree (copy mode rsyncs it to flash, mount mode mounts the dir as
  the device filesystem — both end states give the device a file
  at the requested path).
* :class:`FakeTransport`: stores the bytes in
  ``staged_extra_files`` for assert-on by tests.

The on-device consumers stage ``runtime_config.msgpack`` and read
it via ``chumicro_config.load_runtime_config`` — see
``chumicro_pytest_device.runtime_config.set_runtime_config`` for
the conftest-side staging hook.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from chumicro_deploy import (
    CircuitpythonTransport,
    FakeTransport,
    UnsupportedExtraFilesError,
)
from chumicro_deploy.micropython_transport import (
    MicropythonTransport,
    MicropythonTransportError,
)

# ---------------------------------------------------------------------------
# FakeTransport — host-side stub used by every other transport's tests.
# ---------------------------------------------------------------------------


class TestFakeTransportExtraFiles:
    def test_records_extra_files_in_flash_mode(self, tmp_path: Path) -> None:
        fake = FakeTransport(mode="flash")
        fake.stage(
            source_dirs=[],
            test_files=[],
            harness_source=tmp_path,
            extra_files={"/runtime_config.msgpack": b"\x82\xa4wifi\x80"},
        )
        assert fake.staged_extra_files == {
            "/runtime_config.msgpack": b"\x82\xa4wifi\x80",
        }

    def test_records_multiple_extra_files(self, tmp_path: Path) -> None:
        fake = FakeTransport(mode="flash")
        fake.stage(
            source_dirs=[],
            test_files=[],
            harness_source=tmp_path,
            extra_files={
                "/runtime_config.msgpack": b"\x80",
                "/calibration.bin": b"\x00\x01\x02\x03",
            },
        )
        assert fake.staged_extra_files == {
            "/runtime_config.msgpack": b"\x80",
            "/calibration.bin": b"\x00\x01\x02\x03",
        }

    def test_ram_mode_raises_on_non_empty_extra_files(
        self, tmp_path: Path,
    ) -> None:
        fake = FakeTransport(mode="ram")
        with pytest.raises(
            UnsupportedExtraFilesError, match="cannot stage extra_files",
        ):
            fake.stage(
                source_dirs=[],
                test_files=[],
                harness_source=tmp_path,
                extra_files={"/runtime_config.msgpack": b"\x80"},
            )
        # Nothing leaks into the staged-files dict on the failed call.
        assert fake.staged_extra_files == {}

    def test_ram_mode_with_no_extra_files_passes_through(
        self, tmp_path: Path,
    ) -> None:
        # Bare RAM-mode stage call (the common case before extra_files
        # existed) must not regress — only non-empty extra_files raises.
        fake = FakeTransport(mode="ram")
        fake.stage(
            source_dirs=[],
            test_files=[],
            harness_source=tmp_path,
        )
        assert fake.staged_extra_files == {}

    def test_extra_files_call_recorded_in_calls_log(
        self, tmp_path: Path,
    ) -> None:
        fake = FakeTransport(mode="flash")
        fake.stage(
            source_dirs=[],
            test_files=[],
            harness_source=tmp_path,
            extra_files={"/runtime_config.msgpack": b"\x80"},
        )
        # The full positional + keyword tuple landed in calls — tests
        # that assert on the recorded interaction can see extra_files
        # without poking the dedicated attribute.
        assert len(fake.calls) == 1
        action, args = fake.calls[0]
        assert action == "stage"
        # 5-tuple: source_dirs, test_files, harness_source, extra_modules,
        # extra_files.  extra_modules is None here.
        assert args[4] == {"/runtime_config.msgpack": b"\x80"}


# ---------------------------------------------------------------------------
# CircuitPython transport — RAM mode raises, flash mode lays the file out
# in the staging tree.
# ---------------------------------------------------------------------------


class TestCircuitpythonRamModeRaises:
    def test_non_empty_extra_files_raises_in_ram_mode(
        self, tmp_path: Path,
    ) -> None:
        transport = CircuitpythonTransport(
            address="/dev/null", mode="ram",
        )
        with pytest.raises(
            UnsupportedExtraFilesError, match="cannot stage extra_files",
        ):
            transport.stage(
                source_dirs=[],
                test_files=[],
                harness_source=tmp_path,
                extra_files={"/runtime_config.msgpack": b"\x80"},
            )

    def test_empty_extra_files_dict_does_not_raise(
        self, tmp_path: Path,
    ) -> None:
        transport = CircuitpythonTransport(
            address="/dev/null", mode="ram",
        )
        # Empty dict is the same as None — no extra files, no raise.
        transport.stage(
            source_dirs=[],
            test_files=[],
            harness_source=tmp_path,
            extra_files={},
        )

    def test_none_extra_files_does_not_raise(self, tmp_path: Path) -> None:
        transport = CircuitpythonTransport(
            address="/dev/null", mode="ram",
        )
        transport.stage(
            source_dirs=[],
            test_files=[],
            harness_source=tmp_path,
        )


class TestCircuitpythonFlashModeStagingTree:
    """Flash-mode staging-tree assertions via the local _build_local_staging_tree."""

    def test_extra_files_landed_at_relative_path(self, tmp_path: Path) -> None:
        transport = CircuitpythonTransport(
            address="/dev/null", mode="flash",
        )
        staging = tmp_path / "staging"
        staging.mkdir()
        transport._build_local_staging_tree(
            staging,
            source_dirs=[],
            test_files=[],
            harness_source=staging,
            extra_files={"/runtime_config.msgpack": b"\x82\xa4wifi\x80"},
        )
        result_path = staging / "runtime_config.msgpack"
        assert result_path.is_file()
        assert result_path.read_bytes() == b"\x82\xa4wifi\x80"

    def test_extra_files_with_nested_path_creates_parents(
        self, tmp_path: Path,
    ) -> None:
        transport = CircuitpythonTransport(
            address="/dev/null", mode="flash",
        )
        staging = tmp_path / "staging"
        staging.mkdir()
        transport._build_local_staging_tree(
            staging,
            source_dirs=[],
            test_files=[],
            harness_source=staging,
            extra_files={"/data/calibration.bin": b"\x00\x01\x02\x03"},
        )
        result_path = staging / "data" / "calibration.bin"
        assert result_path.is_file()
        assert result_path.read_bytes() == b"\x00\x01\x02\x03"

    def test_empty_path_component_raises(self, tmp_path: Path) -> None:
        transport = CircuitpythonTransport(
            address="/dev/null", mode="flash",
        )
        staging = tmp_path / "staging"
        staging.mkdir()
        # Just a leading slash with nothing after — caller bug.
        with pytest.raises(
            Exception, match="no path component",
        ):
            transport._build_local_staging_tree(
                staging,
                source_dirs=[],
                test_files=[],
                harness_source=staging,
                extra_files={"/": b"x"},
            )

    def test_no_extra_files_param_leaves_staging_empty(
        self, tmp_path: Path,
    ) -> None:
        transport = CircuitpythonTransport(
            address="/dev/null", mode="flash",
        )
        staging = tmp_path / "staging"
        staging.mkdir()
        transport._build_local_staging_tree(
            staging,
            source_dirs=[],
            test_files=[],
            harness_source=staging,
        )
        # Just the lib/ subdir merge_packages creates; no stray files.
        children = sorted(child.name for child in staging.iterdir())
        assert children == ["lib"]


# ---------------------------------------------------------------------------
# MicroPython transport — both copy and mount modes accept extra_files.
# ---------------------------------------------------------------------------


@pytest.fixture
def mp_copy_transport():
    """``MicropythonTransport(mode='copy')`` with explicit teardown.

    Under ``pytest -W error`` on Python 3.14, the weakref-finalizer
    path that ``tempfile.TemporaryDirectory`` uses can surface a
    bare-``None`` ``PytestUnraisableExceptionWarning`` when the
    transport instance is garbage-collected after the test exits.
    Forcing cleanup in the fixture's teardown phase is deterministic.
    """
    transport = MicropythonTransport(address="/dev/null", mode="copy")
    yield transport
    if transport._staging_dir is not None:
        transport._staging_dir.cleanup()


@pytest.fixture
def mp_mount_transport():
    """``MicropythonTransport(mode='mount')`` with explicit teardown."""
    transport = MicropythonTransport(address="/dev/null", mode="mount")
    yield transport
    if transport._staging_dir is not None:
        transport._staging_dir.cleanup()


class TestMicropythonStagingTreeExtraFiles:
    """The shared staging-tree write covers both mount and copy modes."""

    def test_copy_mode_lands_extra_files_in_staging(
        self, mp_copy_transport: MicropythonTransport, tmp_path: Path,
    ) -> None:
        # Patch out the mpremote subprocess call — we only care about
        # the staging tree.
        with patch.object(mp_copy_transport, "_run_mpremote") as run:
            mp_copy_transport.stage(
                source_dirs=[],
                test_files=[],
                harness_source=tmp_path,
                extra_files={"/runtime_config.msgpack": b"\x82\xa4wifi\x80"},
            )
            # Verify the staging tree got the binary.
            staging = mp_copy_transport._staging_path
            assert staging is not None
            result_path = staging / "runtime_config.msgpack"
            assert result_path.is_file()
            assert result_path.read_bytes() == b"\x82\xa4wifi\x80"
            # And that mpremote got dispatched (copy mode pushes the tree).
            assert run.called

    def test_mount_mode_lands_extra_files_in_staging(
        self, mp_mount_transport: MicropythonTransport, tmp_path: Path,
    ) -> None:
        # Mount mode opens a persistent serial connection + calls
        # `mount_local`; both are heavy.  Patch `_ensure_serial` to
        # supply a stubbed serial that records the mount call.
        class _SerialStub:
            def __init__(self) -> None:
                self.mount_calls = 0

            def umount_local(self) -> None:
                pass  # No prior mount on a fresh transport.

            def mount_local(self, _path: str) -> None:
                self.mount_calls += 1

        stub = _SerialStub()

        def _ensure_serial() -> None:
            mp_mount_transport._serial = stub  # type: ignore[assignment]

        with patch.object(mp_mount_transport, "_ensure_serial", _ensure_serial):
            mp_mount_transport.stage(
                source_dirs=[],
                test_files=[],
                harness_source=tmp_path,
                extra_files={"/runtime_config.msgpack": b"\x80"},
            )

        staging = mp_mount_transport._staging_path
        assert staging is not None
        assert (staging / "runtime_config.msgpack").read_bytes() == b"\x80"
        assert stub.mount_calls == 1

    def test_nested_extra_file_path_creates_parents(
        self, mp_copy_transport: MicropythonTransport, tmp_path: Path,
    ) -> None:
        with patch.object(mp_copy_transport, "_run_mpremote"):
            mp_copy_transport.stage(
                source_dirs=[],
                test_files=[],
                harness_source=tmp_path,
                extra_files={"/data/cal.bin": b"\xaa\xbb\xcc"},
            )
            staging = mp_copy_transport._staging_path
            assert staging is not None
            assert (staging / "data" / "cal.bin").read_bytes() == b"\xaa\xbb\xcc"

    def test_empty_path_component_raises(
        self, mp_copy_transport: MicropythonTransport, tmp_path: Path,
    ) -> None:
        with patch.object(mp_copy_transport, "_run_mpremote"):
            with pytest.raises(
                MicropythonTransportError, match="no path component",
            ):
                mp_copy_transport.stage(
                    source_dirs=[],
                    test_files=[],
                    harness_source=tmp_path,
                    extra_files={"/": b"x"},
                )

    def test_no_extra_files_does_not_create_unexpected_files(
        self, mp_copy_transport: MicropythonTransport, tmp_path: Path,
    ) -> None:
        with patch.object(mp_copy_transport, "_run_mpremote"):
            mp_copy_transport.stage(
                source_dirs=[],
                test_files=[],
                harness_source=tmp_path,
            )
            staging = mp_copy_transport._staging_path
            assert staging is not None
            # No runtime_config.msgpack lands when caller didn't ask.
            assert not (staging / "runtime_config.msgpack").exists()
