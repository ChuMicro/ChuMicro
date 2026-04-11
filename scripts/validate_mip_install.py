"""Validate mip install and import for published bundle packages.

Tests that libraries published to a ChuMicro bundle repository can be
installed via MicroPython's mip package manager and imported successfully.

Both ``.py`` (source) and ``.mpy6`` (bytecode) formats are validated for
each library.  The runner library is always tested last because its
dependency on timing exercises mip's dependency resolution.

Usage (via task runner)::

    python scripts/run.py validate-mip \\
        --bundle-repo ChuMicro-Bundle-Experimental \\
        --libraries timing,runner

Direct usage::

    python scripts/validate_mip_install.py \\
        --bundle-repo ChuMicro-Bundle-Experimental \\
        --libraries timing,runner

Requirements:
    - MicroPython unix-port binary (auto-detected or ``--micropython-binary``)
    - Network access to ``raw.githubusercontent.com``
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from shared import resolve_micropython_binary
from workspace import discover_package_dirs

_GITHUB_ORG = "ChuMicro"

#: mpy bytecode format folder (must match bundle_manager.MPY_FORMAT_FOLDER).
_MPY_FORMAT_FOLDER = "mpy6"

#: Maximum number of retries for mip install (handles CDN propagation delay).
_MAX_RETRIES = 3

#: Seconds to wait between retries.
_RETRY_DELAY = 15


class _QuietHandler(SimpleHTTPRequestHandler):
    """HTTP request handler that suppresses logs."""
    def log_message(self, format: str, *args: list[str]) -> None:
        pass


def _serve_local_bundle(bundle_dir: Path) -> tuple[HTTPServer, str]:
    """Serve a local bundle directory via HTTP."""
    server = HTTPServer(
        ("127.0.0.1", 0),
        lambda *args: _QuietHandler(*args, directory=str(bundle_dir)),
    )
    port = server.server_address[1]
    url_base = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, url_base


def _write_install_script(target_path: Path, package_url: str, install_dir: Path) -> Path:
    """Write a MicroPython script that installs a package via mip.

    Args:
        target_path: File to write the script to.
        package_url: The ``github:`` URL to pass to ``mip.install()``.
        install_dir: Target directory for installed files.

    Returns:
        Path to the written script.
    """
    script = (
        "import mip\n"
        f'mip.install("{package_url}", target="{install_dir}")\n'
    )
    target_path.write_text(script)
    return target_path


def _write_import_script(target_path: Path, package_name: str) -> Path:
    """Write a MicroPython script that imports a package and prints confirmation.

    Args:
        target_path: File to write the script to.
        package_name: Python package name to import (e.g. ``chumicro_timing``).

    Returns:
        Path to the written script.
    """
    script = (
        f"import {package_name}\n"
        f'print("import {package_name}: OK")\n'
    )
    target_path.write_text(script)
    return target_path


def _run_micropython(
    binary: str,
    script_path: Path,
    micropypath: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a script with the MicroPython binary.

    Args:
        binary: Path to the MicroPython unix-port binary.
        script_path: Path to the Python script to execute.
        micropypath: Optional MICROPYPATH override.

    Returns:
        Completed process result.
    """
    environment = None
    if micropypath is not None:
        import os
        environment = os.environ.copy()
        environment["MICROPYPATH"] = micropypath

    return subprocess.run(
        [binary, str(script_path)],
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )


def _validate_single(
    binary: str,
    bundle_repo: str,
    library_name: str,
    format_label: str,
    package_url: str,
) -> bool:
    """Install and import a single package format.

    Args:
        binary: Path to the MicroPython binary.
        bundle_repo: Bundle repository name (for log messages).
        library_name: Library name (e.g. ``timing``).
        format_label: Human label for the format (``py`` or ``mpy6``).
        package_url: The ``github:`` mip URL.

    Returns:
        True if validation passed.
    """
    package_name = f"chumicro_{library_name}"
    print(f"  [{format_label}] {package_url}")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        install_dir = temp_path / "lib"
        install_dir.mkdir()
        install_script = _write_install_script(
            temp_path / "install.py", package_url, install_dir,
        )

        # Retry loop to handle CDN propagation delay after bundle push.
        installed = False
        for attempt in range(1, _MAX_RETRIES + 1):
            result = _run_micropython(binary, install_script)
            if result.returncode == 0:
                installed = True
                break
            if attempt < _MAX_RETRIES:
                delay_message = (
                    f"    Attempt {attempt}/{_MAX_RETRIES} failed, "
                    f"retrying in {_RETRY_DELAY}s..."
                )
                print(delay_message)
                if result.stderr:
                    # Show last line of error for context.
                    last_line = result.stderr.strip().splitlines()[-1]
                    print(f"    {last_line}")
                time.sleep(_RETRY_DELAY)

        if not installed:
            print(f"    FAIL: mip install failed after {_MAX_RETRIES} attempts")
            if result.stdout:
                print(f"    stdout: {result.stdout.strip()}")
            if result.stderr:
                print(f"    stderr: {result.stderr.strip()}")
            return False

        # Print install output for visibility.
        if result.stdout:
            for line in result.stdout.strip().splitlines():
                print(f"    {line}")

        # Verify import works.
        import_script = _write_import_script(temp_path / "import_test.py", package_name)
        result = _run_micropython(binary, import_script, micropypath=str(install_dir))
        if result.returncode != 0:
            print(f"    FAIL: import {package_name} failed")
            if result.stderr:
                print(f"    stderr: {result.stderr.strip()}")
            return False

        print("    OK: install + import succeeded")

    return True


def validate_mip_install(
    bundle_repo: str | None,
    library_names: list[str],
    binary: str | None = None,
    local_bundle: str | None = None,
) -> int:
    """Validate mip install and import for the given libraries.

    Tests both ``.py`` and ``.mpy6`` formats for each library.  Libraries
    with dependencies (e.g. runner → timing) are tested last so that
    dependency resolution is exercised.

    Args:
        bundle_repo: Bundle repository name (e.g. ``ChuMicro-Bundle``).
        library_names: Library names to validate (e.g. ``["timing", "runner"]``).
        binary: Explicit MicroPython binary path, or None for auto-detection.
        local_bundle: Local bundle directory to validate via HTTP server.

    Returns:
        Exit code (0 on success, 1 on failure).
    """
    resolved_binary = resolve_micropython_binary(binary)
    if resolved_binary is None:
        print("MicroPython binary not found.")
        print("Run: python scripts/run.py prepare-micropython")
        return 1

    print(f"MicroPython binary: {resolved_binary}")
    if local_bundle:
        print(f"Local bundle:       {local_bundle}")
    else:
        print(f"Bundle repository:  {_GITHUB_ORG}/{bundle_repo}")
    print(f"Libraries:          {', '.join(library_names)}")
    print()

    sorted_names = sorted(library_names, key=lambda name: name == "runner")

    total = 0
    passed = 0
    failed_tests: list[str] = []

    with tempfile.TemporaryDirectory() as serve_dir:
        serve_path = Path(serve_dir)
        if local_bundle:
            # Copy local bundle into a temporary directory so we can patch package.json
            shutil.copytree(local_bundle, serve_path, dirs_exist_ok=True)
            # Patch all package.json files to point to localhost instead of github
            server, url_base = _serve_local_bundle(serve_path)
            for pjson in serve_path.rglob("package.json"):
                content = pjson.read_text()
                content = re.sub(r"github:[\w\-]+/[\w-]+/", f"{url_base}/", content)
                pjson.write_text(content)

        for library_name in sorted_names:
            package_name = f"chumicro_{library_name}"
            print(f"== {package_name} ==")

            # .py format (source)
            if local_bundle:
                py_url = f"{url_base}/{package_name}"
            else:
                py_url = f"github:{_GITHUB_ORG}/{bundle_repo}/{package_name}"

            total += 1
            if _validate_single(
                resolved_binary, bundle_repo or "local", library_name, "py", py_url
            ):
                passed += 1
            else:
                failed_tests.append(f"{package_name} (py)")

            # .mpy6 format (bytecode)
            if local_bundle:
                mpy_url = f"{url_base}/{_MPY_FORMAT_FOLDER}/{package_name}"
            else:
                mpy_url = f"github:{_GITHUB_ORG}/{bundle_repo}/{_MPY_FORMAT_FOLDER}/{package_name}"

            total += 1
            if _validate_single(
                resolved_binary, bundle_repo or "local", library_name, "mpy6", mpy_url
            ):
                passed += 1
            else:
                failed_tests.append(f"{package_name} (mpy6)")

            print()

    # Summary
    if failed_tests:
        print(f"FAILED: {len(failed_tests)} of {total} validations failed:")
        for failure in failed_tests:
            print(f"  - {failure}")
        return 1

    print(f"All {total} validations passed ({passed}/{total}).")
    return 0


def _resolve_library_names(libraries_arg: str | None) -> list[str]:
    """Resolve library names from CLI argument or auto-discover.

    Args:
        libraries_arg: Comma-separated library names, or None for all.

    Returns:
        List of library names.
    """
    if libraries_arg:
        return [name.strip() for name in libraries_arg.split(",") if name.strip()]

    # Auto-discover from workspace.
    all_dirs = discover_package_dirs()
    return [
        package_dir.name
        for package_dir in all_dirs
        if package_dir.parent.name == "libraries"
    ]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Validate mip install and import for bundle packages.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--bundle-repo",
        help="Bundle repository name (e.g. ChuMicro-Bundle-Experimental)",
    )
    group.add_argument(
        "--local-bundle",
        help="Path to a local bundle directory to validate.",
    )
    parser.add_argument(
        "--libraries",
        help="Comma-separated library names (default: all)",
    )
    parser.add_argument(
        "--micropython-binary",
        help="Path to MicroPython binary (overrides auto-detection)",
    )
    args = parser.parse_args(argv)

    library_names = _resolve_library_names(args.libraries)
    if not library_names:
        print("No libraries found to validate.")
        return 1

    return validate_mip_install(
        bundle_repo=args.bundle_repo,
        library_names=library_names,
        binary=args.micropython_binary,
        local_bundle=args.local_bundle,
    )


if __name__ == "__main__":
    raise SystemExit(main())

