"""Tests for flash_drive, the CircuitPython flash-mode USB helpers."""

from __future__ import annotations

import errno
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from chumicro_deploy import flash_drive
from chumicro_deploy.flash_drive import FatVolumeCorruptionError, FlashDriveError


class TestMergePackages:
    """Tests for flash_drive.merge_packages."""

    def test_copies_top_level_packages(self, tmp_path: Path) -> None:
        """Packages with __init__.py are copied into the staging dir."""
        source = tmp_path / "src"
        source.mkdir()
        package = source / "chumicro_example"
        package.mkdir()
        (package / "__init__.py").write_text("# init")
        (package / "core.py").write_text("# core")

        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(source, staging)

        assert (staging / "chumicro_example" / "__init__.py").is_file()
        assert (staging / "chumicro_example" / "core.py").is_file()

    def test_skips_directories_without_init(self, tmp_path: Path) -> None:
        """Directories without __init__.py are skipped."""
        source = tmp_path / "src"
        source.mkdir()
        (source / "notapackage").mkdir()
        (source / "notapackage" / "data.txt").write_text("data")

        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(source, staging)

        assert not (staging / "notapackage").exists()

    def test_skips_missing_source(self, tmp_path: Path) -> None:
        """A nonexistent source directory is silently skipped."""
        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(tmp_path / "missing", staging)
        assert list(staging.iterdir()) == []

    def test_merges_with_existing_staging_content(self, tmp_path: Path) -> None:
        """dirs_exist_ok=True means repeated merges don't fail on collisions."""
        source_a = tmp_path / "src_a"
        source_a.mkdir()
        (source_a / "pkg").mkdir()
        (source_a / "pkg" / "__init__.py").write_text("")
        (source_a / "pkg" / "one.py").write_text("# one")

        source_b = tmp_path / "src_b"
        source_b.mkdir()
        (source_b / "pkg").mkdir()
        (source_b / "pkg" / "__init__.py").write_text("")
        (source_b / "pkg" / "two.py").write_text("# two")

        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(source_a, staging)
        flash_drive.merge_packages(source_b, staging)

        assert (staging / "pkg" / "one.py").is_file()
        assert (staging / "pkg" / "two.py").is_file()

    def test_ignores_pycache(self, tmp_path: Path) -> None:
        """__pycache__ is excluded from the merge."""
        source = tmp_path / "src"
        source.mkdir()
        (source / "pkg").mkdir()
        (source / "pkg" / "__init__.py").write_text("")
        (source / "pkg" / "__pycache__").mkdir()
        (source / "pkg" / "__pycache__" / "cached.pyc").write_text("bytecode")

        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(source, staging)

        assert not (staging / "pkg" / "__pycache__").exists()

    def test_target_runtime_filters_marked_files(self, tmp_path: Path) -> None:
        """Wrong-runtime ``.py`` files are dropped at merge."""
        source = tmp_path / "src"
        source.mkdir()
        package = source / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "shared.py").write_text("# universal\n")
        (package / "cp.py").write_text(
            '__chumicro_runtimes__ = ("circuitpython",)\n',
        )
        (package / "mp.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )

        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(
            source, staging, target_runtime="circuitpython",
        )

        assert (staging / "pkg" / "cp.py").exists()
        assert not (staging / "pkg" / "mp.py").exists()
        # Universal shared.py and __init__.py still ship.
        assert (staging / "pkg" / "shared.py").exists()
        assert (staging / "pkg" / "__init__.py").exists()

    def test_target_runtime_none_preserves_old_behavior(
        self, tmp_path: Path,
    ) -> None:
        source = tmp_path / "src"
        source.mkdir()
        package = source / "pkg"
        package.mkdir()
        (package / "__init__.py").write_text("")
        (package / "mp.py").write_text(
            '__chumicro_runtimes__ = ("micropython",)\n',
        )

        staging = tmp_path / "staging"
        staging.mkdir()
        flash_drive.merge_packages(source, staging)

        assert (staging / "pkg" / "mp.py").exists()


class TestRsync:
    """Tests for flash_drive.rsync."""

    def test_raises_on_failure(self, tmp_path: Path) -> None:
        """rsync failure produces a FlashDriveError."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                1, "rsync", stderr="permission denied",
            ),
        ):
            with pytest.raises(FlashDriveError, match="rsync failed"):
                flash_drive.rsync(source, destination)

    def test_raises_when_not_installed(self, tmp_path: Path) -> None:
        """FileNotFoundError becomes a clear FlashDriveError message."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=FileNotFoundError("rsync"),
        ):
            with pytest.raises(FlashDriveError, match="rsync is required"):
                flash_drive.rsync(source, destination)

    def test_raises_on_timeout_with_recovery_hint(self, tmp_path: Path) -> None:
        """A wedged rsync (TimeoutExpired) raises a clear FlashDriveError.

        Regression guard: without the timeout, a hung USB write on
        CIRCUITPY puts the rsync subprocess into uninterruptible
        kernel I/O wait, and ``kill -9`` is impossible until the board
        is power-cycled.  The error message must point at the
        recovery procedure (board reboot) and reference the learnings
        entry.
        """
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=subprocess.TimeoutExpired(
                cmd="rsync", timeout=flash_drive.RSYNC_TIMEOUT_MIN_SECONDS,
            ),
        ):
            with pytest.raises(FlashDriveError) as exc_info:
                flash_drive.rsync(source, destination)
        message = str(exc_info.value)
        assert "hung past" in message
        assert "Reboot the board" in message
        assert "uninterruptible kernel I/O" in message

    def test_passes_computed_timeout_to_subprocess_run(self, tmp_path: Path) -> None:
        """rsync invocation passes a ``timeout=`` keyword to subprocess.run.

        For an empty staging tree, the auto-computed timeout matches
        :data:`RSYNC_TIMEOUT_MIN_SECONDS` (the floor).  Catches a
        regression where someone refactors the call and drops the
        timeout, leading right back to the wedged-D-state bug.
        """
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        captured_kwargs: dict[str, object] = {}

        def fake_run(_command, **kwargs):
            captured_kwargs.update(kwargs)
            return subprocess.CompletedProcess(args=_command, returncode=0)

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.rsync(source, destination)

        # Empty staging falls to the floor.
        assert (
            captured_kwargs.get("timeout") == flash_drive.RSYNC_TIMEOUT_MIN_SECONDS
        )

    def test_explicit_timeout_overrides_auto_compute(self, tmp_path: Path) -> None:
        """Caller-supplied ``timeout=`` bypasses the auto-compute formula."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        captured_kwargs: dict[str, object] = {}

        def fake_run(_command, **kwargs):
            captured_kwargs.update(kwargs)
            return subprocess.CompletedProcess(args=_command, returncode=0)

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.rsync(source, destination, timeout=42.0)

        assert captured_kwargs.get("timeout") == 42.0

    def test_default_excludes(self, tmp_path: Path) -> None:
        """Default rsync command carries the base exclude set + ``--delete``.

        Build artifacts, macOS file-level detritus, and macOS volume-
        level noise dirs / sentinels are unconditional excludes.  The
        macOS-noise-dir excludes prevent ``rsync --delete`` from
        aborting with ``unlinkat: Operation not permitted`` when the
        kernel locks ``.Trashes/<UID>/`` read-only on a FAT volume.
        User-config filenames (``boot.py``, ``code.py``, etc.) are
        **not** in the base set.  They're caller-supplied via
        ``additional_excludes`` so the production deploy path can
        write a deploy's ``code.py`` entrypoint without hitting an
        exclude rule (see ``test_additional_excludes_flow_through``).
        """
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.rsync(source, destination)

        assert captured
        command = captured[0]
        assert "--delete" in command
        assert "--checksum" in command
        assert "--inplace" in command
        for exclude in (
            "--exclude=__pycache__",
            "--exclude=*.pyc",
            "--exclude=.DS_Store",
            "--exclude=._*",
            # macOS noise dirs (auto-created, kernel-locked).
            "--exclude=.Trashes",
            "--exclude=.Spotlight-V100",
            "--exclude=.TemporaryItems",
            "--exclude=.DocumentRevisions-V100",
            # macOS skip sentinels (we plant, rsync must not delete).
            "--exclude=.fseventsd",
            "--exclude=.metadata_never_index",
        ):
            assert exclude in command
        # User-config filenames are NOT in the base set.
        for caller_supplied in (
            "--exclude=boot.py",
            "--exclude=code.py",
            "--exclude=settings.toml",
        ):
            assert caller_supplied not in command

    def test_delete_false_omits_delete_flag(self, tmp_path: Path) -> None:
        """``delete=False`` (production deploy path) drops ``--delete``."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.rsync(source, destination, delete=False)

        assert captured
        assert "--delete" not in captured[0]
        # Base excludes still in place.  The only divergence is --delete.
        assert "--exclude=__pycache__" in captured[0]
        assert "--exclude=.Trashes" in captured[0]

    def test_additional_excludes_flow_through(self, tmp_path: Path) -> None:
        """``additional_excludes`` are passed through verbatim.

        Clean callers (production deploy and functional-test stage)
        both pass the same closed ``DEVICE_KEEP_SET``, and ``--delete``
        spares exactly that set.  ``code.py`` is **not** excluded, so
        a stale board ``code.py`` is reconciled away on the functional
        path too.  ``settings.toml`` is likewise absent.  It is evicted
        on every path (competing wifi authority).
        """
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.rsync(
                source,
                destination,
                additional_excludes=flash_drive.DEVICE_KEEP_SET,
            )

        for extra in (
            "--exclude=boot.py",
            "--exclude=boot_out.txt",
            "--exclude=_chu_kv.msgpack",
        ):
            assert extra in captured[0]
        # No per-context code.py exclude: a stale board code.py is
        # reconciled away, not preserved.
        assert "--exclude=code.py" not in captured[0]
        # Evicted on every path, never preserved.
        assert "--exclude=settings.toml" not in captured[0]


class TestRsyncCorruptionClassification:
    """Tests for the EINVAL-in-stderr corruption classification.

    ``rsync`` / ``verify_rsync`` run fixed command lines, so an
    ``Invalid argument`` in stderr is the torn-FAT-entry signature
    (macOS renders a failed ``fstatat`` on a torn directory entry
    that way), not a flag problem.
    """

    def test_rsync_invalid_argument_raises_corruption_error(
        self, tmp_path: Path,
    ) -> None:
        """`fstatat: Invalid argument` in rsync stderr raises the
        FatVolumeCorruptionError with the reset-board recovery command.
        """
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                23, "rsync",
                stderr=(
                    'rsync: [sender] link_stat '
                    '"/Volumes/CIRCUITPY/lib/chumicro_config/section.py" '
                    "failed: Invalid argument (22)"
                ),
            ),
        ):
            with pytest.raises(FatVolumeCorruptionError) as exc_info:
                flash_drive.rsync(source, destination)
        message = str(exc_info.value)
        assert "FAT directory entries" in message
        assert "reset-board" in message

    def test_verify_rsync_invalid_argument_raises_corruption_error(
        self, tmp_path: Path,
    ) -> None:
        """The verification dry-run classifies the same EINVAL signature."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                23, "rsync", stderr="rsync: fstatat: Invalid argument",
            ),
        ):
            with pytest.raises(FatVolumeCorruptionError) as exc_info:
                flash_drive.verify_rsync(source, destination)
        assert "reset-board" in str(exc_info.value)

    def test_corruption_error_names_scanned_paths(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The corruption error enumerates the torn entries the
        post-failure stat sweep found and carries them on the
        ``corrupted_paths`` attribute.
        """
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive.scan_for_torn_directory_entries",
            lambda _drive_path: ["lib/chumicro_config/section.py"],
        )

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                23, "rsync", stderr="rsync: fstatat: Invalid argument",
            ),
        ):
            with pytest.raises(FatVolumeCorruptionError) as exc_info:
                flash_drive.rsync(source, destination)
        assert "lib/chumicro_config/section.py" in str(exc_info.value)
        assert exc_info.value.corrupted_paths == (
            "lib/chumicro_config/section.py",
        )

    def test_non_einval_stderr_keeps_generic_error(
        self, tmp_path: Path,
    ) -> None:
        """Other rsync failures still raise the plain FlashDriveError."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                23, "rsync", stderr="No space left on device",
            ),
        ):
            with pytest.raises(FlashDriveError) as exc_info:
                flash_drive.rsync(source, destination)
        assert not isinstance(exc_info.value, FatVolumeCorruptionError)
        assert "rsync failed" in str(exc_info.value)


class _FakeTornDirEntry:
    """``os.DirEntry`` stand-in modeling msdosfs torn-entry behavior.

    A torn FAT directory entry is listed by ``readdir`` (so the entry
    object exists) but every ``stat`` on it fails with the configured
    error, exactly how macOS surfaces the corruption
    (``fstatat: Invalid argument``).  A healthy entry stats cleanly.
    """

    def __init__(
        self,
        path: Path,
        *,
        is_directory: bool = False,
        stat_error: OSError | None = None,
    ) -> None:
        self.path = str(path)
        self.name = path.name
        self._is_directory = is_directory
        self._stat_error = stat_error

    def stat(self, *, follow_symlinks: bool = True) -> object:
        if self._stat_error is not None:
            raise self._stat_error
        return object()

    def is_dir(self, *, follow_symlinks: bool = True) -> bool:
        if self._stat_error is not None:
            raise self._stat_error
        return self._is_directory


def _fake_scandir_for(tree: dict[str, list | OSError]):
    """Build a scandir fake over *tree* (str(dir) -> entries | OSError)."""

    def fake_scandir(directory: Path) -> list:
        listing = tree[str(directory)]
        if isinstance(listing, OSError):
            raise listing
        return listing

    return fake_scandir


class TestScanForTornDirectoryEntries:
    """Tests for flash_drive.scan_for_torn_directory_entries."""

    def test_healthy_tree_returns_empty(self, tmp_path: Path) -> None:
        """A stat-able tree (real os.scandir) reports no torn entries."""
        (tmp_path / "code.py").write_bytes(b"pass")
        nested = tmp_path / "lib" / "pkg"
        nested.mkdir(parents=True)
        (nested / "module.py").write_bytes(b"X = 1")

        assert flash_drive.scan_for_torn_directory_entries(tmp_path) == []

    def test_torn_file_entry_is_reported(self, tmp_path: Path) -> None:
        """An entry whose stat raises EINVAL lands in the report."""
        einval = OSError(errno.EINVAL, "Invalid argument")
        tree = {
            str(tmp_path): [
                _FakeTornDirEntry(tmp_path / "code.py"),
                _FakeTornDirEntry(tmp_path / "broken.py", stat_error=einval),
            ],
        }

        torn = flash_drive.scan_for_torn_directory_entries(
            tmp_path, scandir=_fake_scandir_for(tree),
        )
        assert torn == ["broken.py"]

    def test_nested_torn_entry_reports_relative_path(
        self, tmp_path: Path,
    ) -> None:
        """The walk descends into healthy directories and reports the
        torn entry's volume-relative path.
        """
        einval = OSError(errno.EINVAL, "Invalid argument")
        lib_directory = tmp_path / "lib"
        package_directory = lib_directory / "chumicro_config"
        tree = {
            str(tmp_path): [
                _FakeTornDirEntry(lib_directory, is_directory=True),
            ],
            str(lib_directory): [
                _FakeTornDirEntry(package_directory, is_directory=True),
            ],
            str(package_directory): [
                _FakeTornDirEntry(
                    package_directory / "section.py", stat_error=einval,
                ),
            ],
        }

        torn = flash_drive.scan_for_torn_directory_entries(
            tmp_path, scandir=_fake_scandir_for(tree),
        )
        assert torn == ["lib/chumicro_config/section.py"]

    def test_non_einval_errors_are_skipped(self, tmp_path: Path) -> None:
        """A file deleted mid-walk (ENOENT) is not a torn entry."""
        enoent = OSError(errno.ENOENT, "No such file or directory")
        tree = {
            str(tmp_path): [
                _FakeTornDirEntry(tmp_path / "raced.py", stat_error=enoent),
            ],
        }

        torn = flash_drive.scan_for_torn_directory_entries(
            tmp_path, scandir=_fake_scandir_for(tree),
        )
        assert torn == []

    def test_directory_whose_listing_einvals_is_reported(
        self, tmp_path: Path,
    ) -> None:
        """A directory that stats cleanly but cannot be listed (EINVAL)
        is itself reported as torn.
        """
        einval = OSError(errno.EINVAL, "Invalid argument")
        broken_directory = tmp_path / "lib"
        tree = {
            str(tmp_path): [
                _FakeTornDirEntry(broken_directory, is_directory=True),
            ],
            str(broken_directory): einval,
        }

        torn = flash_drive.scan_for_torn_directory_entries(
            tmp_path, scandir=_fake_scandir_for(tree),
        )
        assert torn == ["lib"]


class TestFormatFatCorruptionError:
    """Tests for flash_drive.format_fat_corruption_error."""

    def test_names_paths_recovery_command_and_classifier_phrase(
        self, tmp_path: Path,
    ) -> None:
        """The message carries the torn paths, the reset-board command,
        and the ``FAT directory entries`` phrase the recovery
        classifier matches on.
        """
        message = flash_drive.format_fat_corruption_error(
            tmp_path,
            ["lib/chumicro_config/section.py", "lib/chumicro_mqtt/_wire.py"],
            detail="rsync: fstatat: Invalid argument",
        )
        assert "FAT directory entries" in message
        assert "lib/chumicro_config/section.py" in message
        assert "lib/chumicro_mqtt/_wire.py" in message
        assert "rsync: fstatat: Invalid argument" in message
        assert "chumicro-workspace reset-board --device <id> --yes" in message

    def test_empty_path_list_still_actionable(self, tmp_path: Path) -> None:
        """No enumerable paths (stderr-only detection) still yields the
        recovery command and the classifier phrase.
        """
        message = flash_drive.format_fat_corruption_error(tmp_path, [])
        assert "FAT directory entries" in message
        assert "reset-board" in message


class TestVerifyRsync:
    """Tests for flash_drive.verify_rsync."""

    def test_returns_empty_on_clean_match(self, tmp_path: Path) -> None:
        """Identical source + destination produces an empty needs-update list."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "code.py").write_bytes(b"print('hi')\n")
        destination = tmp_path / "destination"
        destination.mkdir()
        (destination / "code.py").write_bytes(b"print('hi')\n")

        divergent = flash_drive.verify_rsync(source, destination)
        assert divergent == []

    def test_returns_paths_on_content_divergence(self, tmp_path: Path) -> None:
        """Content mismatch puts the path in the needs-update list."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "code.py").write_bytes(b"print('hi')\n")
        destination = tmp_path / "destination"
        destination.mkdir()
        (destination / "code.py").write_bytes(b"corrupted\n")

        divergent = flash_drive.verify_rsync(source, destination)
        assert "code.py" in divergent

    def test_returns_paths_on_missing_destination_file(
        self, tmp_path: Path,
    ) -> None:
        """File present in source, absent from destination, gets flagged."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "code.py").write_bytes(b"x")
        destination = tmp_path / "destination"
        destination.mkdir()

        divergent = flash_drive.verify_rsync(source, destination)
        assert "code.py" in divergent

    def test_ignores_cosmetic_time_differences(self, tmp_path: Path) -> None:
        """Time-only diffs (rsync ``T`` flag) do NOT trigger a divergence.

        FAT32 stores mtime at 2-second granularity, so post-rsync the
        destination's mtime can differ from the source even when content
        matches byte-for-byte.  The verification must filter on the
        update-marker (position 1) rather than per-attribute flags so
        the harmless time delta does not fail every deploy.
        """
        import os

        source = tmp_path / "source"
        source.mkdir()
        source_file = source / "code.py"
        source_file.write_bytes(b"identical\n")
        destination = tmp_path / "destination"
        destination.mkdir()
        destination_file = destination / "code.py"
        destination_file.write_bytes(b"identical\n")
        os.utime(destination_file, (0, 0))

        divergent = flash_drive.verify_rsync(source, destination)
        assert divergent == []

    def test_raises_when_rsync_missing(self, tmp_path: Path) -> None:
        """FileNotFoundError surfaces as a clear FlashDriveError."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=FileNotFoundError("rsync"),
        ):
            with pytest.raises(FlashDriveError, match="required for verification"):
                flash_drive.verify_rsync(source, destination)

    def test_raises_on_subprocess_error(self, tmp_path: Path) -> None:
        """A non-zero rsync exit surfaces as FlashDriveError with stderr."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=subprocess.CalledProcessError(
                23, "rsync", stderr="permission denied",
            ),
        ):
            with pytest.raises(FlashDriveError, match="verification failed"):
                flash_drive.verify_rsync(source, destination)

    def test_raises_with_recovery_hint_on_timeout(self, tmp_path: Path) -> None:
        """A wedged verify rsync points at the RESET-and-replay recovery."""
        source = tmp_path / "source"
        source.mkdir()
        destination = tmp_path / "destination"
        destination.mkdir()

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="rsync", timeout=30.0),
        ):
            with pytest.raises(FlashDriveError) as exc_info:
                flash_drive.verify_rsync(source, destination)
        assert "Tap RESET" in str(exc_info.value)


class TestMacOSHelpers:
    """Tests for strip_extended_attributes / clean_dot_files / disable_spotlight_indexing."""

    def test_strip_extended_attributes_calls_xattr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On macOS, strip_extended_attributes runs `xattr -cr <path>`."""
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.strip_extended_attributes(tmp_path)

        assert ["xattr", "-cr", str(tmp_path)] in captured

    def test_strip_extended_attributes_tolerates_missing_xattr(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing xattr binary is a warning, not a raise."""
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=FileNotFoundError("xattr"),
        ):
            flash_drive.strip_extended_attributes(tmp_path)  # must not raise

    def test_clean_dot_files_calls_dot_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On macOS, clean_dot_files runs dot_clean on the drive path."""
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.clean_dot_files(tmp_path)

        assert ["dot_clean", str(tmp_path)] in captured

    def test_clean_dot_files_tolerates_missing_dot_clean(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Missing dot_clean binary does not raise."""
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=FileNotFoundError("dot_clean"),
        ):
            flash_drive.clean_dot_files(tmp_path)  # must not raise


class TestPlantMacosSentinelsInStaging:
    """Tests for flash_drive.plant_macos_sentinels_in_staging.

    The new shape (post-wedge cleanup): sentinels go into a local
    staging tree so rsync ships them in the same pass as the deploy
    payload, with no host-side write to the live CIRCUITPY drive
    before rsync starts.  Direct writes to a live CIRCUITPY drive
    while a parallel rsync is mid-flight could leave rsync hung in
    uninterruptible kernel I/O on macOS FSKit.
    """

    def test_no_op_off_darwin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Linux / Windows runs are a no-op.  The sentinels target
        macOS-specific daemons.
        """
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "linux",
        )
        flash_drive.plant_macos_sentinels_in_staging(tmp_path)
        assert list(tmp_path.iterdir()) == []

    def test_plants_three_sentinels_on_darwin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Spotlight + FSEvents + Trash skip sentinels land in the staging root."""
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        flash_drive.plant_macos_sentinels_in_staging(tmp_path)

        assert (tmp_path / ".metadata_never_index").is_file()
        assert (tmp_path / ".fseventsd" / "no_log").is_file()
        # ``.Trashes`` is planted as a *file* so macOS cannot create
        # the protected ``.Trashes/<UID>/`` directory the kernel
        # otherwise locks down with read-only perms.
        assert (tmp_path / ".Trashes").is_file()


class TestCleanupMacosNoiseDirsPostRsync:
    """Tests for flash_drive.cleanup_macos_noise_dirs_post_rsync."""

    def test_no_op_off_darwin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "linux",
        )
        # Even if a noise dir exists (it shouldn't on Linux), no-op.
        (tmp_path / ".Spotlight-V100").mkdir()
        flash_drive.cleanup_macos_noise_dirs_post_rsync(tmp_path)
        assert (tmp_path / ".Spotlight-V100").exists()

    def test_removes_legacy_noise_directories(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``.Spotlight-V100`` / ``.TemporaryItems`` / ``.DocumentRevisions-V100``
        get rmtree'd.  ``.Trashes`` is intentionally NOT in the rmtree
        set.  Once macOS created ``.Trashes/<UID>/`` the kernel sets it
        read-only and even ``shutil.rmtree`` cannot remove it.
        Prevention via the file sentinel
        (:func:`plant_macos_sentinels_in_staging`) is the only working
        strategy for that one.
        """
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        for noise_relative in (
            ".Spotlight-V100", ".TemporaryItems", ".DocumentRevisions-V100",
        ):
            noise_dir = tmp_path / noise_relative
            noise_dir.mkdir()
            (noise_dir / "data").write_bytes(b"junk")

        flash_drive.cleanup_macos_noise_dirs_post_rsync(tmp_path)

        assert not (tmp_path / ".Spotlight-V100").exists()
        assert not (tmp_path / ".TemporaryItems").exists()
        assert not (tmp_path / ".DocumentRevisions-V100").exists()

    def test_idempotent_when_dirs_absent(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Common case (sentinels already prevent re-creation): no-op."""
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        flash_drive.cleanup_macos_noise_dirs_post_rsync(tmp_path)  # must not raise
        assert list(tmp_path.iterdir()) == []


class TestFlushVolume:
    """Tests for flash_drive.flush_volume."""

    def test_calls_sync_on_darwin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On macOS, flush_volume runs the `sync` command."""
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        captured: list[list[str]] = []

        def fake_run(command, **kwargs):
            captured.append(command)
            return subprocess.CompletedProcess(args=command, returncode=0)

        sleep_calls: list[float] = []
        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.flush_volume(tmp_path, sleep=sleep_calls.append)

        assert ["sync"] in captured

    def test_routes_settle_delay_through_injected_sleep(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The settle delay is applied via the injected sleep callable.

        Constructor-injected sleep lets flash-mode tests skip the
        real 0.5 s settle delay.
        """
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        sleep_durations: list[float] = []

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=lambda command, **kwargs: subprocess.CompletedProcess(
                args=command, returncode=0,
            ),
        ):
            flash_drive.flush_volume(tmp_path, sleep=sleep_durations.append)

        assert sleep_durations == [flash_drive.FLUSH_SETTLE_DELAY]

    def test_honors_custom_settle_delay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Callers can override the settle delay per-invocation."""
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        sleep_durations: list[float] = []

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=lambda command, **kwargs: subprocess.CompletedProcess(
                args=command, returncode=0,
            ),
        ):
            flash_drive.flush_volume(
                tmp_path,
                sleep=sleep_durations.append,
                settle_delay=0.123,
            )

        assert sleep_durations == [0.123]

    def test_full_fsync_barrier_on_darwin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On macOS, flush_volume issues F_FULLFSYNC on the mount point.

        ``sync`` alone only schedules the flush (``sync(2)`` may return
        before the buffers are written); the F_FULLFSYNC barrier is
        what guarantees no dirty FAT metadata is outstanding when a
        board reset lands.
        """
        import fcntl

        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        fcntl_calls: list[int] = []

        def recording_fcntl(descriptor: int, command: int, *args: object) -> int:
            fcntl_calls.append(command)
            return 0

        monkeypatch.setattr("fcntl.fcntl", recording_fcntl)
        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=lambda command, **kwargs: subprocess.CompletedProcess(
                args=command, returncode=0,
            ),
        ):
            flash_drive.flush_volume(tmp_path, sleep=lambda _seconds: None)

        assert fcntl_calls == [fcntl.F_FULLFSYNC]

    def test_full_fsync_falls_back_to_fsync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A filesystem without F_FULLFSYNC support falls back to os.fsync."""
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )

        def unsupported_fcntl(
            descriptor: int, command: int, *args: object,
        ) -> int:
            raise OSError(errno.EINVAL, "F_FULLFSYNC unsupported")

        monkeypatch.setattr("fcntl.fcntl", unsupported_fcntl)
        fsync_descriptors: list[int] = []
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive.os.fsync",
            fsync_descriptors.append,
        )
        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=lambda command, **kwargs: subprocess.CompletedProcess(
                args=command, returncode=0,
            ),
        ):
            flash_drive.flush_volume(tmp_path, sleep=lambda _seconds: None)

        assert len(fsync_descriptors) == 1

    def test_unopenable_drive_path_warns_and_continues(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A mount that vanished before the barrier degrades to
        sync + settle with a warning instead of failing the deploy.
        """
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        sleep_durations: list[float] = []
        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=lambda command, **kwargs: subprocess.CompletedProcess(
                args=command, returncode=0,
            ),
        ):
            flash_drive.flush_volume(
                tmp_path / "GONE", sleep=sleep_durations.append,
            )

        assert sleep_durations == [flash_drive.FLUSH_SETTLE_DELAY]
        assert "full flush" in capsys.readouterr().out


class TestMetadataHelpersHaveTimeouts:
    """Regression: every CIRCUITPY-touching subprocess call passes a
    ``timeout=`` kwarg.  Sister of TestRsync.test_passes_timeout: these
    are smaller helpers but a wedged USB stack hangs them too.
    """

    def test_strip_extended_attributes_passes_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        captured_kwargs: dict[str, object] = {}

        def fake_run(_command, **kwargs):
            captured_kwargs.update(kwargs)
            return subprocess.CompletedProcess(args=_command, returncode=0)

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.strip_extended_attributes(tmp_path)
        assert (
            captured_kwargs.get("timeout")
            == flash_drive.METADATA_HELPER_TIMEOUT_SECONDS
        )

    def test_clean_dot_files_passes_timeout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        captured_kwargs: dict[str, object] = {}

        def fake_run(_command, **kwargs):
            captured_kwargs.update(kwargs)
            return subprocess.CompletedProcess(args=_command, returncode=0)

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.clean_dot_files(tmp_path)
        assert (
            captured_kwargs.get("timeout")
            == flash_drive.METADATA_HELPER_TIMEOUT_SECONDS
        )

    def test_flush_volume_passes_timeout_to_sync(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            "chumicro_deploy.flash_drive._sys_module.platform",
            "darwin",
        )
        captured_kwargs: dict[str, object] = {}

        def fake_run(_command, **kwargs):
            captured_kwargs.update(kwargs)
            return subprocess.CompletedProcess(args=_command, returncode=0)

        with patch(
            "chumicro_deploy.flash_drive.subprocess.run",
            side_effect=fake_run,
        ):
            flash_drive.flush_volume(tmp_path, sleep=lambda _seconds: None)
        assert (
            captured_kwargs.get("timeout") == flash_drive.SYNC_TIMEOUT_SECONDS
        )


class TestComputeRsyncTimeoutSeconds:
    """Tests for the size-based timeout scaling formula.

    Replaces the old fixed 90-second timeout that fired false-positives
    on slow boards (Lolin S2 / ESP32-S2 CP).  Per-MB scaling lets the
    timeout grow with the deploy payload while still bounding the
    "actually wedged" case via the floor.
    """

    def test_zero_size_returns_floor(self) -> None:
        """Empty staging -> RSYNC_TIMEOUT_MIN_SECONDS (the floor)."""
        assert (
            flash_drive.compute_rsync_timeout_seconds(0)
            == flash_drive.RSYNC_TIMEOUT_MIN_SECONDS
        )

    def test_small_size_below_breakeven_returns_floor(self) -> None:
        """Size where (base + per-MB * size) < floor -> floor.

        With base=60s and per-MB=120s, 250 KB gives 60+30 = 90s,
        exactly the 90s floor.  Anything smaller stays at the floor.
        """
        # 100 KB -> 60 + 0.1 * 120 = 72s, capped at 90s.
        result = flash_drive.compute_rsync_timeout_seconds(100 * 1024)
        assert result == flash_drive.RSYNC_TIMEOUT_MIN_SECONDS

    def test_large_size_scales_above_floor(self) -> None:
        """Big staging -> base + per-MB * size, NOT capped at floor."""
        # 1 MB -> 60 + 1.0 * 120 = 180s.
        one_mb = 1024 * 1024
        result = flash_drive.compute_rsync_timeout_seconds(one_mb)
        expected = (
            flash_drive.RSYNC_TIMEOUT_BASE_SECONDS
            + 1.0 * flash_drive.RSYNC_TIMEOUT_PER_MB_SECONDS
        )
        assert result == expected
        assert result > flash_drive.RSYNC_TIMEOUT_MIN_SECONDS

    def test_per_mb_scaling_is_linear(self) -> None:
        """Doubling the size doubles the per-MB term (base stays fixed)."""
        one_mb = 1024 * 1024
        two_mb = 2 * one_mb
        single = flash_drive.compute_rsync_timeout_seconds(one_mb)
        double = flash_drive.compute_rsync_timeout_seconds(two_mb)
        # The DELTA is per_mb_seconds * 1 MB.
        assert (
            double - single == flash_drive.RSYNC_TIMEOUT_PER_MB_SECONDS
        )


class TestDirectorySizeBytes:
    """Tests for the staging-tree size-measurement helper."""

    def test_empty_directory_returns_zero(self, tmp_path: Path) -> None:
        assert flash_drive._directory_size_bytes(tmp_path) == 0

    def test_nonexistent_directory_returns_zero(self, tmp_path: Path) -> None:
        assert (
            flash_drive._directory_size_bytes(tmp_path / "missing") == 0
        )

    def test_sums_file_sizes_recursively(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_bytes(b"x" * 100)
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.txt").write_bytes(b"y" * 250)
        (tmp_path / "sub" / "nested").mkdir()
        (tmp_path / "sub" / "nested" / "c.bin").write_bytes(b"z" * 50)

        assert flash_drive._directory_size_bytes(tmp_path) == 400
