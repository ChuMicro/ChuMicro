"""Host-platform compatibility checks for chumicro-deploy.

The deploy package targets developer laptops: fully supported on
macOS, fully viable on Linux, and explicitly unsupported on native
Windows.  This module surfaces those gaps as fast-failing errors with
actionable remediation hints rather than letting them manifest as
``no devices found`` deep inside the deploy flow.

Two checks live here:

- :func:`check_supported_platform`, called before any path that
  enumerates serial ports or USB mount points, so Windows users see
  a "use WSL2" message immediately instead of an empty-port-list dead
  end.
- :func:`check_rsync_available`, called before flash-mode deploy.  The
  CircuitPython flash transport shells out to ``rsync`` and there is
  no fallback (FAT32 timestamp semantics make ``shutil.copytree``
  unreliable for incremental writes).  Detecting absence up-front
  beats failing partway through staging.
"""

from __future__ import annotations

import shutil
import sys

#: Guidance shown when the deploy package is invoked on native
#: Windows.  Surfaced verbatim in :class:`WindowsNotSupportedError`.
_WINDOWS_GUIDANCE = (
    "chumicro-deploy is not supported on native Windows.  The deploy "
    "code targets POSIX serial-port (/dev/cu.*, /dev/ttyACM*) and "
    "USB-mount (/Volumes, /media/<user>) paths that native Windows "
    "does not expose.  Use WSL2 from Windows, or run from macOS or "
    "Linux."
)


class WindowsNotSupportedError(RuntimeError):
    """Raised when chumicro-deploy is invoked on native Windows."""


class RsyncMissingError(RuntimeError):
    """Raised when ``rsync`` is required for flash-mode deploy but
    is not on PATH."""


def is_native_windows() -> bool:
    """Return ``True`` on native Windows (``win32`` / ``cygwin``).

    WSL2 reports ``sys.platform == "linux"`` and is treated as Linux
    throughout the deploy code, which is correct since the POSIX
    paths work inside WSL2.
    """
    return sys.platform.startswith("win") or sys.platform == "cygwin"


def check_supported_platform() -> None:
    """Raise :class:`WindowsNotSupportedError` on native Windows.

    Call before any path that enumerates serial ports or USB mount
    points, so users see one clean error before the deploy flow tries
    to walk POSIX-only paths.  No-op on macOS, Linux, and WSL2.
    """
    if is_native_windows():
        raise WindowsNotSupportedError(_WINDOWS_GUIDANCE)


def install_hint_for_rsync() -> str:
    """Return a platform-specific install command for ``rsync``.

    Detects common Linux package managers via :func:`shutil.which`
    and produces a copy-paste-able ``sudo <manager> install rsync``
    line.  Falls back to a generic message when no recognized
    manager is on PATH.  On macOS the system ships rsync, so the
    hint points at Xcode Command Line Tools / Homebrew as the
    recovery path.
    """
    platform = sys.platform
    if platform == "darwin":
        return (
            "rsync ships with macOS.  If it is missing, reinstall the "
            "Xcode Command Line Tools (`xcode-select --install`) or "
            "`brew install rsync`."
        )
    if platform.startswith("linux"):
        if shutil.which("apt-get") is not None:
            return "Install with: `sudo apt-get install -y rsync`"
        if shutil.which("dnf") is not None:
            return "Install with: `sudo dnf install -y rsync`"
        if shutil.which("pacman") is not None:
            return "Install with: `sudo pacman -S --noconfirm rsync`"
        if shutil.which("apk") is not None:
            return "Install with: `sudo apk add rsync`"
        if shutil.which("zypper") is not None:
            return "Install with: `sudo zypper install -y rsync`"
        return "Install rsync via your distribution's package manager."
    return "Install rsync and ensure it is on your PATH."


def check_rsync_available() -> None:
    """Raise :class:`RsyncMissingError` if ``rsync`` is not on PATH.

    Call before a CircuitPython flash-mode deploy so a missing rsync
    surfaces as one clear error before the transport opens a serial
    connection and starts staging.  The error embeds the install hint
    from :func:`install_hint_for_rsync`.
    """
    if shutil.which("rsync") is None:
        raise RsyncMissingError(
            "rsync is required for CircuitPython flash-mode deploy but "
            f"was not found on PATH.  {install_hint_for_rsync()}"
        )
