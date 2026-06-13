"""Tests for the deploy-time docstring and comment stripper.

Covers strip_source (docstring and comment removal, the equivalence
guard, and the verbatim fallbacks) and minify_python_tree (in-place
rewrite across a staging tree).
"""

from pathlib import Path

import pytest
from chumicro_deploy.source_minify import (
    _strip_docstring_from_body,
    minify_python_tree,
    strip_source,
)


def test_comment_free_file_is_returned_byte_identical():
    """A file with no docstrings or comments comes back unchanged."""
    source = "import os\nvalue = os.getpid()\n"
    assert strip_source(source) == source


def test_module_class_and_function_docstrings_are_removed():
    """Docstrings at module, class, and function scope are all dropped."""
    source = (
        '"""module doc"""\n'
        "class Thing:\n"
        '    """class doc"""\n'
        "    def method(self):\n"
        '        """method doc"""\n'
        "        return 1\n"
    )
    stripped = strip_source(source)
    assert "module doc" not in stripped
    assert "class doc" not in stripped
    assert "method doc" not in stripped
    assert "return 1" in stripped


def test_async_function_docstring_is_removed():
    """A docstring on an async function is dropped like a sync one."""
    source = 'async def fetch():\n    """async doc"""\n    return 7\n'
    stripped = strip_source(source)
    assert "async doc" not in stripped
    assert "return 7" in stripped


def test_whole_line_and_trailing_comments_are_removed():
    """Both standalone and trailing ``#`` comments disappear, code stays."""
    source = (
        "# leading comment\n"
        "value = 1  # trailing comment\n"
        "    # indented comment\n"
        "result = value + 1\n"
    )
    stripped = strip_source(source)
    assert "#" not in stripped
    assert "value = 1" in stripped
    assert "result = value + 1" in stripped


def test_docstring_only_function_and_class_gain_a_pass():
    """A class or function whose only statement was a docstring keeps a pass body."""
    source = (
        "class Empty:\n"
        '    """only a docstring"""\n'
        "def stub():\n"
        '    """only a docstring"""\n'
    )
    stripped = strip_source(source)
    assert "only a docstring" not in stripped
    assert "class Empty:\n    pass" in stripped
    assert "def stub():\n    pass" in stripped


def test_module_docstring_only_file_becomes_blank():
    """A file holding nothing but a one-line module docstring strips to one blank line."""
    assert strip_source('"""just a module doc"""\n') == "\n"


def test_line_numbers_are_preserved():
    """Stripping blanks removed lines in place, so every kept statement keeps its line number."""
    source = (
        '"""module docstring\n'
        "spanning three\n"
        'lines"""\n'
        "import os\n"
        "# a comment line\n"
        "value = os.getpid()\n"
    )
    stripped = strip_source(source)
    source_lines = source.split("\n")
    stripped_lines = stripped.split("\n")
    assert len(stripped_lines) == len(source_lines)
    # import os stays on line 4 and value on line 6, exactly where they began.
    assert stripped_lines[3] == "import os"
    assert stripped_lines[5] == "value = os.getpid()"


def test_hash_inside_single_line_strings_is_kept():
    """A ``#`` inside single, double, or triple quotes is not treated as a comment."""
    source = (
        "a = 'value # one'\n"
        'b = "value # two"  # real comment\n'
        'c = """value # three"""\n'
    )
    stripped = strip_source(source)
    assert "value # one" in stripped
    assert "value # two" in stripped
    assert "value # three" in stripped
    assert "real comment" not in stripped


def test_escaped_quote_inside_string_does_not_end_the_string():
    """An escaped quote keeps the scanner inside the string past a later ``#``."""
    source = 'label = "a\\"b # still in string"  # comment\n'
    stripped = strip_source(source)
    assert 'a\\"b # still in string' in stripped
    assert "# comment" not in stripped


def test_hash_inside_multiline_string_falls_back_to_verbatim():
    """The line-scoped scanner would corrupt a multi-line string, so the guard keeps it verbatim."""
    source = 'blob = """\nfirst line\n# not a comment\nlast line"""\n'
    assert strip_source(source) == source


def test_unparseable_input_is_returned_verbatim():
    """Source that does not parse is handed back untouched."""
    source = "def broken(:\n    pass\n"
    assert strip_source(source) == source


def test_strip_that_breaks_parseability_falls_back_to_verbatim():
    """When comment removal would unbalance a multi-line string, the original is returned."""
    # Line two's '#' sits inside a triple-quoted string; the per-line scanner
    # strips from it through the closing quotes, so the candidate no longer
    # parses and strip_source returns the input.
    source = 'pair = ("""\na # """, "b")\n'
    assert strip_source(source) == source


def test_strip_source_is_idempotent():
    """Stripping already-stripped output produces the same text."""
    source = '"""doc"""\nx = 1  # c\ndef f():\n    """d"""\n    return x\n'
    once = strip_source(source)
    assert strip_source(once) == once


def test_minify_python_tree_rewrites_python_files_in_place(tmp_path: Path):
    """Every .py under the root is stripped in place, nested packages included."""
    package = tmp_path / "pkg"
    package.mkdir()
    (package / "__init__.py").write_text('"""pkg doc"""\nVERSION = "1.0"\n')
    sub = package / "sub"
    sub.mkdir()
    (sub / "mod.py").write_text("def go():\n    # inner\n    return 1\n")

    minify_python_tree(tmp_path)

    assert (package / "__init__.py").read_text() == '\nVERSION = "1.0"\n'
    assert "# inner" not in (sub / "mod.py").read_text()


def test_minify_python_tree_leaves_comment_free_files_untouched(tmp_path: Path):
    """A file with nothing to strip is not rewritten."""
    target = tmp_path / "clean.py"
    target.write_text("x = 1\n")
    minify_python_tree(tmp_path)
    assert target.read_text() == "x = 1\n"


def test_minify_python_tree_ignores_non_python_files(tmp_path: Path):
    """Non-.py files in the tree are left alone."""
    data = tmp_path / "config.toml"
    data.write_text("# a toml comment\nkey = 1\n")
    minify_python_tree(tmp_path)
    assert data.read_text() == "# a toml comment\nkey = 1\n"


def test_minify_python_tree_skips_files_that_are_not_utf8(tmp_path: Path):
    """A .py file that is not valid UTF-8 is skipped rather than crashing the walk."""
    blob = tmp_path / "binary.py"
    blob.write_bytes(b"\xff\xfe\x00garbage")
    minify_python_tree(tmp_path)
    assert blob.read_bytes() == b"\xff\xfe\x00garbage"


def test_strip_docstring_from_body_empty_body_with_required_pass():
    """An empty body becomes a single pass when nonempty output is required."""
    result = _strip_docstring_from_body([], require_nonempty=True)
    assert len(result) == 1
    assert type(result[0]).__name__ == "Pass"


def test_strip_docstring_from_body_empty_body_without_requirement():
    """An empty body stays empty when no pass is required."""
    assert _strip_docstring_from_body([]) == []


def test_strip_docstring_from_body_keeps_non_docstring_first_statement():
    """A body whose first statement is not a bare string is returned unchanged."""
    import ast

    body = ast.parse("x = 1\ny = 2\n").body
    assert _strip_docstring_from_body(body) is body


def test_strip_docstring_from_body_keeps_non_string_constant():
    """A leading numeric constant expression is not mistaken for a docstring."""
    import ast

    body = ast.parse("42\nx = 1\n").body
    assert _strip_docstring_from_body(body) is body


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
