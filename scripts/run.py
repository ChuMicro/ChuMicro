"""Repo-level task runner for humans, agents, and CI.

Usage::

    python scripts/run.py <task> [options]

Run without arguments to see available tasks.

test options::

    python scripts/run.py test                    # changed packages only
    python scripts/run.py test --all              # all packages
    python scripts/run.py test --libraries timing # specific (comma-sep)
    python scripts/run.py test -- -k test_name    # pytest passthrough
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TOOLS = ROOT / ".tools"

PYTHON = sys.executable
SMOKE_SCRIPT = "ci/run_sample_device_smoke.py"
SMOKE_EXEC = f'exec(open("{SMOKE_SCRIPT}").read())'


# ---------------------------------------------------------------------------
# Auto-discovery helpers
# ---------------------------------------------------------------------------


def _discover_package_dirs() -> list[Path]:
    """Find directories under support/ and libraries/ that contain a pyproject.toml."""
    dirs: list[Path] = []
    for parent in [ROOT / "support", ROOT / "libraries"]:
        if not parent.is_dir():
            continue
        for child in sorted(parent.iterdir()):
            if child.is_dir() and (child / "pyproject.toml").exists():
                dirs.append(child)
    return dirs


def _discover_source_roots() -> list[Path]:
    """Return src/ directories for all discovered packages."""
    return [d / "src" for d in _discover_package_dirs() if (d / "src").is_dir()]


def _discover_ruff_paths() -> list[str]:
    """Return paths to lint across the workspace."""
    paths = ["ci", "scripts"]
    for pkg_dir in _discover_package_dirs():
        rel = str(pkg_dir.relative_to(ROOT))
        for subdir in ["src", "tests", "device_tests"]:
            if (pkg_dir / subdir).is_dir():
                paths.append(f"{rel}/{subdir}")
    return paths


def _coverage_args_for(pkg_dirs: list[Path]) -> list[str]:
    """Return ``--cov`` arguments for importable packages under *pkg_dirs*."""
    args: list[str] = []
    for pkg_dir in pkg_dirs:
        src = pkg_dir / "src"
        if not src.is_dir():
            continue
        for pkg in sorted(src.iterdir()):
            if (
                pkg.is_dir()
                and (pkg / "__init__.py").exists()
                and not pkg.name.endswith(".egg-info")
            ):
                args.extend(["--cov", str(pkg.relative_to(ROOT))])
    return args



def _resolve_named_packages(names: list[str]) -> list[Path]:
    """Resolve package names to directories.

    Accepts bare names (e.g. ``timing``) or relative paths
    (e.g. ``libraries/timing``).
    """
    all_dirs = _discover_package_dirs()
    by_name = {d.name: d for d in all_dirs}
    by_rel = {str(d.relative_to(ROOT)): d for d in all_dirs}

    resolved: list[Path] = []
    for name in names:
        if name in by_rel:
            resolved.append(by_rel[name])
        elif name in by_name:
            resolved.append(by_name[name])
        else:
            available = ", ".join(sorted(by_name.keys()))
            print(f"Unknown package: {name}")
            print(f"Available: {available}")
            return []
    return resolved


def _detect_changed_packages() -> list[Path] | None:
    """Detect packages affected by changes on this branch vs origin/main.

    Returns a list of package directories, or ``None`` when all tests
    should run (infrastructure changed, git unavailable, or no diff).
    """
    try:
        changed: set[str] = set()
        for cmd in (
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            ["git", "diff", "--name-only"],
            ["git", "diff", "--name-only", "--cached"],
        ):
            result = subprocess.run(
                cmd, capture_output=True, text=True, cwd=ROOT, check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                changed.update(result.stdout.strip().splitlines())
    except (FileNotFoundError, OSError):
        return None

    if not changed:
        return None

    # Infrastructure changes → run everything
    for path in changed:
        if path in ("conftest.py", "pyproject.toml"):
            return None
        if path.startswith(("scripts/", "ci/", ".github/")):
            return None

    # Extract unique package dirs from changed file paths
    packages: set[Path] = set()
    for path in changed:
        for prefix in ("libraries/", "support/"):
            if path.startswith(prefix):
                parts = path.split("/")
                if len(parts) >= 2:
                    pkg_dir = ROOT / parts[0] / parts[1]
                    if pkg_dir.is_dir() and (pkg_dir / "pyproject.toml").exists():
                        packages.add(pkg_dir)

    return sorted(packages) if packages else None


def _parse_test_args(
    extra_args: list[str],
) -> tuple[list[Path], list[str]]:
    """Parse ``test`` arguments into a package scope and pytest passthrough.

    Returns ``(pkg_dirs, passthrough)``.
    """
    scope: str | list[str] = "changed"
    passthrough: list[str] = []

    i = 0
    while i < len(extra_args):
        arg = extra_args[i]
        if arg == "--all":
            scope = "all"
            i += 1
        elif arg == "--libraries":
            i += 1
            if i >= len(extra_args):
                print("--libraries requires a comma-separated list of package names.")
                raise SystemExit(1)
            scope = [n.strip() for n in extra_args[i].split(",") if n.strip()]
            i += 1
        elif arg == "--":
            passthrough = extra_args[i + 1 :]
            break
        else:
            passthrough = extra_args[i:]
            break

    # Resolve scope → list[Path]
    if scope == "all":
        return _discover_package_dirs(), passthrough

    if isinstance(scope, list):
        resolved = _resolve_named_packages(scope)
        if not resolved:
            raise SystemExit(1)
        return resolved, passthrough

    # "changed" — detect from git
    detected = _detect_changed_packages()
    if detected is None:
        print("Running all tests (no branch diff or infrastructure changed).")
        return _discover_package_dirs(), passthrough

    names = ", ".join(d.name for d in detected)
    print(f"Changed packages detected: {names}")
    return detected, passthrough


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

TASKS = (
    "setup",
    "sync-ide",
    "new-library",
    "lint",
    "test",
    "build",
    "preflight",
    "prepare-micropython",
    "prepare-circuitpython",
    "test-micropython-compat",
    "test-circuitpython-compat",
    "test-runtime-matrix",
    "test-device",
)


def _pythonpath_env() -> dict[str, str]:
    """Return an environment with the repo source roots prepended to PYTHONPATH."""
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH")
    path_entries = [str(path) for path in _discover_source_roots()]
    if existing_path:
        path_entries.append(existing_path)

    env["PYTHONPATH"] = os.pathsep.join(path_entries)
    return env


def _run(command: list[str], env: dict[str, str] | None = None) -> int:
    """Run a command from the repo root and return its exit code."""
    printable_command = " ".join(command)
    print(f"+ {printable_command}")
    completed = subprocess.run(command, cwd=ROOT, env=env, check=False)
    return completed.returncode


def _read_prepared_binary(marker_name: str) -> str | None:
    """Read a binary path from a marker file written by a ci/prepare_*.py script."""
    marker = _TOOLS / marker_name
    if not marker.exists():
        return None
    candidate = Path(marker.read_text().strip())
    if candidate.exists():
        return str(candidate)
    return None


def _resolve_micropython_binary() -> str | None:
    """Resolve a MicroPython binary from env vars, repo-local tools, or PATH."""
    configured_path = os.environ.get("MICROPYTHON_BIN")
    if configured_path:
        return configured_path

    prepared = _read_prepared_binary("micropython.path")
    if prepared:
        return prepared

    return shutil.which("micropython")


def _resolve_circuitpython_binary() -> str | None:
    """Resolve a CircuitPython binary from env vars, repo-local tools, or PATH."""
    configured_path = os.environ.get("CIRCUITPYTHON_BIN")
    if configured_path:
        return configured_path

    prepared = _read_prepared_binary("circuitpython.path")
    if prepared:
        return prepared

    return shutil.which("circuitpython")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


def setup() -> int:
    """Install development dependencies and regenerate IDE configuration."""
    dev_packages = ["pip", "pytest", "pytest-cov", "ruff", "build"]
    result = _run([PYTHON, "-m", "pip", "install", "-U", *dev_packages])
    if result != 0:
        return result
    return sync_ide()


# ---------------------------------------------------------------------------
# IDE configuration generation
# ---------------------------------------------------------------------------


def _sync_pycharm_iml() -> None:
    """Regenerate .idea/chumicro.iml source roots from the workspace structure."""
    iml_path = ROOT / ".idea" / "chumicro.iml"

    # Preserve the existing SDK reference so users keep their interpreter setting.
    jdk_line = ""
    if iml_path.exists():
        for line in iml_path.read_text().splitlines():
            if 'type="jdk"' in line:
                jdk_line = line
                break

    source_lines: list[str] = []
    for pkg_dir in _discover_package_dirs():
        rel = pkg_dir.relative_to(ROOT)
        for subdir, is_test in [("src", "false"), ("tests", "true"), ("device_tests", "true")]:
            if (pkg_dir / subdir).is_dir():
                source_lines.append(
                    f'      <sourceFolder url="file://$MODULE_DIR$/{rel}/{subdir}"'
                    f' isTestSource="{is_test}" />'
                )

    sources = "\n".join(source_lines)
    jdk_entry = f"\n{jdk_line}" if jdk_line else ""
    content = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<module type="PYTHON_MODULE" version="4">\n'
        '  <component name="NewModuleRootManager">\n'
        '    <content url="file://$MODULE_DIR$">\n'
        f"{sources}\n"
        '      <excludeFolder url="file://$MODULE_DIR$/.venv" />\n'
        '      <excludeFolder url="file://$MODULE_DIR$/.tools" />\n'
        "    </content>{jdk}\n"
        '    <orderEntry type="sourceFolder" forTests="false" />\n'
        "  </component>\n"
        "</module>\n"
    ).format(jdk=jdk_entry)

    iml_path.parent.mkdir(parents=True, exist_ok=True)
    iml_path.write_text(content)
    print(f"  Updated {iml_path.relative_to(ROOT)}")


def _sync_pyrightconfig() -> None:
    """Regenerate pyrightconfig.json extraPaths from the workspace structure."""
    config_path = ROOT / "pyrightconfig.json"

    # Preserve any existing user settings; only overwrite extraPaths.
    if config_path.exists():
        config = json.loads(config_path.read_text())
    else:
        config = {}

    config["extraPaths"] = [
        str(r.relative_to(ROOT)) for r in _discover_source_roots()
    ]

    config_path.write_text(json.dumps(config, indent=2) + "\n")
    print(f"  Updated {config_path.relative_to(ROOT)}")


def sync_ide() -> int:
    """Regenerate IDE configuration files from the workspace structure."""
    _sync_pycharm_iml()
    _sync_pyrightconfig()
    return 0


# ---------------------------------------------------------------------------
# Library scaffolding
# ---------------------------------------------------------------------------

_PYPROJECT_TEMPLATE = """\
[build-system]
requires = ["setuptools>=69", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "chumicro-{name}"
dynamic = ["version"]
description = ""
readme = "README.md"
requires-python = ">=3.11"
license = "MIT"
authors = [
    {{ name = "Chumicro" }},
]
classifiers = [
    "Development Status :: 2 - Pre-Alpha",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3 :: Only",
]

[tool.setuptools]
package-dir = {{"" = "src"}}

[tool.setuptools.dynamic]
version = {{file = "VERSION"}}

[tool.setuptools.packages.find]
where = ["src"]
"""


def _scaffold_library(name: str) -> int:
    """Create the directory structure and template files for a new library."""
    import_name = f"chumicro_{name.replace('-', '_')}"
    lib_dir = ROOT / "libraries" / name

    if lib_dir.exists():
        print(f"Directory already exists: libraries/{name}")
        return 1

    # Create directory tree
    (lib_dir / "src" / import_name).mkdir(parents=True)
    (lib_dir / "tests").mkdir()

    # VERSION
    (lib_dir / "VERSION").write_text("0.1.0\n")

    # pyproject.toml
    (lib_dir / "pyproject.toml").write_text(_PYPROJECT_TEMPLATE.format(name=name))

    # README
    (lib_dir / "README.md").write_text(f"# chumicro-{name}\n")

    # Package __init__.py
    (lib_dir / "src" / import_name / "__init__.py").write_text(
        f'"""Public exports for the chumicro-{name} package."""\n'
    )

    # Tests conftest.py (no __init__.py — avoids module name collisions across libraries)
    (lib_dir / "tests" / "conftest.py").write_text(
        f'"""Test configuration for the chumicro-{name} package."""\n'
    )


    print(f"Created libraries/{name}/")
    return 0


def new_library(extra_args: list[str] | None = None) -> int:
    """Scaffold a new library under libraries/ and regenerate IDE configs.

    Usage: ``python scripts/run.py new-library <name>``
    """
    args = extra_args or []
    if len(args) != 1 or args[0].startswith("-"):
        print("Usage: python scripts/run.py new-library <name>")
        print("Example: python scripts/run.py new-library gpio")
        return 1

    name = args[0]
    result = _scaffold_library(name)
    if result != 0:
        return result

    return sync_ide()


def lint() -> int:
    """Run Ruff across all discovered source, test, and script paths."""
    return _run([PYTHON, "-m", "ruff", "check", *_discover_ruff_paths()])


def test_host(extra_args: list[str] | None = None) -> int:
    """Run the CPython test suite with optional library scoping.

    Runs pytest separately for each package to avoid test-directory name
    collisions, then combines and reports coverage.  Each library must
    independently meet the coverage threshold (90%) unless passthrough
    args are present (e.g. ``-k`` filters naturally reduce coverage).

    Accepts ``--all``, ``--libraries name,...``, and ``-- <pytest args>``.
    Default (no options): detect changed packages on branch vs origin/main.
    """
    pkg_dirs, passthrough = _parse_test_args(extra_args or [])

    # Keep only packages that actually have a tests/ directory.
    testable = [d for d in pkg_dirs if (d / "tests").is_dir()]
    if not testable:
        print("No test directories found for the selected packages.")
        return 0

    env = _pythonpath_env()

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
        cov_args = _coverage_args_for([pkg_dir])
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


def _find_publishable_packages() -> list[str]:
    """Return relative paths to publishable libraries under ``libraries/``."""
    libraries_dir = ROOT / "libraries"
    if not libraries_dir.is_dir():
        return []
    packages = []
    for version_file in sorted(libraries_dir.rglob("VERSION")):
        package_dir = version_file.parent
        if (package_dir / "pyproject.toml").exists():
            packages.append(str(package_dir.relative_to(ROOT)))
    return packages


def build() -> int:
    """Build all publishable package distributions."""
    packages = _find_publishable_packages()
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


def preflight() -> int:
    """Run the checks that CI requires on every pull request."""
    steps: tuple[tuple[str, object], ...] = (
        ("lint", lambda: lint()),
        ("test", lambda: test_host(["--all"])),
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
    return _run([PYTHON, "ci/prepare_micropython.py"])


def prepare_circuitpython() -> int:
    """Prepare the repo-local CircuitPython unix-port runtime."""
    return _run([PYTHON, "ci/prepare_circuitpython.py"])


def test_micropython_compat() -> int:
    """Run the sample device-test smoke script with the MicroPython Unix binary."""
    micropython_bin = _resolve_micropython_binary()
    if micropython_bin is None:
        print("MicroPython binary not found. Preparing unix-port runtime first.")
        prepare_result = prepare_micropython()
        if prepare_result != 0:
            print("MicroPython preparation failed.")
            return prepare_result

        micropython_bin = _resolve_micropython_binary()
        if micropython_bin is None:
            print(
                "Preparation completed without the expected binary. "
                "Set MICROPYTHON_BIN and retry."
            )
            return 1

    return _run([micropython_bin, "-c", SMOKE_EXEC])


def test_circuitpython_compat() -> int:
    """Run the shared smoke script with a configured or repo-managed CircuitPython binary."""
    circuitpython_bin = _resolve_circuitpython_binary()
    if circuitpython_bin is None:
        print("CircuitPython binary not found. Preparing unix-port runtime first.")
        prepare_result = prepare_circuitpython()
        if prepare_result != 0:
            print("CircuitPython preparation failed.")
            return prepare_result

        circuitpython_bin = _resolve_circuitpython_binary()
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

test options:
  --all                Run tests for all packages
  --libraries LIB,...  Run tests for specific packages (comma-separated names)
  -- PYTEST_ARGS       Forward remaining arguments to pytest

  Default (no options): detect changed packages on branch vs origin/main.
"""


def main(argv: list[str]) -> int:
    """Dispatch a named repo-level task."""
    if len(argv) < 2 or argv[1] not in _DISPATCH:
        print(_USAGE.format(prog=argv[0], tasks=", ".join(TASKS)))
        return 1

    task_name = argv[1]
    extra_args = argv[2:]

    if task_name in ("test", "new-library"):
        return _DISPATCH[task_name](extra_args)

    if extra_args:
        print(f"Task '{task_name}' does not accept extra arguments.")
        return 1

    return _DISPATCH[task_name]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
