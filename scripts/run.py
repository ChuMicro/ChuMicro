"""Repo-level task runner for humans, agents, and CI.

Usage::

    python scripts/run.py <task> [options]

Run without arguments to see available tasks.

Scoped tasks (test, verify-examples, docs) accept::

    python scripts/run.py <task>                    # changed packages only
    python scripts/run.py <task> --all              # all packages
    python scripts/run.py <task> --libraries timing # specific (comma-sep)

test also accepts pytest passthrough::

    python scripts/run.py test -- -k test_name
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from discovery import (
    ROOT,
    coverage_args_for,
    discover_ruff_paths,
    find_publishable_packages,
    parse_scope_args,
    pythonpath_env,
)
from ide import sync_ide
from prepare import VERSIONS, resolve_circuitpython_binary, resolve_micropython_binary
from prepare_circuitpython import prepare_circuitpython as _prepare_circuitpython
from prepare_micropython import prepare_micropython as _prepare_micropython
from scaffold import new_library

PYTHON = sys.executable
SMOKE_SCRIPT = "support/test_harness/run_device_smoke.py"
SMOKE_EXEC = f'exec(open("{SMOKE_SCRIPT}").read())'

TASKS = (
    "setup",
    "sync-ide",
    "new-library",
    "lint",
    "test",
    "verify-examples",
    "docs",
    "build",
    "preflight",
    "prepare-micropython",
    "prepare-circuitpython",
    "test-micropython-compat",
    "test-circuitpython-compat",
    "test-runtime-matrix",
    "test-device",
)


def _run(command: list[str], env: dict[str, str] | None = None) -> int:
    """Run a command from the repo root and return its exit code."""
    printable_command = " ".join(command)
    print(f"+ {printable_command}")
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    return completed.returncode


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def setup() -> int:
    """Install development dependencies and regenerate IDE configuration."""
    cp_version = VERSIONS["circuitpython"]["version"]
    mp_version = VERSIONS["micropython"]["version"].lstrip("v")

    # Static deps from requirements-dev.txt, dynamic stubs appended here.
    dev_packages: list[str] = []
    req_file = ROOT / "requirements-dev.txt"
    if req_file.exists():
        for line in req_file.read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                dev_packages.append(stripped)

    dev_packages.extend([
        f"circuitpython-stubs=={cp_version}",
        f"micropython-esp32-stubs=={mp_version}.*",
    ])

    result = _run([PYTHON, "-m", "pip", "install", "-U", *dev_packages])
    if result != 0:
        return result
    return sync_ide()


def lint() -> int:
    """Run Ruff across all discovered source, test, and script paths."""
    return _run([PYTHON, "-m", "ruff", "check", *discover_ruff_paths()])


def test_host(extra_args: list[str] | None = None) -> int:
    """Run the CPython test suite with optional library scoping.

    Runs pytest separately for each package to avoid test-directory name
    collisions, then combines and reports coverage.  Each library must
    independently meet the coverage threshold (90%) unless passthrough
    args are present (e.g. ``-k`` filters naturally reduce coverage).

    Accepts ``--all``, ``--libraries name,...``, and ``-- <pytest args>``.
    Default (no options): detect changed packages on branch vs origin/main.
    """
    pkg_dirs, passthrough = parse_scope_args(extra_args or [])

    # Keep only packages that actually have a tests/ directory.
    testable = [d for d in pkg_dirs if (d / "tests").is_dir()]
    if not testable:
        print("No test directories found for the selected packages.")
        return 0

    env = pythonpath_env()

    # Clean stale coverage data so combine starts fresh.
    for f in ROOT.glob(".coverage"):
        f.unlink()
    for f in ROOT.glob(".coverage.*"):
        f.unlink()

    # When passthrough args are present (e.g. -k filter), skip per-library
    # coverage gates — filtering naturally reduces coverage.  Otherwise each
    # library must independently meet the threshold from pyproject.toml.
    cov_gate_args = ["--cov-fail-under=0"] if passthrough else []

    overall_rc = 0

    for pkg_dir in testable:
        cov_args = coverage_args_for([pkg_dir])
        test_path = str((pkg_dir / "tests").relative_to(ROOT))

        # Each run writes coverage to a per-library file for later combining.
        run_env = {**env, "COVERAGE_FILE": str(ROOT / f".coverage.{pkg_dir.name}")}

        rc = _run(
            [
                PYTHON, "-m", "pytest",
                "-W", "error",
                *cov_args,
                "--cov-report=",
                *cov_gate_args,
                test_path,
                *passthrough,
            ],
            env=run_env,
        )
        # Exit code 5 means no tests were collected (e.g. -k filter matched
        # nothing in this library) — not an error.
        if rc not in (0, 5):
            overall_rc = rc

    # Combine per-library coverage into one data file and report.
    if list(ROOT.glob(".coverage.*")):
        _run([PYTHON, "-m", "coverage", "combine"])

        report_args = [PYTHON, "-m", "coverage", "report", "--show-missing"]
        if passthrough:
            report_args.append("--fail-under=0")

        report_rc = _run(report_args)
        if report_rc != 0 and overall_rc == 0:
            overall_rc = report_rc

    return overall_rc


def build() -> int:
    """Build all publishable package distributions."""
    packages = find_publishable_packages()
    if not packages:
        print("No publishable packages found (no VERSION + pyproject.toml pairs).")
        return 1

    for package in packages:
        print(f"== build {package} ==")
        result = _run([PYTHON, "-m", "build", package])
        if result != 0:
            print(f"Build failed: {package}")
            return result

    print(f"Built {len(packages)} package(s): {', '.join(packages)}")
    return 0


def verify_examples(extra_args: list[str] | None = None) -> int:
    """Import-check examples to catch broken imports and syntax errors.

    Discovers ``examples/*.py`` in each selected library, then imports each
    module in a subprocess.  Examples must use ``if __name__ == "__main__":``
    guards so that import does not trigger long-running loops.

    Accepts ``--all`` and ``--libraries name,...``.
    Default: detect changed packages on branch vs origin/main.
    """
    pkg_dirs, _ = parse_scope_args(extra_args or [])
    env = pythonpath_env()
    examples: list[tuple[str, Path]] = []

    for pkg_dir in pkg_dirs:
        ex_dir = pkg_dir / "examples"
        if not ex_dir.is_dir():
            continue
        for py_file in sorted(ex_dir.glob("*.py")):
            rel = py_file.relative_to(ROOT)
            examples.append((str(rel), py_file))

    if not examples:
        print("No examples found for the selected packages.")
        return 0

    failures = 0
    for rel_path, py_file in examples:
        rc = _run(
            [PYTHON, "-c", f"import importlib.util, sys; "
             f"spec = importlib.util.spec_from_file_location('_example', '{py_file}'); "
             f"mod = importlib.util.module_from_spec(spec); "
             f"spec.loader.exec_module(mod)"],
            env=env,
        )
        if rc != 0:
            print(f"  FAIL: {rel_path}")
            failures += 1
        else:
            print(f"  OK:   {rel_path}")

    if failures:
        print(f"\n{failures} example(s) failed import check.")
        return 1

    print(f"\nAll {len(examples)} example(s) passed import check.")
    return 0


def docs(extra_args: list[str] | None = None) -> int:
    """Build docs for selected libraries using MkDocs.

    Accepts ``--all``, ``--libraries name,...``, and ``--serve``.
    ``--serve`` starts a live-reload dev server for the first selected library.
    Default: detect changed packages on branch vs origin/main.
    """
    serve = False
    filtered_args: list[str] = []
    for arg in (extra_args or []):
        if arg == "--serve":
            serve = True
        else:
            filtered_args.append(arg)

    pkg_dirs, _ = parse_scope_args(filtered_args)

    # Keep only packages that have a mkdocs.yml
    doc_dirs = [d for d in pkg_dirs if (d / "mkdocs.yml").exists()]
    if not doc_dirs:
        print("No libraries with mkdocs.yml found for the selected packages.")
        return 0

    if serve:
        # Serve the first selected library
        pkg_dir = doc_dirs[0]
        rel = pkg_dir.relative_to(ROOT)
        print(f"Serving docs for {rel} (Ctrl+C to stop)...")
        return _run(
            [PYTHON, "-m", "mkdocs", "serve", "-f", str(pkg_dir / "mkdocs.yml")],
        )

    overall_rc = 0
    for pkg_dir in doc_dirs:
        rel = pkg_dir.relative_to(ROOT)
        site_dir = pkg_dir / "site"
        print(f"== docs {rel} ==")
        rc = _run(
            [PYTHON, "-m", "mkdocs", "build",
             "-f", str(pkg_dir / "mkdocs.yml"),
             "-d", str(site_dir)],
        )
        if rc != 0:
            print(f"Docs build failed: {rel}")
            overall_rc = rc
        else:
            print(f"  Built: {site_dir.relative_to(ROOT)}/")

    return overall_rc


def preflight() -> int:
    """Run the checks that CI requires on every pull request."""
    steps: tuple[tuple[str, object], ...] = (
        ("lint", lambda: lint()),
        ("test", lambda: test_host(["--all"])),
        ("verify-examples", lambda: verify_examples(["--all"])),
        ("build", lambda: build()),
    )

    for step_name, step in steps:
        print(f"== {step_name} ==")
        result = step()
        if result != 0:
            print(f"Preflight failed at: {step_name}")
            return result

    print("Preflight passed — required CI checks should pass.")
    return 0


def prepare_micropython() -> int:
    """Prepare the repo-local MicroPython unix-port runtime."""
    return _prepare_micropython()


def prepare_circuitpython() -> int:
    """Prepare the repo-local CircuitPython unix-port runtime."""
    return _prepare_circuitpython()


def test_micropython_compat() -> int:
    """Run the sample device-test smoke script with the MicroPython Unix binary."""
    micropython_bin = resolve_micropython_binary()
    if micropython_bin is None:
        print("MicroPython binary not found. Preparing unix-port runtime first.")
        prepare_result = prepare_micropython()
        if prepare_result != 0:
            print("MicroPython preparation failed.")
            return prepare_result

        micropython_bin = resolve_micropython_binary()
        if micropython_bin is None:
            print(
                "Preparation completed without the expected binary. "
                "Set MICROPYTHON_BIN and retry."
            )
            return 1

    return _run([micropython_bin, "-c", SMOKE_EXEC])


def test_circuitpython_compat() -> int:
    """Run the shared smoke script with a configured or repo-managed CircuitPython binary."""
    circuitpython_bin = resolve_circuitpython_binary()
    if circuitpython_bin is None:
        print("CircuitPython binary not found. Preparing unix-port runtime first.")
        prepare_result = prepare_circuitpython()
        if prepare_result != 0:
            print("CircuitPython preparation failed.")
            return prepare_result

        circuitpython_bin = resolve_circuitpython_binary()
        if circuitpython_bin is None:
            print(
                "Preparation completed without the expected binary. "
                "Set CIRCUITPYTHON_BIN and retry."
            )
            return 1

    return _run([circuitpython_bin, "-c", SMOKE_EXEC])


def test_runtime_matrix() -> int:
    """Run host tests and compatibility smoke tests across all proven runtimes."""
    steps = (
        ("test", lambda: test_host(["--all"])),
        ("test-micropython-compat", test_micropython_compat),
        ("test-circuitpython-compat", test_circuitpython_compat),
    )

    for step_name, step in steps:
        print(f"== {step_name} ==")
        result = step()
        if result != 0:
            print(f"Step failed: {step_name}")
            return result

    return 0


def test_device() -> int:
    """Point users to the current manual-only device validation path."""
    devices_path = ROOT / "devices.yml"
    if devices_path.exists():
        print(f"Manual device validation remains user-driven. Config: {devices_path}")
    else:
        print(
            "Copy devices.example.yml to devices.yml and fill in your board details."
        )

    print("Use libraries/timing/device_tests/ with support/test_harness/ on the target board.")
    return 2


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

_DISPATCH = {
    "setup": setup,
    "sync-ide": sync_ide,
    "new-library": new_library,
    "lint": lint,
    "test": test_host,
    "verify-examples": verify_examples,
    "docs": docs,
    "build": build,
    "preflight": preflight,
    "prepare-micropython": prepare_micropython,
    "prepare-circuitpython": prepare_circuitpython,
    "test-micropython-compat": test_micropython_compat,
    "test-circuitpython-compat": test_circuitpython_compat,
    "test-runtime-matrix": test_runtime_matrix,
    "test-device": test_device,
}

_USAGE = """\
Usage: {prog} <task> [options]

Tasks: {tasks}

new-library:
  python scripts/run.py new-library <name>   Scaffold a library under libraries/

Scoped tasks (test, verify-examples, docs):
  --all                Run for all packages
  --libraries LIB,...  Run for specific packages (comma-separated names)
  -- PYTEST_ARGS       Forward remaining arguments to pytest (test only)

  Default (no options): detect changed packages on branch vs origin/main.

docs also accepts:
  --serve              Start a live-reload dev server for the first selected library
"""


def main(argv: list[str]) -> int:
    """Dispatch a named repo-level task."""
    if len(argv) < 2 or argv[1] not in _DISPATCH:
        print(_USAGE.format(prog=argv[0], tasks=", ".join(TASKS)))
        return 1

    task_name = argv[1]
    extra_args = argv[2:]

    if task_name in ("test", "new-library", "verify-examples", "docs"):
        return _DISPATCH[task_name](extra_args)

    if extra_args:
        print(f"Task '{task_name}' does not accept extra arguments.")
        return 1

    return _DISPATCH[task_name]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
