"""Validate mip install and import for bundle packages.

Tests that libraries published to (or staged for) a ChuMicro bundle
repository can be installed via MicroPython's mip package manager and
imported successfully.

Both ``.py`` (source) and ``.mpy6`` (bytecode) formats are validated for
each library.  The runner library is always tested last because its
dependency on timing exercises mip's dependency resolution.

Two modes:

- **Remote** (``--bundle-repo``): validate against a live GitHub bundle
  repository.  Used post-publish as a smoke test.
- **Local** (``--staging-dir``): validate against a locally staged bundle
  directory by serving it over a background HTTP server and rewriting
  ``package.json`` URLs.  Used pre-publish to catch broken ``.mpy``
  compilation or manifest errors before pushing.

Usage (via task runner)::

    python scripts/run.py validate-mip \\
        --bundle-repo ChuMicro-Bundle-Experimental \\
        --libraries timing,runner

    python scripts/run.py validate-mip \\
        --staging-dir .bundle-staging \\
        --libraries timing,runner

Direct usage::

    python scripts/validate_mip_install.py \\
        --bundle-repo ChuMicro-Bundle-Experimental \\
        --libraries timing,runner

    python scripts/validate_mip_install.py \\
        --staging-dir .bundle-staging \\
        --libraries timing,runner

Requirements:
    - MicroPython unix-port binary (auto-detected or ``--micropython-binary``)
    - Remote mode: network access to ``raw.githubusercontent.com``
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

from bundle_layout import mpy_format_folders
from repo_layout import (
    GITHUB_ORG,
    ROOT,
    discover_library_dirs,
    is_parked,
    library_name_from_pip_dependency,
    load_tomllib,
    order_libraries_by_dependency,
)
from shared import resolve_micropython_binary


def _intra_workspace_deps(library_name: str) -> list[str]:
    """Return workspace library names that *library_name* depends on.

    Reads the library's ``pyproject.toml`` once per call (no caching;
    only invoked at validation startup).  Returns dependency *library
    names* with the ``chumicro-`` prefix stripped (e.g. ``"timing"``,
    not ``"chumicro-timing"``) so they match the ``library_names``
    arguments used by the validator.
    """
    pyproject_file = ROOT / "libraries" / library_name / "pyproject.toml"
    if not pyproject_file.is_file():
        return []
    tomllib = load_tomllib()
    with pyproject_file.open("rb") as handle:
        data = tomllib.load(handle)
    raw_deps = data.get("project", {}).get("dependencies", [])
    workspace_deps: list[str] = []
    for dependency in raw_deps:
        dep_library = library_name_from_pip_dependency(dependency)
        if dep_library is not None:
            workspace_deps.append(dep_library)
    return workspace_deps

#: Maximum number of retries for mip install (handles CDN propagation delay).
_MAX_RETRIES = 3

#: Seconds to wait between retries.
_RETRY_DELAY = 15


class _QuietHandler(SimpleHTTPRequestHandler):
    """HTTP request handler that suppresses access logs."""

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass


def _start_local_server(directory: Path) -> tuple[HTTPServer, str]:
    """Start a background HTTP server serving *directory*.

    Args:
        directory: Filesystem path to serve.

    Returns:
        ``(server, base_url)`` where *base_url* is
        ``http://127.0.0.1:<port>``.
    """
    server = HTTPServer(
        ("127.0.0.1", 0),
        lambda *handler_args: _QuietHandler(
            *handler_args, directory=str(directory),
        ),
    )
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, base_url


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
        # `result` is initialized to None so pyright can prove it's bound on
        # every code path the post-loop branches read it on.  _MAX_RETRIES
        # being a positive constant is a runtime invariant pyright can't see.
        installed = False
        result: subprocess.CompletedProcess | None = None
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

        assert result is not None  # _MAX_RETRIES >= 1, so loop always ran.
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
    bundle_repo: str,
    library_names: list[str],
    binary: str | None = None,
) -> int:
    """Validate mip install and import for the given libraries.

    Tests both ``.py`` and ``.mpy6`` formats for each library.  Libraries
    with dependencies (e.g. runner → timing) are tested last so that
    dependency resolution is exercised.

    Args:
        bundle_repo: Bundle repository name (e.g. ``ChuMicro-Bundle``).
        library_names: Library names to validate (e.g. ``["timing", "runner"]``).
        binary: Explicit MicroPython binary path, or None for auto-detection.

    Returns:
        Exit code (0 on success, 1 on failure).
    """
    resolved_binary = resolve_micropython_binary(binary)
    if resolved_binary is None:
        print("MicroPython binary not found.")
        print("Run: python scripts/run.py prepare-micropython")
        return 1

    print(f"MicroPython binary: {resolved_binary}")
    print(f"Bundle repository:  {GITHUB_ORG}/{bundle_repo}")
    print(f"Libraries:          {', '.join(library_names)}")
    print()

    # Topologically sort so each library's intra-workspace deps run
    # first.  This ensures dependency resolution against the bundle
    # repo is exercised in the right order, so runner sees a satisfiable
    # `chumicro-timing` import because timing was installed first.
    sorted_names = order_libraries_by_dependency(library_names, _intra_workspace_deps)

    total = 0
    passed = 0
    failed_tests: list[str] = []

    for library_name in sorted_names:
        package_name = f"chumicro_{library_name}"
        print(f"== {package_name} ==")

        # .py format (source)
        py_url = f"github:{GITHUB_ORG}/{bundle_repo}/{package_name}"
        total += 1
        if _validate_single(resolved_binary, bundle_repo, library_name, "py", py_url):
            passed += 1
        else:
            failed_tests.append(f"{package_name} (py)")

        # Every live mpy format folder (bytecode).  One today; when an
        # incompatible ABI lands the bundle carries the formats side by
        # side (Decision 0112), and each one has to install on its own.
        for mpy_folder in mpy_format_folders():
            mpy_url = (
                f"github:{GITHUB_ORG}/{bundle_repo}/{mpy_folder}/{package_name}"
            )
            total += 1
            if _validate_single(
                resolved_binary, bundle_repo, library_name, mpy_folder, mpy_url,
            ):
                passed += 1
            else:
                failed_tests.append(f"{package_name} ({mpy_folder})")

        print()

    # Summary
    if failed_tests:
        print(f"FAILED: {len(failed_tests)} of {total} validations failed:")
        for failure in failed_tests:
            print(f"  - {failure}")
        return 1

    print(f"All {total} validations passed ({passed}/{total}).")
    return 0


def validate_local_staging(
    staging_dir: str,
    library_names: list[str],
    binary: str | None = None,
) -> int:
    """Validate mip install and import from a locally staged bundle.

    Copies the staging directory into a temp directory, rewrites all
    ``package.json`` manifests to replace ``github:`` URLs with
    ``http://localhost`` URLs, starts a background HTTP server, and
    validates that each library can be installed via mip and imported.

    This is the pre-publish gate.  Run it after staging bundle artifacts
    but before pushing to the live bundle repository.

    Args:
        staging_dir: Path to the staged bundle directory (e.g.
            ``.bundle-staging``).
        library_names: Library names to validate (e.g. ``["timing", "runner"]``).
        binary: Explicit MicroPython binary path, or None for auto-detection.

    Returns:
        Exit code (0 on success, 1 on failure).
    """
    resolved_binary = resolve_micropython_binary(binary)
    if resolved_binary is None:
        print("MicroPython binary not found.")
        print("Run: python scripts/run.py prepare-micropython")
        return 1

    staging_path = Path(staging_dir)
    if not staging_path.is_dir():
        print(f"Staging directory not found: {staging_dir}")
        return 1

    print(f"MicroPython binary: {resolved_binary}")
    print(f"Staging directory:  {staging_dir}")
    print(f"Libraries:          {', '.join(library_names)}")
    print()

    sorted_names = order_libraries_by_dependency(library_names, _intra_workspace_deps)

    total = 0
    passed = 0
    failed_tests: list[str] = []

    # Copy staging to a temp directory so we can rewrite package.json
    # without modifying the original artifacts.
    with tempfile.TemporaryDirectory() as serve_dir:
        serve_path = Path(serve_dir)
        shutil.copytree(staging_dir, serve_path, dirs_exist_ok=True)

        server, base_url = _start_local_server(serve_path)
        try:
            # Rewrite all github: URLs in package.json manifests to point
            # at the local HTTP server.
            for manifest_path in serve_path.rglob("package.json"):
                content = manifest_path.read_text()
                content = re.sub(
                    r"github:[\w\-]+/[\w\-]+/",
                    f"{base_url}/",
                    content,
                )
                manifest_path.write_text(content)

            for library_name in sorted_names:
                package_name = f"chumicro_{library_name}"
                print(f"== {package_name} ==")

                # .py format (source)
                py_url = f"{base_url}/{package_name}"
                total += 1
                if _validate_single(
                    resolved_binary, "local", library_name, "py", py_url,
                ):
                    passed += 1
                else:
                    failed_tests.append(f"{package_name} (py)")

                # Every live mpy format folder (bytecode), as above.
                for mpy_folder in mpy_format_folders():
                    mpy_url = f"{base_url}/{mpy_folder}/{package_name}"
                    total += 1
                    if _validate_single(
                        resolved_binary, "local", library_name,
                        mpy_folder, mpy_url,
                    ):
                        passed += 1
                    else:
                        failed_tests.append(f"{package_name} ({mpy_folder})")

                print()
        finally:
            server.shutdown()

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

    # Auto-discover from workspace.  Parked libraries (Decision 0107)
    # are excluded: they never enter the bundle, so there is nothing to
    # validate a mip install against.
    return [
        package_dir.name
        for package_dir in discover_library_dirs()
        if not is_parked(package_dir)
    ]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Validate mip install and import for bundle packages.",
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--bundle-repo",
        help="Bundle repository name (e.g. ChuMicro-Bundle-Experimental)",
    )
    source_group.add_argument(
        "--staging-dir",
        help="Path to a locally staged bundle directory",
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

    if args.staging_dir:
        return validate_local_staging(
            staging_dir=args.staging_dir,
            library_names=library_names,
            binary=args.micropython_binary,
        )

    return validate_mip_install(
        bundle_repo=args.bundle_repo,
        library_names=library_names,
        binary=args.micropython_binary,
    )


if __name__ == "__main__":
    raise SystemExit(main())
