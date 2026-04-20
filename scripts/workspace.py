"""Workspace discovery, scope parsing, and change detection.

Provides the shared helpers that other ``scripts/`` modules use to
locate packages, source roots, and changed files.  This is the
foundational module — nearly every other script imports from here.

Previously named ``discovery.py``.
"""

from __future__ import annotations

import functools
import os
import subprocess
from pathlib import Path

#: Absolute path to the repository root (parent of the scripts/ directory).
ROOT = Path(__file__).resolve().parent.parent
#: Directory where prepared runtime source trees and binaries are stored.
TOOLS = ROOT / ".tools"

#: Canonical platform identifiers.
ALL_PLATFORMS = ("cpython", "micropython", "circuitpython")

#: GitHub organization name used across bundle, docs, and distribution URLs.
GITHUB_ORG = "ChuMicro"


def load_tomllib():
    """Import tomllib lazily.

    Stdlib from 3.11+; the ``tomli`` backport covers 3.9–3.10.
    Keeping this out of module scope lets ``workspace`` be imported on a
    fresh clone before third-party packages are installed.
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]
    return tomllib


def read_runtime_versions() -> dict:
    """Read pinned target runtime versions from ``target-runtimes.toml``."""
    tomllib = load_tomllib()
    with (ROOT / "target-runtimes.toml").open("rb") as runtimes_file:
        return tomllib.load(runtimes_file)


@functools.cache
def read_platforms(package_dir: Path) -> tuple[str, ...]:
    """Read ``[tool.chumicro].platforms`` from a package's ``pyproject.toml``.

    Returns :data:`ALL_PLATFORMS` when the key or section is absent —
    libraries default to targeting all three runtimes.

    See ``plans/decisions/0011-platform-targeting.md``.

    Args:
        package_dir: Directory containing the package's ``pyproject.toml``.
    """

    pyproject_file = package_dir / "pyproject.toml"
    if not pyproject_file.exists():
        return ALL_PLATFORMS
    tomllib = load_tomllib()
    with pyproject_file.open("rb") as toml_file:
        data = tomllib.load(toml_file)
    platforms = data.get("tool", {}).get("chumicro", {}).get("platforms")
    if platforms is None:
        return ALL_PLATFORMS
    return tuple(platforms)


def filter_by_platform(package_dirs: list[Path], platform: str) -> list[Path]:
    """Return only packages that target *platform*.

    Args:
        package_dirs: Package directories to filter.
        platform: Runtime identifier (e.g. ``"micropython"``).
    """
    return [package_dir for package_dir in package_dirs if platform in read_platforms(package_dir)]


def find_package_dir(library_dir: Path) -> Path | None:
    """Find the single importable package directory under a library's ``src/``.

    Returns the first directory inside ``<library_dir>/src/`` that contains
    an ``__init__.py`` and is not a dot-prefixed or egg-info directory.
    Returns ``None`` when no importable package is found.

    Args:
        library_dir: Root directory of the library.
    """
    src_dir = library_dir / "src"
    if not src_dir.is_dir():
        return None
    for child in sorted(src_dir.iterdir()):
        if (
            child.is_dir()
            and (child / "__init__.py").exists()
            and not child.name.startswith(".")
            and not child.name.endswith(".egg-info")
        ):
            return child
    return None


_package_dirs_cache: list[Path] | None = None


def discover_package_dirs() -> list[Path]:
    """Find directories under support/ and libraries/ that contain a pyproject.toml.

    This is the primary discovery function — it defines which packages
    exist in the workspace.  The task runner, IDE sync, and coverage
    tools all derive their package lists from this function.  No
    hard-coded package lists exist anywhere in the codebase.

    Results are cached for the lifetime of the process.
    """
    global _package_dirs_cache
    if _package_dirs_cache is not None:
        return list(_package_dirs_cache)
    package_dirs: list[Path] = []
    for parent_dir in [ROOT / "support", ROOT / "libraries"]:
        if not parent_dir.is_dir():
            continue
        for child in sorted(parent_dir.iterdir()):
            if child.is_dir() and (child / "pyproject.toml").exists():
                package_dirs.append(child)
    _package_dirs_cache = package_dirs
    return package_dirs


def discover_library_dirs() -> list[Path]:
    """Return package directories that live under ``libraries/``.

    Convenience wrapper around :func:`discover_package_dirs` that filters
    to publishable library directories only — excludes ``support/``
    packages.
    """
    return [
        package_dir for package_dir in discover_package_dirs()
        if package_dir.parent.name == "libraries"
    ]


def discover_source_roots() -> list[Path]:
    """Return src/ directories for all discovered packages.

    Used to build ``PYTHONPATH`` for pytest and IDE ``extraPaths``
    as a fallback alongside editable installs.
    """
    return [
        package_dir / "src"
        for package_dir in discover_package_dirs()
        if (package_dir / "src").is_dir()
    ]


def discover_ruff_paths() -> list[str]:
    """Return paths to lint across the workspace.

    Includes ``scripts/`` itself and the ``src/``, ``tests/``,
    ``functional_tests/``, and ``examples/`` subdirectories of every
    discovered package.  Directories that don't exist are skipped.
    """
    paths = ["scripts"]
    for package_dir in discover_package_dirs():
        relative_path = str(package_dir.relative_to(ROOT))
        for subdir in ["src", "tests", "functional_tests", "examples"]:
            if (package_dir / subdir).is_dir():
                paths.append(f"{relative_path}/{subdir}")
    return paths


def coverage_args_for(package_dirs: list[Path]) -> list[str]:
    """Return ``--cov`` arguments for importable packages under *package_dirs*."""
    args: list[str] = []
    for package_dir in package_dirs:
        importable_dir = find_package_dir(package_dir)
        if importable_dir is not None:
            args.extend(["--cov", str(importable_dir.relative_to(ROOT))])
    return args


def read_pyproject_description(library_dir: Path) -> str:
    """Read ``project.description`` from a library's ``pyproject.toml``.

    Falls back to the first non-heading, non-empty line of ``README.md``
    when the description is empty.

    Args:
        library_dir: Root directory of the library.

    Returns:
        Description string, or empty string if none found.
    """
    pyproject_file = library_dir / "pyproject.toml"
    if not pyproject_file.exists():
        return ""
    tomllib = load_tomllib()
    with pyproject_file.open("rb") as toml_file:
        data = tomllib.load(toml_file)
    description = data.get("project", {}).get("description", "") or ""
    if not description and (library_dir / "README.md").exists():
        for line in (library_dir / "README.md").read_text().splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                description = stripped
                break
    return description


def discover_doc_dirs(package_dirs: list[Path] | None = None) -> list[Path]:
    """Return library directories that contain a ``mkdocs.yml``.

    Args:
        package_dirs: Package directories to filter.  When ``None``,
            uses :func:`discover_library_dirs`.
    """
    candidates = package_dirs if package_dirs is not None else discover_library_dirs()
    return [
        package_dir for package_dir in candidates
        if (package_dir / "mkdocs.yml").exists()
    ]


def is_ref_reachable(reference: str) -> bool:
    """Return True if *reference* is a valid git ref that can be diffed against.

    Args:
        reference: Git ref to check (e.g. ``"origin/main"``).
    """
    result = subprocess.run(
        ["git", "rev-parse", "--verify", reference],
        capture_output=True, cwd=ROOT, check=False,
    )
    return result.returncode == 0


def resolve_named_packages(names: list[str]) -> list[Path]:
    """Resolve package names to directories.

    Accepts bare names (e.g. ``timing``) or relative paths
    (e.g. ``libraries/timing``).
    """
    all_package_dirs = discover_package_dirs()
    by_name = {package_dir.name: package_dir for package_dir in all_package_dirs}
    by_relative_path = {
        str(package_dir.relative_to(ROOT)): package_dir
        for package_dir in all_package_dirs
    }

    resolved: list[Path] = []
    for name in names:
        if name in by_relative_path:
            resolved.append(by_relative_path[name])
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
        # Union three diffs to catch all local work:
        #   1. Committed changes on this branch vs origin/main
        #   2. Unstaged working-tree changes
        #   3. Staged but uncommitted changes
        # This ensures we never miss files regardless of commit state.
        for diff_command in (
            ["git", "diff", "--name-only", "origin/main...HEAD"],
            ["git", "diff", "--name-only"],
            ["git", "diff", "--name-only", "--cached"],
        ):
            result = subprocess.run(
                diff_command, capture_output=True, text=True, cwd=ROOT, check=False
            )
            if result.returncode == 0 and result.stdout.strip():
                changed.update(result.stdout.strip().splitlines())
    except (FileNotFoundError, OSError):
        # git unavailable (e.g. no .git dir) — caller treats None as
        # "run everything" to be safe.
        return None

    if not changed:
        # No changes at all — also means "run everything" so the default
        # invocation always does useful work.
        return None

    # Infrastructure changes affect all packages.  Root conftest.py
    # configures sys.path for all tests; root pyproject.toml controls
    # shared tooling; scripts/ and .github/ define CI and task-runner
    # behavior.  Any change here invalidates per-library scoping.
    for path in changed:
        if path in ("conftest.py", "pyproject.toml"):
            return None
        if path.startswith(("scripts/", ".github/")):
            return None

    # Extract unique package dirs from changed file paths
    package_dirs: set[Path] = set()
    for path in changed:
        for prefix in ("libraries/", "support/"):
            if path.startswith(prefix):
                parts = path.split("/")
                if len(parts) >= 2:
                    package_dir = ROOT / parts[0] / parts[1]
                    if package_dir.is_dir() and (package_dir / "pyproject.toml").exists():
                        package_dirs.add(package_dir)

    return sorted(package_dirs) if package_dirs else None


def resolve_scope(
    *, all_packages: bool = False, libraries: str | None = None
) -> list[Path]:
    """Resolve package scope from parsed CLI flags.

    Called by the task runner after argparse has extracted ``--all`` /
    ``--libraries``.  Returns the list of package directories to operate on.
    """
    if all_packages:
        return discover_package_dirs()

    if libraries:
        names = [name.strip() for name in libraries.split(",") if name.strip()]
        resolved = resolve_named_packages(names)
        if not resolved:
            raise SystemExit(1)
        return resolved

    # Default: detect from git
    detected = detect_changed_packages()
    if detected is None:
        print("Running for all packages (no branch diff or infrastructure changed).")
        return discover_package_dirs()

    package_names = ", ".join(package_dir.name for package_dir in detected)
    print(f"Changed packages detected: {package_names}")
    return detected


def find_publishable_packages() -> list[str]:
    """Return relative paths to publishable libraries under ``libraries/``.

    A library is publishable when it has both a ``VERSION`` file (which
    provides the release version) and a ``pyproject.toml`` (which
    defines build metadata).  Support packages under ``support/`` are
    workspace-internal and are never published.
    """
    libraries_dir = ROOT / "libraries"
    if not libraries_dir.is_dir():
        return []
    packages = []
    for version_file in sorted(libraries_dir.rglob("VERSION")):
        package_dir = version_file.parent
        if (package_dir / "pyproject.toml").exists():
            packages.append(str(package_dir.relative_to(ROOT)))
    return packages


def find_support_packages() -> list[str]:
    """Return relative paths to support packages under ``support/``.

    A support package is any directory under ``support/`` with a
    ``pyproject.toml``.  These are workspace-internal packages that
    are editable-installed for development convenience but never
    published.
    """
    support_dir = ROOT / "support"
    if not support_dir.is_dir():
        return []
    packages = []
    for child in sorted(support_dir.iterdir()):
        if child.is_dir() and (child / "pyproject.toml").exists():
            packages.append(str(child.relative_to(ROOT)))
    return packages


def read_version(library_dir: Path) -> str | None:
    """Read a library's ``VERSION`` file.

    Args:
        library_dir: Root directory of the library.

    Returns:
        The version string, or ``None`` if the file is missing or empty.
    """
    version_file = library_dir / "VERSION"
    if not version_file.exists():
        return None
    return version_file.read_text().strip() or None


def release_tags(library_name: str) -> list[str]:
    """Return release tags for a library, sorted newest first.

    Args:
        library_name: Library name (e.g. ``"timing"``).
    """
    result = subprocess.run(
        ["git", "tag", "--list", f"{library_name}-v*", "--sort=-v:refname"],
        capture_output=True, text=True, cwd=ROOT, check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return result.stdout.strip().splitlines()


def pythonpath_environment() -> dict[str, str]:
    """Return an environment with the repository source roots prepended to PYTHONPATH.

    Prepending all ``src/`` directories lets pytest discover library
    packages as a fallback alongside editable installs (Decision 0008).
    """
    environment = os.environ.copy()
    existing_path = environment.get("PYTHONPATH")
    path_entries = [str(source_dir) for source_dir in discover_source_roots()]
    if existing_path:
        path_entries.append(existing_path)

    environment["PYTHONPATH"] = os.pathsep.join(path_entries)
    return environment


# ---------------------------------------------------------------------------
# Shared helpers for PR checks (check_version, check_api)
# ---------------------------------------------------------------------------

#: Paths within a library that require a VERSION bump when changed.
#: ``"src"`` matches as a directory prefix (any file under ``src/``),
#: while ``"pyproject.toml"`` matches as an exact filename at the
#: library root.  See ``plans/decisions/0002-per-library-version-files.md``.
RELEASE_RELEVANT = {"src", "pyproject.toml"}


def changed_files(base_reference: str) -> list[str]:
    """Return files changed between *base_reference* and HEAD."""
    # Three-dot syntax finds changes since the merge-base, which is the
    # standard PR diff.  It fails in shallow clones (CI) where the
    # merge-base commit is not fetched.  The two-arg fallback gives a
    # full diff between the two refs — a superset that may include extra
    # files, but is safe (we'd rather over-test than under-test).
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_reference}...HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["git", "diff", "--name-only", base_reference, "HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr.strip()}")
    return [line for line in result.stdout.strip().splitlines() if line]


def changed_libraries(base_reference: str) -> set[str]:
    """Return names of libraries with release-relevant changes."""
    changed = changed_files(base_reference)
    libraries: set[str] = set()
    for path in changed:
        parts = path.split("/")
        # parts[2] is checked against RELEASE_RELEVANT = {"src", "pyproject.toml"}.
        # "src" acts as a directory prefix (any file under src/ qualifies),
        # while "pyproject.toml" is an exact match (len(parts)==3 for the
        # root-level file).  Both work because we only need to know whether
        # the library was touched — not which specific file changed.
        if len(parts) >= 3 and parts[0] == "libraries" and parts[2] in RELEASE_RELEVANT:
            libraries.add(parts[1])
    return libraries
