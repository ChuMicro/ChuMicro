"""CLI smoke tests for the empty scaffold."""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_checks import Finding, Rule
from chumicro_checks.cli import _find_repo_root, _parse_codes, main


def test_help_exits_cleanly(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    assert "chumicro-checks" in capsys.readouterr().out


def test_no_rules_means_no_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # An empty registry → nothing fires → exit 0.
    assert main(["--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == ""


def test_list_with_empty_registry(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("chumicro_checks.cli.registered_rules", dict)
    assert main(["--list"]) == 0
    assert "no rules registered" in capsys.readouterr().out


def test_unknown_select_returns_usage_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["--root", str(tmp_path), "--select", "CHU999"]) == 2
    assert "unknown rule code" in capsys.readouterr().err


def test_parse_codes_splits_and_normalises() -> None:
    assert _parse_codes("chu006, CHU011, ,") == {"CHU006", "CHU011"}
    assert _parse_codes(None) == set()
    assert _parse_codes("") == set()


def test_find_repo_root_picks_up_marker(tmp_path: Path) -> None:
    nested = tmp_path / "deep" / "nested"
    nested.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'fake'\n")
    assert _find_repo_root(nested) == tmp_path.resolve()


def test_finding_renders_relative_to_root(tmp_path: Path) -> None:
    target = tmp_path / "src" / "thing.py"
    target.parent.mkdir(parents=True)
    target.write_text("")
    finding = Finding(path=target, line=12, code="CHU999", message="example")
    assert finding.render(root=tmp_path) == "src/thing.py:12: CHU999 example"


class _AlwaysFires(Rule):
    code = "CHU999"
    description = "test rule"

    def check(self, repo_root: Path) -> list[Finding]:
        return [Finding(path=repo_root / "x.py", line=1, code="CHU999", message="bad")]


def test_findings_are_emitted_and_exit_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "chumicro_checks.cli.registered_rules", lambda: {"CHU999": _AlwaysFires()}
    )

    assert main(["--root", str(tmp_path)]) == 1
    captured = capsys.readouterr().out
    assert "CHU999 bad" in captured


def test_list_with_registered_rule(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "chumicro_checks.cli.registered_rules", lambda: {"CHU999": _AlwaysFires()}
    )
    assert main(["--list"]) == 0
    out = capsys.readouterr().out
    assert "CHU999" in out
    assert "test rule" in out


def test_find_repo_root_falls_back_when_no_marker(tmp_path: Path) -> None:
    # tmp_path is under /private/var/folders/... — no .git or pyproject.toml
    # exists between it and the filesystem root, so the fallback returns
    # the resolved start path itself.
    deep = tmp_path / "no" / "marker" / "here"
    deep.mkdir(parents=True)
    assert _find_repo_root(deep) == deep.resolve()


def test_finding_render_keeps_absolute_when_unrelated(tmp_path: Path) -> None:
    finding = Finding(path=Path("/elsewhere/foo.py"), line=3, code="CHU999", message="m")
    rendered = finding.render(root=tmp_path)
    assert rendered.startswith("/elsewhere/foo.py:3:")


def test_finding_render_without_root_uses_path_as_is() -> None:
    finding = Finding(path=Path("relative/foo.py"), line=4, code="CHU999", message="m")
    assert finding.render() == "relative/foo.py:4: CHU999 m"


def test_dunder_main_module_imports_cli_main() -> None:
    """``python -m chumicro_checks`` entry point wires to cli.main.

    Importing the ``__main__`` module exercises its three import lines
    (the ``if __name__ == "__main__"`` block itself stays under
    ``# pragma: no cover``).  Asserts the wiring is unchanged so a
    rename of ``cli.main`` would surface here at test time.
    """
    import chumicro_checks.__main__ as dunder_main
    from chumicro_checks.cli import main as cli_main

    assert dunder_main.main is cli_main
