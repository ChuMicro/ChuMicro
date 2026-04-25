"""Manual regression audit for pre-merge gates.

Builds deliberately-bad inputs against each gate and confirms the gate
fires.  Catches the class of regression where a gate silently passes
when it shouldn't — e.g. the griffe absolute-``--search`` no-op that
went undetected for the entire life of ``check_api`` before commit
``5578026``.  Mocked unit tests can't see this class of bug because
the subprocess (or its exit code) is replaced.

Run on demand::

    python scripts/audit_gates.py

Exit code 0 if every scenario behaved as expected; 1 otherwise.

Not wired into CI or the unit-test suite — temp-repo construction +
real subprocess calls add 5–10 s, which would dominate the otherwise
fast ``test-scripts`` suite.  Run this before structural changes to
``scripts/`` that touch any gate, and after upgrading griffe / ruff /
pytest / mpy-cross.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# scripts/ is sys.path[0] when invoked as ``python scripts/audit_gates.py``,
# so its siblings (check_api, check_version, …) import as bare modules.
import check_api
import check_version
import verify_examples
import workspace

SCRIPTS_DIR = Path(__file__).resolve().parent
ROOT = SCRIPTS_DIR.parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"


@contextmanager
def _tmp_dir(label: str) -> Iterator[Path]:
    """Yield a fresh tmp directory; clean it up unconditionally."""
    path = Path(tempfile.mkdtemp(prefix=f"audit-{label}-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _python(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Run a Python subprocess with the venv interpreter when available."""
    interpreter = str(VENV_PYTHON if VENV_PYTHON.exists() else sys.executable)
    return subprocess.run(
        [interpreter, *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _git(repo: Path, *arguments: str) -> None:
    """Run a deterministic git command in *repo*; raises on non-zero."""
    subprocess.run(
        ["git", "-C", str(repo), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env={
            "PATH": shutil.os.environ.get("PATH", ""),
            "GIT_AUTHOR_NAME": "audit",
            "GIT_AUTHOR_EMAIL": "audit@test",
            "GIT_COMMITTER_NAME": "audit",
            "GIT_COMMITTER_EMAIL": "audit@test",
        },
    )


def _seed_publishable_repo(
    workdir: Path,
    *,
    parent: str,
    name: str,
    initial_version: str = "0.1.0",
    tag_initial: bool = True,
) -> Path:
    """Build a minimal git repo holding one publishable package.

    Returns the repo path.  HEAD is on a ``feature`` branch off ``main``
    so callers can layer additional commits to diff against.
    """
    repo = workdir / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet", "-b", "main")
    src_pkg = repo / parent / name / "src" / f"chumicro_{name}"
    src_pkg.mkdir(parents=True)
    (src_pkg / "__init__.py").write_text(
        "def stable() -> int:\n"
        "    return 1\n"
        "\n\n"
        "def soon_removed() -> int:\n"
        "    return 2\n"
    )
    (repo / parent / name / "VERSION").write_text(f"{initial_version}\n")
    (repo / parent / name / "pyproject.toml").write_text(
        f'[project]\nname = "chumicro-{name}"\nversion = "{initial_version}"\n'
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "--quiet", "-m", "initial")
    if tag_initial:
        _git(repo, "tag", f"chumicro-{name}-v{initial_version}")
    _git(repo, "checkout", "--quiet", "-b", "feature")
    return repo


# ---------------------------------------------------------------------------
# Scenario harness
# ---------------------------------------------------------------------------

Result = tuple[str, bool, str]
"""(label, ok, evidence) — *ok* is True when the gate fired as expected."""


def _scenario(label: str, ok: bool, evidence: str) -> Result:
    return (label, ok, evidence)


# ---------------------------------------------------------------------------
# check_names — CHU001 (single-letter / abbreviation)
# ---------------------------------------------------------------------------


def audit_check_names_single_letter() -> Result:
    with _tmp_dir("names1") as workdir:
        bad = workdir / "bad.py"
        bad.write_text("def setup() -> int:\n    x = 1\n    return x\n")
        result = _python(str(SCRIPTS_DIR / "check_names.py"), str(bad))
    output = result.stdout + result.stderr
    fired = result.returncode != 0 and "CHU001" in output
    return _scenario("check_names CHU001 (single-letter)", fired, output.strip())


def audit_check_names_abbreviation() -> Result:
    with _tmp_dir("names2") as workdir:
        bad = workdir / "bad.py"
        bad.write_text(
            "def setup() -> bytearray:\n"
            "    buf = bytearray(8)\n"
            "    return buf\n"
        )
        result = _python(str(SCRIPTS_DIR / "check_names.py"), str(bad))
    output = result.stdout + result.stderr
    fired = result.returncode != 0 and "CHU001" in output and "buf" in output
    return _scenario("check_names CHU001 (abbreviation)", fired, output.strip())


# ---------------------------------------------------------------------------
# check_whitespace — CHU002 / CHU004
# ---------------------------------------------------------------------------


def audit_check_whitespace_no_trailing_newline() -> Result:
    with _tmp_dir("ws1") as workdir:
        bad = workdir / "bad.py"
        bad.write_text("value = 1")  # no trailing newline at all
        result = _python(str(SCRIPTS_DIR / "check_whitespace.py"), str(bad))
    output = result.stdout + result.stderr
    fired = result.returncode != 0 and "CHU002" in output
    return _scenario("check_whitespace CHU002 (no final newline)", fired, output.strip())


def audit_check_whitespace_trailing_space() -> Result:
    with _tmp_dir("ws2") as workdir:
        bad = workdir / "bad.py"
        bad.write_text("value = 1  \n")  # trailing whitespace
        result = _python(str(SCRIPTS_DIR / "check_whitespace.py"), str(bad))
    output = result.stdout + result.stderr
    fired = result.returncode != 0 and "CHU004" in output
    return _scenario("check_whitespace CHU004 (trailing whitespace)", fired, output.strip())


# ---------------------------------------------------------------------------
# ruff lint — F401 unused import
# ---------------------------------------------------------------------------


def audit_ruff_unused_import() -> Result:
    with _tmp_dir("ruff") as workdir:
        bad = workdir / "bad.py"
        bad.write_text("import os\n\n\ndef setup() -> int:\n    return 1\n")
        result = _python("-m", "ruff", "check", str(bad))
    output = result.stdout + result.stderr
    fired = result.returncode != 0 and "F401" in output
    return _scenario("ruff F401 (unused import)", fired, output.strip())


def audit_ruff_clean_passes() -> Result:
    """Sanity counterpart: clean code should pass ruff with exit 0."""
    with _tmp_dir("ruff-clean") as workdir:
        good = workdir / "good.py"
        good.write_text(
            'def setup() -> int:\n'
            '    """Module docstring."""\n'
            '    return 1\n'
        )
        result = _python("-m", "ruff", "check", str(good))
    output = result.stdout + result.stderr
    fired = result.returncode == 0
    return _scenario("ruff (clean code passes)", fired, output.strip() or "(no output)")


# ---------------------------------------------------------------------------
# ruff TID252 — banned-relative-imports in device-code trees
# ---------------------------------------------------------------------------


_TID252_PYPROJECT = (
    '[tool.ruff.lint]\n'
    'select = ["TID252"]\n'
    '\n'
    '[tool.ruff.lint.flake8-tidy-imports]\n'
    'ban-relative-imports = "all"\n'
    '\n'
    '[tool.ruff.lint.per-file-ignores]\n'
    '"workbench/**" = ["TID252"]\n'
    '"scripts/**" = ["TID252"]\n'
    '"**/tests/**" = ["TID252"]\n'
    '"**/functional_tests/**" = ["TID252"]\n'
    '"**/examples/**" = ["TID252"]\n'
)


def audit_ruff_tid252_libraries_src_fails() -> Result:
    """A relative import in libraries/*/src/ must trip TID252."""
    with _tmp_dir("tid-lib") as workdir:
        (workdir / "pyproject.toml").write_text(_TID252_PYPROJECT)
        bad = workdir / "libraries/timing/src/chumicro_timing/__init__.py"
        bad.parent.mkdir(parents=True)
        bad.write_text("from .core import something\n")
        result = _python("-m", "ruff", "check", str(bad))
    output = result.stdout + result.stderr
    fired = result.returncode != 0 and "TID252" in output
    return _scenario(
        "ruff TID252 (relative import in libraries/*/src/ → fail)",
        fired,
        output.strip(),
    )


def audit_ruff_tid252_test_harness_src_fails() -> Result:
    """A relative import in support/test_harness/src/ must trip TID252.

    The test harness is the *other* tree that gets exec()'d on device,
    so the constraint applies identically.
    """
    with _tmp_dir("tid-th") as workdir:
        (workdir / "pyproject.toml").write_text(_TID252_PYPROJECT)
        bad = workdir / "support/test_harness/src/chumicro_test_harness/__init__.py"
        bad.parent.mkdir(parents=True)
        bad.write_text("from .core import something\n")
        result = _python("-m", "ruff", "check", str(bad))
    output = result.stdout + result.stderr
    fired = result.returncode != 0 and "TID252" in output
    return _scenario(
        "ruff TID252 (relative import in support/test_harness/src/ → fail)",
        fired,
        output.strip(),
    )


def audit_ruff_tid252_workbench_src_passes() -> Result:
    """workbench/*/src/ is host-only and may keep relative imports."""
    with _tmp_dir("tid-wb") as workdir:
        (workdir / "pyproject.toml").write_text(_TID252_PYPROJECT)
        good = workdir / "workbench/deploy/src/chumicro_deploy/__init__.py"
        good.parent.mkdir(parents=True)
        good.write_text("from .core import something\n")
        result = _python("-m", "ruff", "check", str(good))
    output = result.stdout + result.stderr
    fired = result.returncode == 0 and "TID252" not in output
    return _scenario(
        "ruff TID252 (relative import in workbench/*/src/ → allowed)",
        fired,
        output.strip() or "(no violations)",
    )


def audit_ruff_tid252_libraries_tests_passes() -> Result:
    """libraries/*/tests/ is host-side and may keep relative imports."""
    with _tmp_dir("tid-test") as workdir:
        (workdir / "pyproject.toml").write_text(_TID252_PYPROJECT)
        good = workdir / "libraries/timing/tests/test_thing.py"
        good.parent.mkdir(parents=True)
        good.write_text("from .core import something\n")
        result = _python("-m", "ruff", "check", str(good))
    output = result.stdout + result.stderr
    fired = result.returncode == 0 and "TID252" not in output
    return _scenario(
        "ruff TID252 (relative import in libraries/*/tests/ → allowed)",
        fired,
        output.strip() or "(no violations)",
    )


# ---------------------------------------------------------------------------
# verify_examples — broken import
# ---------------------------------------------------------------------------


def audit_verify_examples_broken_import() -> Result:
    """A broken ``import`` in an example must fail the gate.

    verify_examples uses ``importlib.import_module`` to resolve every
    non-platform import, then ``hasattr`` to confirm specific symbols
    are present.  A nonsense module name should trip the resolver.
    """
    with _tmp_dir("examples") as workdir:
        pkg = workdir / "fake-pkg"
        (pkg / "examples").mkdir(parents=True)
        (pkg / "examples" / "broken.py").write_text(
            "import zzz_nonexistent_module_xyz\n"
        )
        # verify_examples computes relative_to(ROOT); patch so it points
        # at our workdir for the duration of this scenario.
        monkey_root = workdir
        old_workspace_root = workspace.ROOT
        old_module_root = verify_examples.ROOT
        workspace.ROOT = monkey_root
        verify_examples.ROOT = monkey_root
        try:
            from io import StringIO
            buffer = StringIO()
            old_stdout = sys.stdout
            sys.stdout = buffer
            try:
                exit_code = verify_examples.verify_examples([pkg])
            finally:
                sys.stdout = old_stdout
            output = buffer.getvalue()
        finally:
            workspace.ROOT = old_workspace_root
            verify_examples.ROOT = old_module_root
    fired = exit_code != 0 and "FAIL" in output
    return _scenario("verify_examples (broken import)", fired, output.strip())


# ---------------------------------------------------------------------------
# check_version — workbench src change without VERSION bump
# ---------------------------------------------------------------------------


def audit_check_version_workbench_no_bump() -> Result:
    with _tmp_dir("ver1") as workdir:
        repo = _seed_publishable_repo(workdir, parent="workbench", name="deploy")
        init = repo / "workbench/deploy/src/chumicro_deploy/__init__.py"
        init.write_text(init.read_text() + "\n# touched\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "--quiet", "-m", "src change without bump")

        old_root = workspace.ROOT
        workspace.ROOT = repo
        try:
            from io import StringIO
            buffer = StringIO()
            old_stdout = sys.stdout
            sys.stdout = buffer
            try:
                exit_code = check_version._check("main")
            finally:
                sys.stdout = old_stdout
            output = buffer.getvalue()
        finally:
            workspace.ROOT = old_root
    fired = exit_code == 1 and "FAIL: workbench/deploy/" in output
    return _scenario(
        "check_version workbench (src no-bump → fail)", fired, output.strip()
    )


def audit_check_version_workbench_with_bump_passes() -> Result:
    with _tmp_dir("ver2") as workdir:
        repo = _seed_publishable_repo(workdir, parent="workbench", name="deploy")
        init = repo / "workbench/deploy/src/chumicro_deploy/__init__.py"
        init.write_text(init.read_text() + "\n# touched\n")
        (repo / "workbench/deploy/VERSION").write_text("0.1.1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "--quiet", "-m", "src change with bump")

        old_root = workspace.ROOT
        workspace.ROOT = repo
        try:
            from io import StringIO
            buffer = StringIO()
            old_stdout = sys.stdout
            sys.stdout = buffer
            try:
                exit_code = check_version._check("main")
            finally:
                sys.stdout = old_stdout
            output = buffer.getvalue()
        finally:
            workspace.ROOT = old_root
    fired = exit_code == 0 and "OK: workbench/deploy/" in output
    return _scenario(
        "check_version workbench (src + bump → pass)", fired, output.strip()
    )


# ---------------------------------------------------------------------------
# check_api — real griffe subprocess against a real tag
# ---------------------------------------------------------------------------


def audit_check_api_workbench_breakage_patch_fails() -> Result:
    """0.x breakages need a *minor* bump (Decision 0020); patch fails."""
    with _tmp_dir("api1") as workdir:
        repo = _seed_publishable_repo(workdir, parent="workbench", name="deploy")
        init = repo / "workbench/deploy/src/chumicro_deploy/__init__.py"
        init.write_text("def stable() -> int:\n    return 1\n")  # soon_removed gone
        (repo / "workbench/deploy/VERSION").write_text("0.1.1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "--quiet", "-m", "remove symbol; patch bump")

        old_workspace_root = workspace.ROOT
        old_module_root = check_api.ROOT
        workspace.ROOT = repo
        check_api.ROOT = repo
        try:
            from io import StringIO
            buffer = StringIO()
            old_stdout = sys.stdout
            sys.stdout = buffer
            try:
                exit_code = check_api._check("main")
            finally:
                sys.stdout = old_stdout
            output = buffer.getvalue()
        finally:
            workspace.ROOT = old_workspace_root
            check_api.ROOT = old_module_root
    fired = (
        exit_code == 1
        and "FAIL: workbench/deploy" in output
        and "soon_removed" in output
    )
    return _scenario(
        "check_api workbench (breakage + patch → fail)", fired, output.strip()
    )


def audit_check_api_workbench_breakage_minor_passes() -> Result:
    """Same removal with a minor bump clears the 0.x gate."""
    with _tmp_dir("api2") as workdir:
        repo = _seed_publishable_repo(workdir, parent="workbench", name="deploy")
        init = repo / "workbench/deploy/src/chumicro_deploy/__init__.py"
        init.write_text("def stable() -> int:\n    return 1\n")
        (repo / "workbench/deploy/VERSION").write_text("0.2.0\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "--quiet", "-m", "remove symbol; minor bump")

        old_workspace_root = workspace.ROOT
        old_module_root = check_api.ROOT
        workspace.ROOT = repo
        check_api.ROOT = repo
        try:
            from io import StringIO
            buffer = StringIO()
            old_stdout = sys.stdout
            sys.stdout = buffer
            try:
                exit_code = check_api._check("main")
            finally:
                sys.stdout = old_stdout
            output = buffer.getvalue()
        finally:
            workspace.ROOT = old_workspace_root
            check_api.ROOT = old_module_root
    fired = exit_code == 0 and "minor bump sufficient" in output
    return _scenario(
        "check_api workbench (breakage + minor → pass)", fired, output.strip()
    )


def audit_check_api_libraries_breakage_patch_fails() -> Result:
    """Same shape as the workbench audit, against the libraries/ arm.

    Confirms the absolute-vs-relative ``--search`` fix from commit
    ``5578026`` is also live for libraries — not just workbench.
    """
    with _tmp_dir("api3") as workdir:
        repo = _seed_publishable_repo(workdir, parent="libraries", name="timing")
        init = repo / "libraries/timing/src/chumicro_timing/__init__.py"
        init.write_text("def stable() -> int:\n    return 1\n")
        (repo / "libraries/timing/VERSION").write_text("0.1.1\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "--quiet", "-m", "remove symbol; patch bump")

        old_workspace_root = workspace.ROOT
        old_module_root = check_api.ROOT
        workspace.ROOT = repo
        check_api.ROOT = repo
        try:
            from io import StringIO
            buffer = StringIO()
            old_stdout = sys.stdout
            sys.stdout = buffer
            try:
                exit_code = check_api._check("main")
            finally:
                sys.stdout = old_stdout
            output = buffer.getvalue()
        finally:
            workspace.ROOT = old_workspace_root
            check_api.ROOT = old_module_root
    fired = (
        exit_code == 1
        and "FAIL: libraries/timing" in output
        and "soon_removed" in output
    )
    return _scenario(
        "check_api libraries (breakage + patch → fail)", fired, output.strip()
    )


# ---------------------------------------------------------------------------
# Known gaps — reported separately, not pass/fail
# ---------------------------------------------------------------------------


KNOWN_GAPS: list[str] = []
"""AGENTS.md rules with no static pre-merge gate.  Empty for now —
ruff TID252 was added to cover the libraries/* + support/test_harness/
absolute-imports rule (commit 04074c2's follow-up)."""


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


SCENARIOS: list = [
    audit_check_names_single_letter,
    audit_check_names_abbreviation,
    audit_check_whitespace_no_trailing_newline,
    audit_check_whitespace_trailing_space,
    audit_ruff_unused_import,
    audit_ruff_clean_passes,
    audit_ruff_tid252_libraries_src_fails,
    audit_ruff_tid252_test_harness_src_fails,
    audit_ruff_tid252_workbench_src_passes,
    audit_ruff_tid252_libraries_tests_passes,
    audit_verify_examples_broken_import,
    audit_check_version_workbench_no_bump,
    audit_check_version_workbench_with_bump_passes,
    audit_check_api_workbench_breakage_patch_fails,
    audit_check_api_workbench_breakage_minor_passes,
    audit_check_api_libraries_breakage_patch_fails,
]


def main() -> int:
    print(f"Running {len(SCENARIOS)} gate-audit scenarios...\n")
    results: list[Result] = []
    for scenario_fn in SCENARIOS:
        try:
            result = scenario_fn()
        except Exception as error:  # noqa: BLE001 - audit must continue past one failure
            results.append(
                (scenario_fn.__name__, False, f"crashed: {error!r}")
            )
            continue
        results.append(result)

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed

    width = max(len(label) for label, _, _ in results) + 2
    for label, ok, evidence in results:
        marker = "OK  " if ok else "FAIL"
        print(f"  [{marker}] {label.ljust(width)}", end="")
        if not ok:
            evidence_line = evidence.splitlines()[0] if evidence else "(no output)"
            print(f"  ← {evidence_line}")
        else:
            print()

    print()
    print(f"Summary: {passed}/{len(results)} scenarios behaved as expected.")

    if KNOWN_GAPS:
        print("\nKnown unenforced rules (informational):")
        for gap in KNOWN_GAPS:
            print(f"  - {gap}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
