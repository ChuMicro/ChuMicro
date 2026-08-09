"""Tests for the ownership-doc drift checker.

Fixture docs mirror the workspace template's real surfaces: the
agents-doc "File ownership" markdown table, the contributing-doc
"only touches tool-owned files" paragraph (wrapped across lines the
way prose is), and readme lines claiming a directory is tool-owned.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from chumicro_workspace.template_zone_docs import (
    collect_zone_doc_drift,
    main,
)


def _faithful_agents_lines() -> list[str]:
    """Agents-doc lines whose ownership table matches the zone tables."""
    return [
        "# Workspace guide for agents",
        "",
        "## File ownership",
        "",
        "| Path | Who edits | What `update` does |",
        "|---|---|---|",
        "| `projects/<your-name>/` | YOU | leaves alone |",
        "| `devices.yml` | tool (via device commands) | leaves alone |",
        "| `workspace.yml` | YOU | leaves alone |",
        "| `secrets.toml` | YOU | leaves alone |",
        "| `quality.toml` | YOU | leaves alone |",
        "| `shared/` | YOU | leaves alone |",
        "| `packages/` | YOU | leaves alone |",
        "| `run.py` | NEVER edit | rewrites |",
        "| `AGENTS.md` | NEVER edit | rewrites |",  # noqa: CHU006  template-payload filename data
        "| `CONTRIBUTING.md` | NEVER edit | rewrites |",  # noqa: CHU006  template-payload filename data
        "| `pyproject.toml` | NEVER edit | rewrites |",
        "| `requirements.txt` | NEVER edit | rewrites |",
        "| `constraints.txt` | NEVER edit | rewrites |",
        "| `projects/_template/` | NEVER edit | rewrites |",
        "| `.github/skills/` | NEVER edit | rewrites |",
        "| `.github/workflows/` | NEVER edit | rewrites |",
        "| `examples/` | NEVER edit | rewrites |",
        "",
        "## Skills index",
        "",
        "More prose.",
    ]


def _faithful_contributing_lines() -> list[str]:
    """Contributing-doc lines whose tool-owned list matches the zones."""
    return [
        "# Contributing",
        "",
        "`update` only touches tool-owned files: `run.py`, `AGENTS.md`,",  # noqa: CHU006  template-payload filename data
        "`CONTRIBUTING.md`, `pyproject.toml`, `requirements.txt`,",  # noqa: CHU006  template-payload filename data
        "`constraints.txt`, the `projects/_template/` skeleton, the",
        "`examples/` tree, `.github/skills/`, and `.github/workflows/`.",
        "Your `projects/`, `devices.yml`, `workspace.yml`, `secrets.toml`,",
        "`shared/`, and `packages/` are never touched.",
        "",
        "More prose.",
    ]


def _faithful_readme_lines() -> list[str]:
    """Readme lines with one directory ownership claim and one line
    about a tool-owned block inside a user-owned file that also
    mentions a `src/` subdirectory in passing (which the checker must
    not read as a directory claim)."""
    return [
        "# My workspace",
        "",
        "- `examples/`: read-only worked demos.  This folder is tool-owned:",
        "  `python3 run.py update` rewrites it from upstream.",
        "",
        "In dev mode, `setup` maintains a `library_sources:` block in",
        "`workspace.yml`, mapping each library to its `src/` directory."
        "  That block is tool-owned: every `setup` re-syncs it.",
    ]


def _write_docs(
    root: Path,
    *,
    agents: list[str] | None,
    contributing: list[str] | None,
    readme: list[str] | None,
) -> None:
    """Write each non-``None`` doc into *root* as its template filename."""
    names = (
        ("AGENTS.md", agents),  # noqa: CHU006  template-payload filename data
        ("CONTRIBUTING.md", contributing),  # noqa: CHU006  template-payload filename data
        ("README.md", readme),
    )
    for filename, lines in names:
        if lines is not None:
            (root / filename).write_text(
                "\n".join(lines) + "\n", encoding="utf-8",
            )


def _write_faithful_docs(root: Path) -> None:
    _write_docs(
        root,
        agents=_faithful_agents_lines(),
        contributing=_faithful_contributing_lines(),
        readme=_faithful_readme_lines(),
    )


class TestCollectZoneDocDrift:
    def test_faithful_docs_have_no_drift(self, tmp_path: Path) -> None:
        _write_faithful_docs(tmp_path)
        assert collect_zone_doc_drift(tmp_path) == []

    def test_agents_table_missing_tool_owned_row(
        self, tmp_path: Path,
    ) -> None:
        """Dropping the requirements.txt row (the drift class the
        checker exists for) produces a finding naming the entry."""
        agents = [
            line for line in _faithful_agents_lines()
            if "`requirements.txt`" not in line
        ]
        _write_docs(
            tmp_path,
            agents=agents,
            contributing=_faithful_contributing_lines(),
            readme=_faithful_readme_lines(),
        )
        findings = collect_zone_doc_drift(tmp_path)
        assert len(findings) == 1
        assert "requirements.txt" in findings[0]
        assert "'rewrites' row" in findings[0]

    def test_agents_table_leaves_alone_claim_on_tool_owned_path(
        self, tmp_path: Path,
    ) -> None:
        """A tool-owned directory claimed left-alone yields the
        leaves-alone finding and the missing-rewrites-row finding."""
        agents = [
            line if "`examples/`" not in line
            else "| `examples/` | YOU | leaves alone |"
            for line in _faithful_agents_lines()
        ]
        _write_docs(
            tmp_path,
            agents=agents,
            contributing=_faithful_contributing_lines(),
            readme=_faithful_readme_lines(),
        )
        findings = collect_zone_doc_drift(tmp_path)
        assert any(
            "leaves `examples/` alone" in finding for finding in findings
        )
        assert any(
            "no 'rewrites' row" in finding and "examples/" in finding
            for finding in findings
        )

    def test_agents_table_rewrites_row_for_unknown_path(
        self, tmp_path: Path,
    ) -> None:
        agents = [
            *_faithful_agents_lines()[:-3],
            "| `demos/` | NEVER edit | rewrites |",
            *_faithful_agents_lines()[-3:],
        ]
        _write_docs(
            tmp_path,
            agents=agents,
            contributing=_faithful_contributing_lines(),
            readme=_faithful_readme_lines(),
        )
        findings = collect_zone_doc_drift(tmp_path)
        assert len(findings) == 1
        assert "demos/" in findings[0]
        assert "rewrites" in findings[0]

    def test_agents_table_unrecognized_action_cell(
        self, tmp_path: Path,
    ) -> None:
        agents = [
            line if line != "| `run.py` | NEVER edit | rewrites |"
            else "| `run.py` | NEVER edit | sometimes |"
            for line in _faithful_agents_lines()
        ]
        _write_docs(
            tmp_path,
            agents=agents,
            contributing=_faithful_contributing_lines(),
            readme=_faithful_readme_lines(),
        )
        findings = collect_zone_doc_drift(tmp_path)
        assert any(
            "unrecognized action" in finding and "run.py" in finding
            for finding in findings
        )

    def test_agents_missing_ownership_section(self, tmp_path: Path) -> None:
        _write_docs(
            tmp_path,
            agents=["# Workspace guide for agents", "", "No table here."],
            contributing=_faithful_contributing_lines(),
            readme=_faithful_readme_lines(),
        )
        findings = collect_zone_doc_drift(tmp_path)
        assert len(findings) == 1
        assert "File ownership" in findings[0]

    def test_contributing_missing_tool_owned_entry(
        self, tmp_path: Path,
    ) -> None:
        contributing = [
            line.replace("`requirements.txt`,", "")
            for line in _faithful_contributing_lines()
        ]
        _write_docs(
            tmp_path,
            agents=_faithful_agents_lines(),
            contributing=contributing,
            readme=_faithful_readme_lines(),
        )
        findings = collect_zone_doc_drift(tmp_path)
        assert len(findings) == 1
        assert "requirements.txt" in findings[0]
        assert "missing from the 'update only touches' list" in findings[0]

    def test_contributing_stray_token_flagged(self, tmp_path: Path) -> None:
        """A token no zone table recognizes (a retired or misspelled
        path) is flagged, so the prose list cannot quietly keep naming
        a file the zones no longer re-flow."""
        contributing = [
            line.replace("`run.py`,", "`run.py`, `demos/`,")
            for line in _faithful_contributing_lines()
        ]
        _write_docs(
            tmp_path,
            agents=_faithful_agents_lines(),
            contributing=contributing,
            readme=_faithful_readme_lines(),
        )
        findings = collect_zone_doc_drift(tmp_path)
        assert len(findings) == 1
        assert "demos/" in findings[0]
        assert "no zone table recognizes" in findings[0]

    def test_contributing_missing_marker_paragraph(
        self, tmp_path: Path,
    ) -> None:
        _write_docs(
            tmp_path,
            agents=_faithful_agents_lines(),
            contributing=["# Contributing", "", "No update list here."],
            readme=_faithful_readme_lines(),
        )
        findings = collect_zone_doc_drift(tmp_path)
        assert len(findings) == 1
        assert "no paragraph contains" in findings[0]

    def test_readme_bogus_tool_owned_directory_claim(
        self, tmp_path: Path,
    ) -> None:
        readme = [
            *_faithful_readme_lines(),
            "",
            "- `demos/`: more demos.  This folder is tool-owned.",
        ]
        _write_docs(
            tmp_path,
            agents=_faithful_agents_lines(),
            contributing=_faithful_contributing_lines(),
            readme=readme,
        )
        findings = collect_zone_doc_drift(tmp_path)
        assert len(findings) == 1
        assert "demos/" in findings[0]
        assert findings[0].startswith("README.md:")

    def test_missing_doc_is_a_finding(self, tmp_path: Path) -> None:
        """An absent checked doc is drift, not a silent pass, so a
        renamed or dropped doc cannot disable its own check."""
        _write_docs(
            tmp_path,
            agents=_faithful_agents_lines(),
            contributing=_faithful_contributing_lines(),
            readme=None,
        )
        findings = collect_zone_doc_drift(tmp_path)
        assert len(findings) == 1
        assert findings[0].startswith("README.md: missing")


class TestMain:
    def test_exit_zero_on_faithful_docs(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_faithful_docs(tmp_path)
        assert main([str(tmp_path)]) == 0
        assert "match" in capsys.readouterr().out

    def test_exit_one_and_findings_on_stderr_on_drift(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str],
    ) -> None:
        _write_docs(
            tmp_path,
            agents=_faithful_agents_lines(),
            contributing=_faithful_contributing_lines(),
            readme=None,
        )
        assert main([str(tmp_path)]) == 1
        assert "zone-docs:" in capsys.readouterr().err
