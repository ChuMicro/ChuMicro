"""Tests for check_version.py — VERSION enforcement logic.

Every test monkeypatches ``check_version.{changed_files,read_version,
release_tags}`` so the gate runs against a synthetic snapshot of the
workspace.  No test reads the real on-disk ``VERSION`` of any real
package — that would couple test outcomes to whichever package
happened to sit at the pre-release floor or above it on the day the
test was written.  The ``_synthetic_versions`` fixture wires the
default (every package above the floor); individual tests override
specific packages when they need to exercise the floor exemption.
"""

import pytest
from check_version import _check, _code_is_equivalent

#: Default synthetic VERSION for any package the test doesn't override.
#: Above the pre-release floor so the bump-required gate kicks in by
#: default; tests opt into the floor by adding entries to the override.
_DEFAULT_VERSION = "0.1.0"


@pytest.fixture
def _synthetic_versions(monkeypatch):
    """Return a setter that wires a synthetic version map into ``_check``.

    Usage::

        def test_foo(self, monkeypatch, capsys, _synthetic_versions):
            _synthetic_versions({("workbench", "repl"): "0.0.0"})
            ...

    Any package not in the override map reads as ``_DEFAULT_VERSION``
    (above the pre-release floor).  ``release_tags`` is also stubbed
    to return an empty list so the new-package NOTE branch never fires
    unless a test explicitly overrides it.
    """

    def _apply(version_overrides: dict[tuple[str, str], str] | None = None) -> None:
        overrides = version_overrides or {}

        def _read_version(package_dir):
            key = (package_dir.parent.name, package_dir.name)
            return overrides.get(key, _DEFAULT_VERSION)

        monkeypatch.setattr("check_version.read_version", _read_version)
        monkeypatch.setattr("check_version.release_tags", lambda _name: ["v0.1.0"])
        # Default: every synthetic source path is a real (non-docstring) change,
        # matching pre-exemption behavior. Tests exercising the docstring
        # exemption override this. Keeps _check off real git/filesystem.
        monkeypatch.setattr(
            "check_version._diff_is_docstring_only",
            lambda _path, _base: False,
        )

    return _apply


class TestCheck:
    """Tests for the _check function."""

    def test_no_changed_files(self, monkeypatch, capsys, _synthetic_versions):
        """No changes produces a clean exit."""
        _synthetic_versions()
        monkeypatch.setattr("check_version.changed_files", lambda _base: [])
        result = _check("origin/main")
        assert result == 0
        assert "No changed files detected" in capsys.readouterr().out

    def test_non_library_changes_only(self, monkeypatch, capsys, _synthetic_versions):
        """Changes outside libraries/ and workbench/ are not release-relevant."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["scripts/run.py", "README.md"],
        )
        result = _check("origin/main")
        assert result == 0
        assert "No release-relevant package changes" in capsys.readouterr().out

    def test_src_change_with_version_bump(self, monkeypatch, capsys, _synthetic_versions):
        """src/ change with VERSION bump passes."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: [
                "libraries/timing/src/chumicro_timing/core.py",
                "libraries/timing/VERSION",
            ],
        )
        result = _check("origin/main")
        assert result == 0
        assert "OK:" in capsys.readouterr().out

    def test_src_change_without_version_bump_fails(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        """src/ change without VERSION bump fails."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["libraries/timing/src/chumicro_timing/core.py"],
        )
        result = _check("origin/main")
        assert result == 1
        assert "FAIL:" in capsys.readouterr().out

    def test_pyproject_change_requires_bump(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        """pyproject.toml change without VERSION bump fails."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["libraries/runner/pyproject.toml"],
        )
        result = _check("origin/main")
        assert result == 1
        assert "FAIL:" in capsys.readouterr().out

    def test_test_change_does_not_require_bump(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        """tests/ change is not release-relevant and doesn't need a bump."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["libraries/timing/tests/test_ticks.py"],
        )
        result = _check("origin/main")
        assert result == 0
        assert "No release-relevant" in capsys.readouterr().out

    def test_version_only_change(self, monkeypatch, capsys, _synthetic_versions):
        """Bumping VERSION without src/ changes is fine (unusual but valid)."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["libraries/timing/VERSION"],
        )
        result = _check("origin/main")
        assert result == 0

    def test_multiple_libraries_one_missing(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        """When two libraries change, failing one causes overall failure."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: [
                "libraries/timing/src/chumicro_timing/core.py",
                "libraries/timing/VERSION",
                "libraries/runner/src/chumicro_runner/core.py",
                # runner VERSION not bumped
            ],
        )
        result = _check("origin/main")
        assert result == 1
        captured = capsys.readouterr().out
        # _check returns 1 immediately after printing FAIL lines —
        # the OK messages for compliant libraries are never reached.
        assert "FAIL: libraries/runner/" in captured

    def test_workbench_src_change_with_version_bump(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        """workbench/<name>/src/ change with VERSION bump passes."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: [
                "workbench/deploy/src/chumicro_deploy/core.py",
                "workbench/deploy/VERSION",
            ],
        )
        result = _check("origin/main")
        assert result == 0
        assert "OK: workbench/deploy/" in capsys.readouterr().out

    def test_workbench_src_change_without_version_bump_fails(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        """workbench/<name>/src/ change without VERSION bump fails."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["workbench/deploy/src/chumicro_deploy/core.py"],
        )
        result = _check("origin/main")
        assert result == 1
        assert "FAIL: workbench/deploy/" in capsys.readouterr().out

    def test_workbench_pyproject_change_requires_bump(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        """workbench/<name>/pyproject.toml change without VERSION bump fails."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["workbench/deploy/pyproject.toml"],
        )
        result = _check("origin/main")
        assert result == 1
        assert "FAIL: workbench/deploy/" in capsys.readouterr().out

    def test_pre_release_floor_skips_bump_requirement(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        """Decision 0038 §6: a package at 0.0.0 is exempt from the bump gate.

        Uses a synthetic ``read_version`` so the test doesn't depend on
        which real package happens to sit at the floor on any given day —
        the previous version of this test hardcoded ``workbench/repl``
        and broke the moment that package's VERSION was bumped.
        """
        _synthetic_versions({("workbench", "repl"): "0.0.0"})
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["workbench/repl/src/chumicro_repl/cli.py"],
        )
        result = _check("origin/main")
        assert result == 0
        captured = capsys.readouterr().out
        assert "PRE-RELEASE: workbench/repl/" in captured
        assert "FAIL:" not in captured

    def test_pre_release_floor_does_not_mask_non_zero_packages(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        """A package above 0.0.0 still requires VERSION bumps even if a
        sibling 0.0.0 package is also being changed."""
        _synthetic_versions({("workbench", "repl"): "0.0.0"})
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: [
                "workbench/repl/src/chumicro_repl/cli.py",      # 0.0.0
                "libraries/timing/src/chumicro_timing/core.py",  # >0.0.0
            ],
        )
        result = _check("origin/main")
        assert result == 1
        captured = capsys.readouterr().out
        assert "FAIL: libraries/timing/" in captured

    def test_mixed_roots_pass(self, monkeypatch, capsys, _synthetic_versions):
        """Library + workbench changes both bumped pass cleanly."""
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: [
                "libraries/timing/src/chumicro_timing/core.py",
                "libraries/timing/VERSION",
                "workbench/deploy/src/chumicro_deploy/core.py",
                "workbench/deploy/VERSION",
            ],
        )
        result = _check("origin/main")
        assert result == 0
        captured = capsys.readouterr().out
        assert "OK: libraries/timing/" in captured
        assert "OK: workbench/deploy/" in captured


class TestDocstringEquivalence:
    """The AST-normalization that exempts docstring/comment-only changes."""

    def test_identical_source(self):
        source = "def f(x):\n    return x + 1\n"
        assert _code_is_equivalent(source, source)

    def test_docstring_change_is_equivalent(self):
        old = 'def f(x):\n    """Old doc."""\n    return x\n'
        new = 'def f(x):\n    """A reworded doc."""\n    return x\n'
        assert _code_is_equivalent(old, new)

    def test_docstring_removed_is_equivalent(self):
        old = 'def f(x):\n    """Doc."""\n    return x\n'
        new = "def f(x):\n    return x\n"
        assert _code_is_equivalent(old, new)

    def test_comment_change_is_equivalent(self):
        old = "def f(x):\n    # old comment\n    return x\n"
        new = "def f(x):\n    # comment, reworded\n    return x\n"
        assert _code_is_equivalent(old, new)

    def test_attribute_docstring_change_is_equivalent(self):
        # PEP 258 attribute docstring following a constant assignment.
        old = 'PATH = "/x"\n"""Old attribute doc."""\n'
        new = 'PATH = "/x"\n"""New attribute doc, longer."""\n'
        assert _code_is_equivalent(old, new)

    def test_bare_string_in_else_branch_is_equivalent(self):
        # A no-op string in an ``else`` body lives in the If node's
        # ``orelse``, which the earlier ``.body``-only strip missed.
        old = (
            "def f(x):\n    if x:\n        return 1\n"
            '    else:\n        "note"\n        return 2\n'
        )
        new = "def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n"
        assert _code_is_equivalent(old, new)

    def test_bare_string_in_finally_branch_is_equivalent(self):
        # A no-op string in a ``finally`` body lives in the Try node's
        # ``finalbody`` — likewise missed by a ``.body``-only strip.
        old = (
            "def f():\n    try:\n        g()\n"
            '    finally:\n        "cleanup note"\n        h()\n'
        )
        new = "def f():\n    try:\n        g()\n    finally:\n        h()\n"
        assert _code_is_equivalent(old, new)

    def test_real_change_in_else_branch_still_flagged(self):
        # The completeness fix must not mask a genuine change in ``orelse``.
        assert not _code_is_equivalent(
            "def f(x):\n    if x:\n        return 1\n    else:\n        return 2\n",
            "def f(x):\n    if x:\n        return 1\n    else:\n        return 3\n",
        )

    def test_code_change_is_not_equivalent(self):
        assert not _code_is_equivalent(
            "def f(x):\n    return x + 1\n",
            "def f(x):\n    return x + 2\n",
        )

    def test_error_message_string_change_is_not_equivalent(self):
        # A raised string literal is shipped output, not a docstring.
        assert not _code_is_equivalent(
            'def f():\n    raise ValueError("bad — thing")\n',
            'def f():\n    raise ValueError("bad; thing")\n',
        )

    def test_syntax_error_is_not_equivalent(self):
        assert not _code_is_equivalent("def f(", "def f():\n    pass\n")


class TestDocstringExemptionInCheck:
    """_check exempts a package whose only source change is docstring-only."""

    def test_docstring_only_src_change_needs_no_bump(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: ["libraries/timing/src/chumicro_timing/ticks.py"],
        )
        monkeypatch.setattr(
            "check_version._diff_is_docstring_only", lambda _path, _base: True,
        )
        result = _check("origin/main")
        assert result == 0
        assert "No release-relevant package changes detected." in capsys.readouterr().out

    def test_mixed_docstring_and_real_change_still_needs_bump(
        self, monkeypatch, capsys, _synthetic_versions,
    ):
        _synthetic_versions()
        monkeypatch.setattr(
            "check_version.changed_files",
            lambda _base: [
                "libraries/timing/src/chumicro_timing/ticks.py",
                "libraries/timing/src/chumicro_timing/waits.py",
            ],
        )
        # Only ticks.py is docstring-only; waits.py is a real change.
        monkeypatch.setattr(
            "check_version._diff_is_docstring_only",
            lambda path, _base: path.endswith("ticks.py"),
        )
        result = _check("origin/main")
        assert result == 1
        assert "FAIL: libraries/timing/" in capsys.readouterr().out
