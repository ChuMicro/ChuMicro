"""Tests for docs_deploy_retry.py — gh-pages deploy with retry-on-conflict."""

from __future__ import annotations

from pathlib import Path

import docs_deploy_retry
import pytest


@pytest.fixture(autouse=True)
def stub_index_now(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Record the IndexNow ping instead of sending it.

    ``deploy_with_retry`` pings after a successful push, so without
    this every test in the module would reach the network.
    """
    pings: list[bool] = []
    monkeypatch.setattr(
        docs_deploy_retry.index_now, "ping", lambda: pings.append(True) or True,
    )
    return pings


class TestDeployWithRetry:
    """Tests for deploy_with_retry."""

    def test_successful_push_pings_index_now(
        self, monkeypatch: pytest.MonkeyPatch, stub_index_now: list[bool],
    ) -> None:
        """The engines that read IndexNow hear about the new pages."""
        monkeypatch.setattr(docs_deploy_retry, "_run", lambda *args, **kwargs: 0)
        monkeypatch.setattr(docs_deploy_retry, "_fetch_gh_pages", lambda: None)

        docs_deploy_retry.deploy_with_retry(
            channel="stable", libraries=None, max_attempts=3, retry_delay=0,
        )

        assert stub_index_now == [True]

    def test_failed_deploy_pings_nothing(
        self, monkeypatch: pytest.MonkeyPatch, stub_index_now: list[bool],
    ) -> None:
        """Nothing was published, so there is nothing to announce."""
        monkeypatch.setattr(docs_deploy_retry, "_run", lambda *args, **kwargs: 1)
        monkeypatch.setattr(docs_deploy_retry, "_fetch_gh_pages", lambda: None)

        docs_deploy_retry.deploy_with_retry(
            channel="stable", libraries=None, max_attempts=1, retry_delay=0,
        )

        assert stub_index_now == []

    def test_succeeds_on_first_attempt(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ) -> None:
        """Successful deploy + push → return 0 after one attempt."""
        calls: list[list[str]] = []

        def fake_run(command: list[str], cwd: Path = docs_deploy_retry.ROOT) -> int:
            calls.append(command)
            return 0

        monkeypatch.setattr(docs_deploy_retry, "_run", fake_run)
        monkeypatch.setattr(docs_deploy_retry, "_fetch_gh_pages", lambda: None)

        result = docs_deploy_retry.deploy_with_retry(
            channel="stable", libraries="timing",
            max_attempts=3, retry_delay=0,
        )

        assert result == 0
        # docs-deploy + git push, in that order, exactly once.
        deploy_calls = [call for call in calls if "docs-deploy" in call]
        push_calls = [call for call in calls if call[:3] == ["git", "push", "origin"]]
        assert len(deploy_calls) == 1
        assert len(push_calls) == 1

    def test_retries_on_push_conflict(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failing push retries; the next successful push returns 0."""
        push_attempts = {"count": 0}

        def fake_run(command: list[str], cwd: Path = docs_deploy_retry.ROOT) -> int:
            if command[:3] == ["git", "push", "origin"]:
                push_attempts["count"] += 1
                return 0 if push_attempts["count"] >= 2 else 1
            return 0

        monkeypatch.setattr(docs_deploy_retry, "_run", fake_run)
        monkeypatch.setattr(docs_deploy_retry, "_fetch_gh_pages", lambda: None)

        result = docs_deploy_retry.deploy_with_retry(
            channel="stable", libraries="timing",
            max_attempts=3, retry_delay=0,
        )

        assert result == 0
        assert push_attempts["count"] == 2

    def test_returns_nonzero_after_exhausting_retries(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
    ) -> None:
        """Every push fails → return 1 after max_attempts."""
        push_attempts = {"count": 0}

        def fake_run(command: list[str], cwd: Path = docs_deploy_retry.ROOT) -> int:
            if command[:3] == ["git", "push", "origin"]:
                push_attempts["count"] += 1
                return 1
            return 0

        monkeypatch.setattr(docs_deploy_retry, "_run", fake_run)
        monkeypatch.setattr(docs_deploy_retry, "_fetch_gh_pages", lambda: None)

        result = docs_deploy_retry.deploy_with_retry(
            channel="stable", libraries="timing",
            max_attempts=2, retry_delay=0,
        )

        assert result == 1
        assert push_attempts["count"] == 2
        assert "Failed to deploy" in capsys.readouterr().out

    def test_returns_deploy_failure_code(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A failing docs-deploy short-circuits (no retry)."""
        def fake_run(command: list[str], cwd: Path = docs_deploy_retry.ROOT) -> int:
            if "docs-deploy" in command:
                return 5
            return 0

        monkeypatch.setattr(docs_deploy_retry, "_run", fake_run)
        monkeypatch.setattr(docs_deploy_retry, "_fetch_gh_pages", lambda: None)

        result = docs_deploy_retry.deploy_with_retry(
            channel="stable", libraries="timing",
            max_attempts=3, retry_delay=0,
        )

        assert result == 5

    def test_omits_libraries_flag_when_empty(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """An empty libraries arg leaves --libraries off the deploy command."""
        recorded: list[list[str]] = []

        def fake_run(command: list[str], cwd: Path = docs_deploy_retry.ROOT) -> int:
            recorded.append(command)
            return 0

        monkeypatch.setattr(docs_deploy_retry, "_run", fake_run)
        monkeypatch.setattr(docs_deploy_retry, "_fetch_gh_pages", lambda: None)

        docs_deploy_retry.deploy_with_retry(
            channel="experimental", libraries=None,
            max_attempts=1, retry_delay=0,
        )

        deploy_calls = [call for call in recorded if "docs-deploy" in call]
        assert deploy_calls
        assert "--libraries" not in deploy_calls[0]


class TestMain:
    """Tests for the CLI entry point."""

    def test_dispatches_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """CLI flags flow into deploy_with_retry."""
        captured: dict[str, object] = {}

        def fake_deploy(
            channel: str, libraries: str | None,
            max_attempts: int, retry_delay: float,
        ) -> int:
            captured["channel"] = channel
            captured["libraries"] = libraries
            captured["max_attempts"] = max_attempts
            captured["retry_delay"] = retry_delay
            return 0

        monkeypatch.setattr(docs_deploy_retry, "deploy_with_retry", fake_deploy)

        result = docs_deploy_retry.main([
            "--channel", "stable",
            "--libraries", "timing",
            "--max-attempts", "5",
            "--retry-delay", "0.5",
        ])

        assert result == 0
        assert captured == {
            "channel": "stable",
            "libraries": "timing",
            "max_attempts": 5,
            "retry_delay": 0.5,
        }
