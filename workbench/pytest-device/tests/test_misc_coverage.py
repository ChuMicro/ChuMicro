"""Coverage-closing tests for small device_backend / session / features branches.

Covers the pytest.fail wrappers around transport.clear_entrypoints and
transport.soft_reset, the _session_targets None passthrough, and the
features-marker AST skip for non-feature assignments.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_pytest_device import device_backend, features
from chumicro_pytest_device import plugin as pytest_device
from chumicro_pytest_device.session import _session_targets
from chumicro_pytest_device.testing import FakeSession


class _RaisingTransport:
    """Transport stub whose lifecycle calls raise, to drive the fail wrappers."""

    def __init__(self, error: Exception) -> None:
        self._error = error

    def clear_entrypoints(self) -> None:
        raise self._error

    def soft_reset(self) -> None:
        raise self._error


class TestClearEntrypointsOrFail:
    """Tests for _clear_entrypoints_or_fail's failure wrapper."""

    def test_transport_error_becomes_pytest_fail(self) -> None:
        """A clear_entrypoints error surfaces as a single-line pytest fail."""
        transport = _RaisingTransport(RuntimeError("REPL wedged"))
        with pytest.raises(pytest.fail.Exception, match="clear stale entrypoint"):
            device_backend._clear_entrypoints_or_fail(transport)  # type: ignore[arg-type]


class TestSoftResetOrFail:
    """Tests for _soft_reset_or_fail's failure wrapper."""

    def test_transport_error_names_the_lifecycle_point(self) -> None:
        """A soft_reset error fails with the *when* phrase in the message."""
        transport = _RaisingTransport(RuntimeError("no response"))
        with pytest.raises(pytest.fail.Exception, match="before test file"):
            device_backend._soft_reset_or_fail(
                transport, "before test file (--per-file)",  # type: ignore[arg-type]
            )


class TestSessionTargetsNone:
    """Tests for _session_targets' unset-attribute passthrough."""

    def test_returns_none_when_targets_unset(self, tmp_path: Path) -> None:
        """A session without _device_targets reads back as None, not a raise."""
        session = FakeSession(pytest_device._TransportCache(), rootpath=tmp_path)
        assert _session_targets(session) is None


class TestReadFeaturesMarkerSkipsOtherAssignments:
    """Tests for read_features_marker ignoring non-feature module assignments."""

    def test_unrelated_assignment_does_not_yield_features(
        self, tmp_path: Path,
    ) -> None:
        """A module assigning a different name returns None (no features marker)."""
        test_file = tmp_path / "test_x.py"
        test_file.write_text(
            "__chumicro_runtimes__ = (\"micropython\",)\n"
            "def test_one(): pass\n",
        )
        assert features.read_features_marker(test_file) is None
