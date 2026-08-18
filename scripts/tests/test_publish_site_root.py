"""Tests for publish_site_root.py, the host-root site publish.

The publish rebuilds the site repository's whole tree, so the tests
that matter are about what a rebuild removes: a file the generator no
longer writes has to disappear, or a retired IndexNow key would keep
answering after its replacement shipped.
"""

import subprocess
from pathlib import Path

import pytest
from publish_site_root import publish


@pytest.fixture
def clone_dir(tmp_path: Path) -> Path:
    """Return an initialized git repository standing in for the site clone."""
    directory = tmp_path / "site-repo"
    directory.mkdir()
    for command in (
        ["git", "init", "-q", "-b", "main"],
        ["git", "config", "user.email", "test@example.com"],
        ["git", "config", "user.name", "Test"],
    ):
        subprocess.run(command, cwd=directory, check=True)
    (directory / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=directory, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=directory, check=True)
    return directory


def test_publish_writes_the_generated_site(clone_dir: Path):
    """A publish leaves the site files in the clone."""
    assert publish(clone_dir, push=False, message="Rebuild") == 0

    assert (clone_dir / "index.html").is_file()
    assert (clone_dir / "robots.txt").is_file()
    assert (clone_dir / ".nojekyll").is_file()


def test_publish_removes_a_file_the_generator_no_longer_writes(clone_dir: Path):
    """A retired IndexNow key has to stop answering."""
    (clone_dir / "stale-key.txt").write_text("stale\n")
    subprocess.run(["git", "add", "-A"], cwd=clone_dir, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "stale"], cwd=clone_dir, check=True)

    assert publish(clone_dir, push=False, message="Rebuild") == 0
    assert not (clone_dir / "stale-key.txt").exists()


def test_publish_keeps_the_git_directory(clone_dir: Path):
    """Clearing the tree must not take the history with it."""
    assert publish(clone_dir, push=False, message="Rebuild") == 0
    assert (clone_dir / ".git").is_dir()


def test_publish_is_a_no_op_when_nothing_changed(clone_dir: Path, capsys):
    """A second publish with no source change adds no commit."""
    publish(clone_dir, push=False, message="Rebuild")
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=clone_dir,
        check=True, capture_output=True, text=True,
    ).stdout

    assert publish(clone_dir, push=False, message="Rebuild") == 0
    after = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=clone_dir,
        check=True, capture_output=True, text=True,
    ).stdout

    assert before == after
    assert "unchanged" in capsys.readouterr().out


def test_publish_refuses_a_directory_that_is_not_a_clone(tmp_path: Path):
    """Rebuilding a stray directory would delete whatever was in it."""
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "keep.txt").write_text("keep\n")

    assert publish(plain, push=False, message="Rebuild") == 1
    assert (plain / "keep.txt").is_file()
