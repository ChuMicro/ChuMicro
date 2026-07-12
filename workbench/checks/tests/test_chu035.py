"""Tests for CHU035: example helpers.py byte-identity to the template.

Verifies the silent no-op when the template is absent, the clean pass
when every copy matches, a finding per diverging library copy, the skip
for libraries that ship no helper, and enforcement against the scaffold
payload template.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_checks.rules.chu035 import CHU035

_TEMPLATE_BODY = (
    '"""Standalone wifi-up helper."""\n'
    "\n"
    "def wifi_up():\n"
    "    return None\n"
)

_PAYLOAD_RELPATH = (
    "workbench/workspace/src/chumicro_workspace/"
    "_payloads/library_template/helpers.py.template"
)


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _stage_template(repo_root: Path, body: str = _TEMPLATE_BODY) -> Path:
    return _write(
        repo_root / "scripts" / "templates" / "examples_helpers.py", body,
    )


def _stage_library_helper(repo_root: Path, name: str, body: str) -> Path:
    return _write(
        repo_root / "libraries" / name / "examples" / "helpers.py", body,
    )


def _stage_payload(repo_root: Path, body: str) -> Path:
    return _write(repo_root / _PAYLOAD_RELPATH, body)


class TestSilentNoOp:
    def test_no_template_returns_no_findings(self, tmp_path: Path) -> None:
        _stage_library_helper(tmp_path, "sockets", "drifted\n")
        assert CHU035.check(tmp_path) == []

    def test_matching_copies_pass(self, tmp_path: Path) -> None:
        _stage_template(tmp_path)
        _stage_library_helper(tmp_path, "sockets", _TEMPLATE_BODY)
        _stage_payload(tmp_path, _TEMPLATE_BODY)
        assert CHU035.check(tmp_path) == []

    def test_library_without_helper_is_skipped(self, tmp_path: Path) -> None:
        _stage_template(tmp_path)
        # A library dir with an examples/ but no helpers.py: no finding.
        (tmp_path / "libraries" / "timing" / "examples").mkdir(parents=True)
        _stage_library_helper(tmp_path, "sockets", _TEMPLATE_BODY)
        assert CHU035.check(tmp_path) == []


class TestLibraryCopyDrift:
    def test_diverging_library_helper_flagged(self, tmp_path: Path) -> None:
        _stage_template(tmp_path)
        _stage_library_helper(tmp_path, "mqtt", _TEMPLATE_BODY + "# drift\n")
        findings = CHU035.check(tmp_path)
        assert len(findings) == 1
        assert findings[0].code == "CHU035"
        assert "libraries/mqtt/examples/helpers.py" in findings[0].message
        assert "examples_helpers.py" in findings[0].message

    def test_each_diverging_copy_flagged_individually(
        self, tmp_path: Path,
    ) -> None:
        _stage_template(tmp_path)
        _stage_library_helper(tmp_path, "mqtt", "one drift\n")
        _stage_library_helper(tmp_path, "requests", "another drift\n")
        _stage_library_helper(tmp_path, "sockets", _TEMPLATE_BODY)
        findings = CHU035.check(tmp_path)
        assert len(findings) == 2
        flagged = " ".join(finding.message for finding in findings)
        assert "libraries/mqtt/examples/helpers.py" in flagged
        assert "libraries/requests/examples/helpers.py" in flagged
        assert "libraries/sockets" not in flagged

    def test_finding_points_at_line_one(self, tmp_path: Path) -> None:
        _stage_template(tmp_path)
        _stage_library_helper(tmp_path, "ntp", "drift\n")
        findings = CHU035.check(tmp_path)
        assert findings[0].line == 1


class TestScaffoldPayloadDrift:
    def test_diverging_payload_template_flagged(self, tmp_path: Path) -> None:
        _stage_template(tmp_path)
        _stage_payload(tmp_path, _TEMPLATE_BODY + "# stale scaffold\n")
        findings = CHU035.check(tmp_path)
        assert len(findings) == 1
        assert _PAYLOAD_RELPATH in findings[0].message

    def test_matching_payload_template_clean(self, tmp_path: Path) -> None:
        _stage_template(tmp_path)
        _stage_payload(tmp_path, _TEMPLATE_BODY)
        assert CHU035.check(tmp_path) == []
