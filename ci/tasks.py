"""Shared repo-level tasks for humans, agents, and CI."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from prepare_circuitpython import DEFAULT_BINARY_PATH as DEFAULT_CIRCUITPYTHON_BINARY_PATH
from prepare_micropython import DEFAULT_BINARY_PATH

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
SMOKE_SCRIPT = "ci/run_sample_device_smoke.py"
SMOKE_EXEC = f'exec(open("{SMOKE_SCRIPT}").read())'
SOURCE_PATHS = [
    ROOT / "support/runtime/src",
    ROOT / "support/test_harness/src",
    ROOT / "sample/src",
]
RUFF_PATHS = [
    "ci",
    "scripts",
    "support/runtime/src",
    "support/runtime/tests",
    "support/test_harness/src",
    "support/test_harness/tests",
    "sample/src",
    "sample/tests",
    "sample/device_tests",
]
PYTEST_ARGS = [
    "-W",
    "error",
    "--cov=support/runtime/src/chumicro_runtime",
    "--cov=support/test_harness/src/chumicro_test_harness",
    "--cov=sample/src/chumicro_sample",
    "--cov-report=term-missing",
]
TASKS = (
    "setup",
    "lint",
    "test-host",
    "build-sample",
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
    path_entries = [str(path) for path in SOURCE_PATHS]
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


def _resolve_binary(environment_name: str, default_name: str) -> str | None:
    """Resolve a runtime binary from an environment variable or the current PATH."""
    configured_path = os.environ.get(environment_name)
    if configured_path:
        return configured_path

    return shutil.which(default_name)


def _resolve_micropython_binary() -> str | None:
    """Resolve a MicroPython binary from env vars, repo-local tools, or PATH."""
    configured_path = os.environ.get("MICROPYTHON_BIN")
    if configured_path:
        return configured_path

    if DEFAULT_BINARY_PATH.exists():
        return str(DEFAULT_BINARY_PATH)

    return _resolve_binary("MICROPYTHON_BIN", "micropython")


def _resolve_circuitpython_binary() -> str | None:
    """Resolve a CircuitPython binary from env vars, repo-local tools, or PATH."""
    configured_path = os.environ.get("CIRCUITPYTHON_BIN")
    if configured_path:
        return configured_path

    if DEFAULT_CIRCUITPYTHON_BINARY_PATH.exists():
        return str(DEFAULT_CIRCUITPYTHON_BINARY_PATH)

    return _resolve_binary("CIRCUITPYTHON_BIN", "circuitpython")


def lint() -> int:
    """Run Ruff across the currently tracked source and test roots."""
    return _run([PYTHON, "-m", "ruff", "check", *RUFF_PATHS])


def setup() -> int:
    """Install development dependencies into the active Python environment."""
    packages = ["pip", "pytest", "pytest-cov", "ruff", "build"]
    return _run([PYTHON, "-m", "pip", "install", "-U", *packages])


def test_host() -> int:
    """Run the verified CPython test suite with coverage."""
    return _run([PYTHON, "-m", "pytest", *PYTEST_ARGS], env=_pythonpath_env())


def build_sample() -> int:
    """Build the sample package distribution."""
    return _run([PYTHON, "-m", "build", "sample"])


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
        print(
            "MicroPython binary not found. Running `python ci/tasks.py prepare-micropython` "
            "before the smoke test."
        )
        prepare_result = prepare_micropython()
        if prepare_result != 0:
            print(
                "MicroPython compatibility check stopped before the smoke test because "
                "runtime preparation failed."
            )
            return prepare_result

        micropython_bin = _resolve_micropython_binary()
        if micropython_bin is None:
            print(
                "MicroPython preparation completed without the expected binary. Set "
                "MICROPYTHON_BIN to a working interpreter path and rerun the compatibility check."
            )
            return 1

    return _run([micropython_bin, "-c", SMOKE_EXEC])


def test_runtime_matrix() -> int:
    """Run host tests and compatibility smoke tests across all proven runtimes."""
    steps = (
        ("test-host", test_host),
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


def test_circuitpython_compat() -> int:
    """Run the shared smoke script with a configured or repo-managed CircuitPython binary."""
    circuitpython_bin = _resolve_circuitpython_binary()
    if circuitpython_bin is None:
        print(
            "CircuitPython binary not found. Running `python ci/tasks.py prepare-circuitpython` "
            "before the smoke test."
        )
        prepare_result = prepare_circuitpython()
        if prepare_result != 0:
            print(
                "CircuitPython compatibility check stopped before the smoke test because "
                "runtime preparation failed."
            )
            return prepare_result

        circuitpython_bin = _resolve_circuitpython_binary()
        if circuitpython_bin is None:
            print(
                "CircuitPython preparation completed without the expected binary. Set "
                "CIRCUITPYTHON_BIN to a working interpreter path and rerun the compatibility check."
            )
            return 1

    return _run([circuitpython_bin, "-c", SMOKE_EXEC])


def preflight() -> int:
    """Run the checks that CI requires on every pull request."""
    steps = (
        ("lint", lint),
        ("test-host", test_host),
        ("build-sample", build_sample),
    )

    for step_name, step in steps:
        print(f"== {step_name} ==")
        result = step()
        if result != 0:
            print(f"Preflight failed at: {step_name}")
            return result

    print("Preflight passed — required CI checks should pass.")
    return 0


def test_device() -> int:
    """Point users to the current manual-only device validation path."""
    devices_path = ROOT / "devices.yml"
    if devices_path.exists():
        print(f"Manual device validation remains user-driven. Config found at: {devices_path}")
    else:
        print(
            "Manual device validation remains user-driven. Copy `devices.example.yml` to "
            "`devices.yml` and fill in your local board details."
        )

    print("Use `sample/device_tests/` with `support/test_harness/` on the target board.")
    return 2


def main(argv: list[str]) -> int:
    """Dispatch a named repo-level task."""
    if len(argv) != 2 or argv[1] not in TASKS:
        available_tasks = ", ".join(TASKS)
        print(f"Usage: {argv[0]} <task>")
        print(f"Available tasks: {available_tasks}")
        return 1

    task = argv[1]
    if task == "setup":
        return setup()
    if task == "lint":
        return lint()
    if task == "test-host":
        return test_host()
    if task == "build-sample":
        return build_sample()
    if task == "preflight":
        return preflight()
    if task == "prepare-micropython":
        return prepare_micropython()
    if task == "prepare-circuitpython":
        return prepare_circuitpython()
    if task == "test-micropython-compat":
        return test_micropython_compat()
    if task == "test-runtime-matrix":
        return test_runtime_matrix()
    if task == "test-circuitpython-compat":
        return test_circuitpython_compat()

    return test_device()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

