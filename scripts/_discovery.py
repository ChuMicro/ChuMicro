"""Workspace discovery, scope parsing, and change detection.

Provides the shared helpers that other ``scripts/`` modules use to
locate packages, source roots, and changed files.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / ".tools"


def read_runtime_versions() -> dict:
    """Read pinned runtime versions from ``runtime-versions.toml``."""
    import tomllib

    with (ROOT / "runtime-versions.toml").open("rb") as f:
        return tomllib.load(f)


def discover_package_dirs() -> list[Path]:
    """Find directories under support/ and libraries/ that contain a pyproject.toml."""
    dirs: list[Path] = []
    for parent in [ROOT / "support", ROOT / "libraries"]:
        if not parent.is_dir():
            continue
        for child in sorted(parent.iterdir()):
            if child.is_dir() and (child / "pyproject.toml").exists():
                dirs.append(child)
    return dirs


def discover_source_roots() -> list[Path]:
    """Return src/ directories for all discovered packages."""
    return [d / "src" for d in discover_package_dirs() if (d / "src").is_dir()]


def discover_ruff_paths() -> list[str]:
    """Return paths to lint across the workspace."""
    paths = ["ci", "scripts"]
    for pkg_dir in discover_package_dirs():
        rel = str(pkg_dir.relative_to(ROOT))
        for subdir in ["src", "tests", "device_tests", "examples"]:
            if (pkg_dir / subdir).is_dir():
                paths.append(f"{rel}/{subdir}")
    return paths


def coverage_args_for(pkg_dirs: list[Path]) -> list[str]:
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


def resolve_named_packages(names: list[str]) -> list[Path]:
    """Resolve package names to directories.

    Accepts bare names (e.g. ``timing``) or relative paths
    (e.g. ``libraries/timing``).
    """
    all_dirs = discover_package_dirs()
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


def detect_changed_packages() -> list[Path] | None:
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


def parse_scope_args(extra_args: list[str]) -> tuple[list[Path], list[str]]:
    """Parse ``--all`` / ``--libraries`` into a package scope and remaining args.

    Returns ``(pkg_dirs, remaining)``.  Used by test, verify-examples, and docs.
    """
    scope: str | list[str] = "changed"
    remaining: list[str] = []

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
            remaining = extra_args[i + 1 :]
            break
        else:
            remaining = extra_args[i:]
            break

    # Resolve scope → list[Path]
    if scope == "all":
        return discover_package_dirs(), remaining

    if isinstance(scope, list):
        resolved = resolve_named_packages(scope)
        if not resolved:
            raise SystemExit(1)
        return resolved, remaining

    # "changed" — detect from git
    detected = detect_changed_packages()
    if detected is None:
        print("Running for all packages (no branch diff or infrastructure changed).")
        return discover_package_dirs(), remaining

    names = ", ".join(d.name for d in detected)
    print(f"Changed packages detected: {names}")
    return detected, remaining


def find_publishable_packages() -> list[str]:
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


def pythonpath_env() -> dict[str, str]:
    """Return an environment with the repo source roots prepended to PYTHONPATH."""
    env = os.environ.copy()
    existing_path = env.get("PYTHONPATH")
    path_entries = [str(path) for path in discover_source_roots()]
    if existing_path:
        path_entries.append(existing_path)

    env["PYTHONPATH"] = os.pathsep.join(path_entries)
    return env

