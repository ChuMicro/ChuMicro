"""Tests for DeployResult and DeployError."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from chumicro_deploy import DeployError, DeployResult


class TestDeployError:
    def test_is_exception(self):
        assert issubclass(DeployError, Exception)

    def test_raisable_with_message(self):
        with pytest.raises(DeployError, match="boom"):
            raise DeployError("boom")


class TestDeployResult:
    def test_minimum_success(self):
        result = DeployResult(success=True)
        assert result.success is True
        assert result.staged_files == []
        assert result.execute_output == ""
        assert result.traceback is None

    def test_failure_with_traceback(self):
        result = DeployResult(
            success=False,
            staged_files=["/lib/app.py"],
            execute_output="Traceback ...\nZeroDivisionError",
            traceback="ZeroDivisionError: division by zero",
        )
        assert result.success is False
        assert result.staged_files == ["/lib/app.py"]
        assert "ZeroDivisionError" in result.traceback  # type: ignore[operator]

    def test_frozen(self):
        result = DeployResult(success=True)
        with pytest.raises(FrozenInstanceError):
            result.success = False  # type: ignore[misc]

    def test_each_instance_gets_own_list(self):
        one = DeployResult(success=True)
        two = DeployResult(success=True)
        one.staged_files.append("x")
        assert two.staged_files == []
