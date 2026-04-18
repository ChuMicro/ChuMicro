"""Tests for check_whitespace.py — CHU002–CHU004 whitespace rules."""


from check_whitespace import (
    _has_noqa,
    _should_check,
    check_file,
    check_paths,
    main,
)


class TestHasNoqa:
    """Tests for _has_noqa helper."""

    def test_no_suppression(self):
        """Line without noqa returns False."""
        assert _has_noqa("x = 1", "CHU004") is False

    def test_specific_suppression(self):
        """# noqa: CHU004 suppresses the matching rule."""
        assert _has_noqa("x = 1  # noqa: CHU004", "CHU004") is True

    def test_bare_noqa(self):
        """Bare # noqa suppresses any rule."""
        assert _has_noqa("x = 1  # noqa", "CHU004") is True

    def test_wrong_code(self):
        """# noqa: CHU001 does not suppress CHU004."""
        assert _has_noqa("x = 1  # noqa: CHU001", "CHU004") is False

    def test_multiple_codes(self):
        """# noqa: CHU001,CHU004 suppresses CHU004."""
        assert _has_noqa("x = 1  # noqa: CHU001,CHU004", "CHU004") is True


class TestShouldCheck:
    """Tests for _should_check helper."""

    def test_python_file(self, tmp_path):
        """Python files are checked."""
        filepath = tmp_path / "example.py"
        filepath.touch()
        assert _should_check(filepath) is True

    def test_markdown_file(self, tmp_path):
        """Markdown files are checked."""
        filepath = tmp_path / "README.md"
        filepath.touch()
        assert _should_check(filepath) is True

    def test_binary_file(self, tmp_path):
        """Binary extensions are skipped."""
        filepath = tmp_path / "image.png"
        filepath.touch()
        assert _should_check(filepath) is False

    def test_toml_file(self, tmp_path):
        """TOML files are checked."""
        filepath = tmp_path / "config.toml"
        filepath.touch()
        assert _should_check(filepath) is True


class TestCheckFile:
    """Tests for check_file — individual file scanning."""

    def test_clean_file(self, tmp_path):
        """File ending with one newline and no issues passes."""
        filepath = tmp_path / "clean.py"
        filepath.write_text("x = 1\n", encoding="utf-8")
        assert check_file(filepath) == []

    def test_empty_file(self, tmp_path):
        """Empty files are accepted."""
        filepath = tmp_path / "empty.py"
        filepath.write_text("", encoding="utf-8")
        assert check_file(filepath) == []

    def test_no_trailing_newline(self, tmp_path):
        """File without trailing newline triggers CHU002."""
        filepath = tmp_path / "missing.py"
        filepath.write_text("x = 1", encoding="utf-8")
        errors = check_file(filepath)
        assert len(errors) == 1
        assert "CHU002" in errors[0]
        assert "does not end with a newline" in errors[0]

    def test_two_trailing_newlines(self, tmp_path):
        """File ending with two newlines triggers CHU002."""
        filepath = tmp_path / "double.py"
        filepath.write_text("x = 1\n\n", encoding="utf-8")
        errors = check_file(filepath)
        assert any("CHU002" in error for error in errors)
        assert any("2 newlines instead of 1" in error for error in errors)

    def test_three_trailing_newlines(self, tmp_path):
        """File ending with three newlines triggers CHU002."""
        filepath = tmp_path / "triple.py"
        filepath.write_text("x = 1\n\n\n", encoding="utf-8")
        errors = check_file(filepath)
        chu002_errors = [error for error in errors if "CHU002" in error]
        assert len(chu002_errors) == 1
        assert "3 newlines instead of 1" in chu002_errors[0]

    def test_three_consecutive_blank_lines(self, tmp_path):
        """Three consecutive blank lines in file body triggers CHU003."""
        filepath = tmp_path / "gaps.py"
        filepath.write_text("x = 1\n\n\n\ny = 2\n", encoding="utf-8")
        errors = check_file(filepath)
        chu003_errors = [error for error in errors if "CHU003" in error]
        assert len(chu003_errors) == 1
        assert "consecutive blank lines" in chu003_errors[0]

    def test_two_blank_lines_is_fine(self, tmp_path):
        """Two consecutive blank lines are allowed (PEP 8 top-level)."""
        filepath = tmp_path / "ok.py"
        filepath.write_text("x = 1\n\n\ny = 2\n", encoding="utf-8")
        errors = check_file(filepath)
        assert not any("CHU003" in error for error in errors)

    def test_trailing_whitespace(self, tmp_path):
        """Trailing spaces on a line trigger CHU004."""
        filepath = tmp_path / "trail.py"
        filepath.write_text("x = 1   \n", encoding="utf-8")
        errors = check_file(filepath)
        assert len(errors) == 1
        assert "CHU004" in errors[0]
        assert "trailing whitespace" in errors[0]

    def test_trailing_whitespace_suppressed(self, tmp_path):
        """Trailing whitespace with noqa suppression is accepted."""
        filepath = tmp_path / "suppressed.py"
        filepath.write_text("x = 1   # noqa: CHU004   \n", encoding="utf-8")
        # The noqa is on the line, so CHU004 should be suppressed.
        # Note: the line still has trailing whitespace after the comment,
        # but the suppression covers it.
        errors = check_file(filepath)
        assert not any("CHU004" in error for error in errors)

    def test_trailing_whitespace_non_python_no_suppression(self, tmp_path):
        """Non-Python files do not support noqa suppression for CHU004."""
        filepath = tmp_path / "trail.md"
        filepath.write_text("hello   # noqa: CHU004   \n", encoding="utf-8")
        errors = check_file(filepath)
        assert any("CHU004" in error for error in errors)

    def test_tabs_as_trailing_whitespace(self, tmp_path):
        """Trailing tabs trigger CHU004."""
        filepath = tmp_path / "tabs.py"
        filepath.write_text("x = 1\t\n", encoding="utf-8")
        errors = check_file(filepath)
        assert any("CHU004" in error for error in errors)

    def test_unreadable_file(self, tmp_path):
        """Binary/unreadable file returns no errors."""
        filepath = tmp_path / "binary.py"
        filepath.write_bytes(b"\x80\x81\x82")
        assert check_file(filepath) == []

    def test_blank_line_after_def(self, tmp_path):
        """Blank line after def triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text("def foo():\n\n    pass\n", encoding="utf-8")
        errors = check_file(filepath)
        chu005 = [error for error in errors if "CHU005" in error]
        assert len(chu005) == 1
        assert "blank line after block opener" in chu005[0]

    def test_blank_line_after_class(self, tmp_path):
        """Blank line after class triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text("class Foo:\n\n    pass\n", encoding="utf-8")
        errors = check_file(filepath)
        assert any("CHU005" in error for error in errors)

    def test_blank_line_after_if(self, tmp_path):
        """Blank line after if triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text("if True:\n\n    pass\n", encoding="utf-8")
        errors = check_file(filepath)
        assert any("CHU005" in error for error in errors)

    def test_blank_line_after_for(self, tmp_path):
        """Blank line after for triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text("for index in range(10):\n\n    pass\n", encoding="utf-8")
        errors = check_file(filepath)
        assert any("CHU005" in error for error in errors)

    def test_blank_line_after_while(self, tmp_path):
        """Blank line after while triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text("while True:\n\n    break\n", encoding="utf-8")
        errors = check_file(filepath)
        assert any("CHU005" in error for error in errors)

    def test_blank_line_after_try(self, tmp_path):
        """Blank line after try triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text("try:\n\n    pass\nexcept Exception:\n    pass\n", encoding="utf-8")
        errors = check_file(filepath)
        assert any("CHU005" in error for error in errors)

    def test_blank_line_after_else(self, tmp_path):
        """Blank line after else triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text("if True:\n    pass\nelse:\n\n    pass\n", encoding="utf-8")
        errors = check_file(filepath)
        assert any("CHU005" in error for error in errors)

    def test_blank_line_after_elif(self, tmp_path):
        """Blank line after elif triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text(
            "if True:\n    pass\nelif False:\n\n    pass\n",
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert any("CHU005" in error for error in errors)

    def test_blank_line_after_except(self, tmp_path):
        """Blank line after except (non-definition body) triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text(
            "try:\n    pass\nexcept Exception:\n\n    pass\n",
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert any("CHU005" in error for error in errors)

    def test_except_with_fallback_def_allowed(self, tmp_path):
        """Blank line after except is allowed when followed by a def."""
        filepath = tmp_path / "fallback.py"
        filepath.write_text(
            "try:\n"
            "    from micropython import const\n"
            "except ImportError:\n"
            "\n"
            "    def const(value):\n"
            "        return value\n",
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert not any("CHU005" in error for error in errors)

    def test_except_with_fallback_class_allowed(self, tmp_path):
        """Blank line after except is allowed when followed by a class."""
        filepath = tmp_path / "fallback.py"
        filepath.write_text(
            "try:\n"
            "    from fast import Engine\n"
            "except ImportError:\n"
            "\n"
            "    class Engine:\n"
            "        pass\n",
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert not any("CHU005" in error for error in errors)

    def test_if_with_nested_def_allowed(self, tmp_path):
        """Blank line after if is allowed when followed by a def."""
        filepath = tmp_path / "conditional.py"
        filepath.write_text(
            "if USE_FAST:\n"
            "\n"
            "    def helper():\n"
            "        pass\n",
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert not any("CHU005" in error for error in errors)

    def test_else_with_nested_def_allowed(self, tmp_path):
        """Blank line after else is allowed when followed by a def."""
        filepath = tmp_path / "conditional.py"
        filepath.write_text(
            "if USE_FAST:\n"
            "    pass\n"
            "else:\n"
            "\n"
            "    def helper():\n"
            "        pass\n",
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert not any("CHU005" in error for error in errors)

    def test_blank_line_after_finally(self, tmp_path):
        """Blank line after finally triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text(
            "try:\n    pass\nfinally:\n\n    pass\n",
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert any("CHU005" in error for error in errors)

    def test_blank_line_after_with(self, tmp_path):
        """Blank line after with triggers CHU005."""
        filepath = tmp_path / "gap.py"
        filepath.write_text(
            "with open('x') as handle:\n\n    pass\n",
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert any("CHU005" in error for error in errors)

    def test_no_blank_after_def_is_clean(self, tmp_path):
        """Def without blank line after it is clean."""
        filepath = tmp_path / "clean.py"
        filepath.write_text("def foo():\n    pass\n", encoding="utf-8")
        errors = check_file(filepath)
        assert not any("CHU005" in error for error in errors)

    def test_docstring_after_def_is_clean(self, tmp_path):
        """Docstring immediately after def is clean."""
        filepath = tmp_path / "clean.py"
        filepath.write_text(
            'def foo():\n    """Docstring."""\n    pass\n',
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert not any("CHU005" in error for error in errors)

    def test_chu005_not_triggered_for_non_python(self, tmp_path):
        """CHU005 only applies to Python files."""
        filepath = tmp_path / "notes.md"
        filepath.write_text("def something:\n\nmore text\n", encoding="utf-8")
        errors = check_file(filepath)
        assert not any("CHU005" in error for error in errors)

    def test_chu005_not_triggered_inside_docstring(self, tmp_path):
        """Prose starting with a keyword inside a docstring is not flagged."""
        filepath = tmp_path / "template.py"
        filepath.write_text(
            'TEMPLATE = """\n'
            "class below with real fakes.  A good fake:\n"
            "\n"
            "- does something\n"
            '"""\n',
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert not any("CHU005" in error for error in errors)

    def test_chu005_noqa_suppression(self, tmp_path):
        """CHU005 can be suppressed with noqa on the block opener line."""
        filepath = tmp_path / "suppressed.py"
        filepath.write_text(
            "def foo():  # noqa: CHU005\n\n    pass\n",
            encoding="utf-8",
        )
        errors = check_file(filepath)
        assert not any("CHU005" in error for error in errors)


class TestCheckPaths:
    """Tests for check_paths — directory scanning."""

    def test_clean_directory(self, tmp_path):
        """Directory of clean files returns 0."""
        (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
        (tmp_path / "b.py").write_text("y = 2\n", encoding="utf-8")
        assert check_paths([str(tmp_path)]) == 0

    def test_dirty_directory(self, tmp_path):
        """Directory with violations returns 1."""
        (tmp_path / "a.py").write_text("x = 1\n\n", encoding="utf-8")
        assert check_paths([str(tmp_path)]) == 1

    def test_single_file(self, tmp_path):
        """Single file path works."""
        filepath = tmp_path / "solo.py"
        filepath.write_text("x = 1\n", encoding="utf-8")
        assert check_paths([str(filepath)]) == 0

    def test_skips_pycache(self, tmp_path):
        """__pycache__ directories are skipped."""
        cache_dir = tmp_path / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "module.py").write_text("x = 1\n\n\n", encoding="utf-8")
        assert check_paths([str(tmp_path)]) == 0

    def test_skips_egg_info(self, tmp_path):
        """*.egg-info directories are skipped."""
        egg_dir = tmp_path / "my_package.egg-info"
        egg_dir.mkdir()
        (egg_dir / "SOURCES.txt").write_text("some content", encoding="utf-8")
        assert check_paths([str(tmp_path)]) == 0


class TestMain:
    """Tests for the main entry point."""

    def test_explicit_paths(self, tmp_path):
        """Passing explicit paths checks those paths."""
        filepath = tmp_path / "ok.py"
        filepath.write_text("x = 1\n", encoding="utf-8")
        assert main([str(filepath)]) == 0

    def test_violations_return_nonzero(self, tmp_path):
        """Violations cause nonzero exit."""
        filepath = tmp_path / "bad.py"
        filepath.write_text("x = 1", encoding="utf-8")
        assert main([str(filepath)]) == 1
