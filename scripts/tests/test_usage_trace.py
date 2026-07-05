"""Tests for the audit skills' usage-path tracer (`.github/skills/audit-code/usage_trace.py`).

Two layers, matching the tracer's two halves:

* The **AST helpers** (`api_seed_quals`, `def_line_of_qual`, `enclosing_def`) are pure and
  deterministic — no jedi, no repo — so they are unit-tested directly.
* The **reference resolution** (`cmd_trace`) is what replaced the old name-grep + generic-name
  cap. It is exercised end-to-end against a synthetic package under ``tmp_path``: a two-hop call
  chain (``app`` -> ``welcome`` -> ``greet``) plus a decoy ``Bot.greet`` that shares the name but
  is a different symbol. The point the old tracer could not make: the decoy stays out of the
  top-level ``greet`` seed group, and a generic name traces to its real call sites with no cap.
  The synthetic tree is not a git repo, so this also covers the non-git ``_fs_grep`` fallback.
"""

import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parents[2] / ".github" / "skills" / "audit-code"
if str(SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR))

import usage_trace  # noqa: E402, I001  (imported after SKILL_DIR joins sys.path, above)


# --- AST helpers (no jedi) ---

SAMPLE = '''\
def top_level():
    pass


def _private():
    pass


class Runner:
    def tick(self):
        marker = 1
        return marker

    def _secret(self):
        pass


class _Hidden:
    def method(self):
        pass
'''


def test_api_seed_quals_public_surface_and_methods():
    quals = usage_trace.api_seed_quals_from_source(SAMPLE)
    assert quals == ["top_level", "Runner", "Runner.tick"]


def test_def_line_of_qual_finds_nested_method():
    import ast
    tree = ast.parse(SAMPLE)
    assert usage_trace.def_line_of_qual(tree, "Runner.tick") == 10
    assert usage_trace.def_line_of_qual(tree, "Runner") == 9
    assert usage_trace.def_line_of_qual(tree, "nope") is None


def test_enclosing_def_picks_innermost():
    import ast
    tree = ast.parse(SAMPLE)
    # line 11 (`marker = 1`) lives inside Runner.tick
    assert usage_trace.enclosing_def(tree, 11) == ("Runner.tick", 10)
    # line 1 (`def top_level`) is a top-level def, enclosed by itself
    assert usage_trace.enclosing_def(tree, 1) == ("top_level", 1)


# --- reference resolution (needs jedi) ---


@pytest.fixture
def fixture_pkg(tmp_path):
    (tmp_path / "lib.py").write_text("def greet(name):\n    return 'hi ' + name\n")
    (tmp_path / "caller.py").write_text(
        "from lib import greet\n\n\ndef welcome(name):\n    return greet(name)\n"
    )
    (tmp_path / "app.py").write_text("from caller import welcome\n\nprint(welcome('world'))\n")
    # decoy: a same-named method on an unrelated class
    (tmp_path / "other.py").write_text(
        "class Bot:\n    def greet(self):\n        return 'beep'\n\n\nBot().greet()\n"
    )
    return tmp_path


def test_trace_resolves_two_hops_and_disambiguates_decoy(fixture_pkg, tmp_path):
    pytest.importorskip("jedi")
    import json
    out = tmp_path / "out.json"
    rc = usage_trace.cmd_trace([str(fixture_pkg)], [{"kind": "name", "name": "greet"}], 4, str(out))
    assert rc == 0
    edges = json.loads(out.read_text())["edges"]

    greet_group = [e for e in edges if e["seed"] == "greet"]
    bot_group = [e for e in edges if e["seed"] == "Bot"]

    # hop 1: welcome() calls greet()
    assert any(e["callee"] == "greet" and e["caller_qual"] == "welcome" and e["depth"] == 1
               for e in greet_group)
    # hop 2 (the whole point): the module body of app.py calls welcome()
    assert any(e["callee"] == "welcome" and e["caller_qual"] == "<module>" and e["depth"] == 2
               for e in greet_group)
    # the top-level greet's chain never wanders into the decoy's file
    assert not any(e["caller_file"] == "other.py" for e in greet_group)
    # the decoy is a real, distinct symbol — its own seed group, never merged into greet
    assert any(e["callee"] == "Bot.greet" and e["caller_file"] == "other.py" for e in bot_group)


def test_trace_records_stop_for_unresolvable_seed(fixture_pkg, tmp_path):
    pytest.importorskip("jedi")
    import json
    out = tmp_path / "out.json"
    usage_trace.cmd_trace([str(fixture_pkg)], [{"kind": "name", "name": "does_not_exist"}],
                          4, str(out))
    payload = json.loads(out.read_text())
    assert payload["edges"] == []
    assert any("no definition" in stop["reason"] for stop in payload["stops"])
