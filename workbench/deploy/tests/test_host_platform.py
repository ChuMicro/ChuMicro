"""Tests for chumicro_deploy.host_platform."""

from __future__ import annotations

import pytest
from chumicro_deploy import host_platform
from chumicro_deploy.host_platform import (
    RsyncMissingError,
    WindowsNotSupportedError,
    check_rsync_available,
    check_supported_platform,
    install_hint_for_rsync,
    is_native_windows,
)


class TestIsNativeWindows:
    """is_native_windows() detects native Windows variants."""

    def test_returns_false_on_linux(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")
        assert is_native_windows() is False

    def test_returns_false_on_darwin(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "darwin")
        assert is_native_windows() is False

    def test_returns_true_on_win32(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "win32")
        assert is_native_windows() is True

    def test_returns_true_on_cygwin(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "cygwin")
        assert is_native_windows() is True


class TestCheckSupportedPlatform:
    """check_supported_platform() raises only on native Windows."""

    def test_no_op_on_linux(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")
        check_supported_platform()  # must not raise

    def test_no_op_on_darwin(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "darwin")
        check_supported_platform()  # must not raise

    def test_raises_on_win32(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "win32")
        with pytest.raises(WindowsNotSupportedError, match="WSL2"):
            check_supported_platform()

    def test_raises_on_cygwin(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "cygwin")
        with pytest.raises(WindowsNotSupportedError):
            check_supported_platform()


class TestInstallHintForRsync:
    """install_hint_for_rsync() adapts to the host's package manager."""

    def test_macos_points_at_xcode_or_brew(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "darwin")
        hint = install_hint_for_rsync()
        assert "xcode-select" in hint or "brew" in hint

    def test_linux_apt_get(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")
        monkeypatch.setattr(
            host_platform.shutil,
            "which",
            lambda name: "/usr/bin/apt-get" if name == "apt-get" else None,
        )
        assert "apt-get install" in install_hint_for_rsync()

    def test_linux_dnf(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")
        monkeypatch.setattr(
            host_platform.shutil,
            "which",
            lambda name: "/usr/bin/dnf" if name == "dnf" else None,
        )
        assert "dnf install" in install_hint_for_rsync()

    def test_linux_pacman(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")
        monkeypatch.setattr(
            host_platform.shutil,
            "which",
            lambda name: "/usr/bin/pacman" if name == "pacman" else None,
        )
        assert "pacman" in install_hint_for_rsync()

    def test_linux_apk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")
        monkeypatch.setattr(
            host_platform.shutil,
            "which",
            lambda name: "/sbin/apk" if name == "apk" else None,
        )
        assert "apk add" in install_hint_for_rsync()

    def test_linux_zypper(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")
        monkeypatch.setattr(
            host_platform.shutil,
            "which",
            lambda name: "/usr/bin/zypper" if name == "zypper" else None,
        )
        assert "zypper install" in install_hint_for_rsync()

    def test_linux_no_known_manager(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")
        monkeypatch.setattr(host_platform.shutil, "which", lambda _name: None)
        hint = install_hint_for_rsync()
        assert "package manager" in hint

    def test_unknown_platform_falls_back(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "freebsd")
        hint = install_hint_for_rsync()
        assert "PATH" in hint


class TestCheckRsyncAvailable:
    """check_rsync_available() raises when rsync is missing."""

    def test_no_op_when_rsync_present(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(
            host_platform.shutil,
            "which",
            lambda name: "/usr/bin/rsync" if name == "rsync" else None,
        )
        check_rsync_available()  # must not raise

    def test_raises_with_install_hint_when_missing(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")
        monkeypatch.setattr(host_platform.shutil, "which", lambda _name: None)
        with pytest.raises(RsyncMissingError, match="rsync is required"):
            check_rsync_available()

    def test_error_embeds_platform_specific_hint(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(host_platform.sys, "platform", "linux")

        def fake_which(name: str) -> str | None:
            if name == "rsync":
                return None
            if name == "apt-get":
                return "/usr/bin/apt-get"
            return None

        monkeypatch.setattr(host_platform.shutil, "which", fake_which)
        with pytest.raises(RsyncMissingError, match="apt-get install"):
            check_rsync_available()


class TestPublicSurface:
    """The exception types are exposed on the package root."""

    def test_windows_error_importable_from_root(self) -> None:
        from chumicro_deploy import WindowsNotSupportedError as Exported

        assert Exported is WindowsNotSupportedError

    def test_rsync_error_importable_from_root(self) -> None:
        from chumicro_deploy import RsyncMissingError as Exported

        assert Exported is RsyncMissingError
