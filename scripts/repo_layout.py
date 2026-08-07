"""Workspace discovery, scope parsing, and change detection.

Provides the shared helpers that other ``scripts/`` modules use to
locate packages, source roots, and changed files.  Nearly every other
script imports from here.
"""

from __future__ import annotations

import functools
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

#: Absolute path to the repository root (parent of the scripts/ directory).
ROOT = Path(__file__).resolve().parent.parent
#: Directory where prepared runtime source trees and binaries are stored.
TOOLS = ROOT / ".tools"

#: Canonical platform identifiers.
ALL_PLATFORMS = ("cpython", "micropython", "circuitpython")

#: GitHub organization name used across bundle, docs, and distribution URLs.
GITHUB_ORG = "ChuMicro"

#: PEP 508 version specifiers, environment markers, and extras.
#: Splits a dependency string so ``"chumicro-timing>=0.1"`` becomes ``"chumicro-timing"``.
_DEPENDENCY_VERSION_SPLITTER = re.compile(r"[><=!;~\[]")


def strip_pip_dependency_version(dependency: str) -> str:
    """Return *dependency* with any version specifier / marker / extra stripped.

    Examples::

        "chumicro-timing>=0.1"      -> "chumicro-timing"
        "chumicro-timing[extra]"    -> "chumicro-timing"
        "chumicro-timing; python_version>='3.11'" -> "chumicro-timing"
    """
    return _DEPENDENCY_VERSION_SPLITTER.split(dependency, maxsplit=1)[0].strip()


def library_name_from_pip_dependency(dependency: str) -> str | None:
    """Return the workspace library name for a ``chumicro-*`` pip dependency.

    Parses a ``project.dependencies`` entry (including PEP 508 version
    specifiers and extras) and returns the bare library directory name.

    Returns ``None`` for dependencies that are not intra-workspace
    (anything without the ``chumicro-`` prefix).

    Examples::

        "chumicro-timing>=0.1"  -> "timing"
        "chumicro-runner"       -> "runner"
        "pyserial"              -> None

    Args:
        dependency: A ``project.dependencies`` entry from ``pyproject.toml``.
    """
    name = strip_pip_dependency_version(dependency)
    if not name.startswith("chumicro-"):
        return None
    return name[len("chumicro-"):]


def library_name_from_module(module_name: str) -> str | None:
    """Return the workspace library name for a ``chumicro_*`` Python module.

    Handles dotted paths: ``chumicro_timing.ticks`` still resolves to
    ``timing``.  Returns ``None`` for modules that are not part of a
    ChuMicro library.

    Examples::

        "chumicro_timing"        -> "timing"
        "chumicro_timing.ticks"  -> "timing"
        "time"                   -> None

    Args:
        module_name: A Python module name as written in an ``import``
            statement.
    """
    if not module_name.startswith("chumicro_"):
        return None
    return module_name.removeprefix("chumicro_").split(".", 1)[0]


class _TomllibModule(Protocol):
    """Minimal structural interface shared by ``tomllib`` and ``tomli``.

    Both modules expose ``load(fp)`` returning a ``dict[str, Any]``; we
    use only that one entry point.  A ``Protocol`` keeps the lazy-import
    return type precise without forcing a dependency on either module
    at import time.
    """

    def load(self, fp: Any, /) -> dict[str, Any]: ...


def load_tomllib() -> _TomllibModule:
    """Import tomllib lazily.

    Stdlib from 3.11+; the ``tomli`` backport covers 3.9–3.10.
    Keeping this out of module scope lets ``workspace`` be imported on a
    fresh clone before third-party packages are installed.
    """
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[import-not-found,no-redef]
    # Both modules expose ``load(fp) -> dict[str, Any]``; cast to the
    # shared structural protocol so callers get precise typing.
    return tomllib  # pyright: ignore[reportReturnType]


def read_runtime_versions() -> dict[str, Any]:
    """Read pinned target runtime versions from ``target-runtimes.toml``."""
    tomllib = load_tomllib()
    with (ROOT / "target-runtimes.toml").open("rb") as runtimes_file:
        return tomllib.load(runtimes_file)


@functools.cache
def read_platforms(package_dir: Path) -> tuple[str, ...]:
    """Read ``[tool.chumicro].platforms`` from a package's ``pyproject.toml``.

    Returns :data:`ALL_PLATFORMS` when the key or section is absent.
    Libraries default to targeting all three runtimes.

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
    """Find directories under support/, libraries/, and workbench/ that contain a pyproject.toml.

    Defines which packages exist in the workspace.  The task runner,
    IDE sync, and coverage tools all derive their package lists from
    this function.  No hard-coded package lists exist anywhere in the
    codebase.

    See Decision 0032 for why ``workbench/`` exists alongside
    ``libraries/``.

    Results are cached for the lifetime of the process.
    """
    global _package_dirs_cache
    if _package_dirs_cache is not None:
        return list(_package_dirs_cache)
    package_dirs: list[Path] = []
    for parent_dir in [ROOT / "support", ROOT / "libraries", ROOT / "workbench"]:
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
    to device-library directories only.  Excludes ``support/`` packages
    (internal, not published) and ``workbench/`` packages (host-only
    publishable tools; Decision 0032).  Used by bundle staging,
    cross-runtime tests, and docs: all CircuitPython / MicroPython
    concerns that don't apply to host-only packages.
    """
    return [
        package_dir for package_dir in discover_package_dirs()
        if package_dir.parent.name == "libraries"
    ]


def discover_workbench_dirs() -> list[Path]:
    """Return package directories that live under ``workbench/``.

    Counterpart to :func:`discover_library_dirs` for host-only
    publishable tools.  Used by the ``test-workbench-functional`` task to drive
    pytest at every workbench package's ``functional_tests/``
    directory.  Device-side routing is not relevant: workbench
    packages are CPython-only and reach hardware through the public
    ``chumicro_deploy`` API (or through their own subprocess shells)
    rather than the test-harness plugin.
    """
    return [
        package_dir for package_dir in discover_package_dirs()
        if package_dir.parent.name == "workbench"
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

    Includes ``scripts/`` and ``.github/skills/`` (both host-only
    tooling) plus the ``src/``, ``tests/``, ``functional_tests/``, and
    ``examples/`` subdirectories of every discovered package.  Package
    subdirectories that don't exist are skipped.
    """
    paths = ["scripts", ".github/skills"]
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
    """Return package directories that contain a ``mkdocs.yml``.

    Args:
        package_dirs: Package directories to filter.  When ``None``,
            uses :func:`discover_package_dirs`, which covers both
            ``libraries/`` and ``workbench/`` packages so docs-deploy
            and the landing page pick up host-only tools alongside
            device libraries.  Support packages are not published and
            typically don't carry ``mkdocs.yml``, so they drop out at
            the filter step below.
    """
    candidates = package_dirs if package_dirs is not None else discover_package_dirs()
    return [
        package_dir for package_dir in candidates
        if (package_dir / "mkdocs.yml").exists()
    ]


def run_git(
    *arguments: str,
    cwd: Path | None = None,
    capture: bool = True,
    check: bool = False,
    input_text: str | None = None,
) -> subprocess.CompletedProcess:
    """Run a ``git`` subprocess from the repository root.

    Workspace-wide wrapper that consolidates the dozen+ inline
    ``subprocess.run(["git", ...])`` call sites scattered across
    ``repo_layout.py``, ``bundle_manager.py``, ``docs_deploy.py``, and
    ``run.py``.  Defaults match the most common usage:

    - ``cwd`` defaults to :data:`ROOT`
    - ``capture=True`` returns text stdout/stderr (set ``False`` to let
      output flow to the terminal)
    - ``check=False`` lets callers inspect the return code instead of
      raising

    Args:
        *arguments: Arguments passed after ``git`` (e.g. ``"rev-parse",
            "HEAD"``).
        cwd: Working directory; ``None`` means the repository root.
        capture: When ``True``, capture stdout/stderr as text.
        check: When ``True``, raise :class:`subprocess.CalledProcessError`
            on a non-zero exit code.
        input_text: Optional stdin text for the subprocess.
    """
    return subprocess.run(
        ["git", *arguments],
        cwd=cwd or ROOT,
        capture_output=capture,
        text=capture,
        check=check,
        input=input_text,
    )


def is_ref_reachable(reference: str) -> bool:
    """Return True if *reference* is a valid git ref that can be diffed against.

    Args:
        reference: Git ref to check (e.g. ``"origin/main"``).
    """
    return run_git("rev-parse", "--verify", reference).returncode == 0


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
        # Union four git queries to catch all local work regardless of
        # commit state:
        #   1. Committed changes on this branch vs origin/main
        #   2. Unstaged working-tree changes to tracked files
        #   3. Staged but uncommitted changes
        #   4. Untracked, non-ignored files (new modules / tests an
        #      agent created but hasn't `git add`ed yet)
        # The three diff forms never list untracked files, so without
        # query 4 a package whose only changes are brand-new files
        # would escape change detection and fall to the lower default
        # coverage gate.
        for diff_args in (
            ("diff", "--name-only", "origin/main...HEAD"),
            ("diff", "--name-only"),
            ("diff", "--name-only", "--cached"),
            ("ls-files", "--others", "--exclude-standard"),
        ):
            result = run_git(*diff_args)
            if result.returncode == 0 and result.stdout.strip():
                changed.update(result.stdout.strip().splitlines())
    except (FileNotFoundError, OSError):
        # git unavailable (e.g. no .git dir).  Caller treats None as
        # "run everything" to be safe.
        return None

    if not changed:
        # No changes at all.  Also means "run everything" so the default
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
        for prefix in ("libraries/", "support/", "workbench/"):
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


# ---------------------------------------------------------------------------
# Parked libraries
# ---------------------------------------------------------------------------

#: Marker filename that parks a library.  Present at a library root, it
#: holds that library out of the *publish set* — the PyPI release
#: matrix, the device bundle, the host libraries channel, the landing
#: page, and mip validation all skip it — while leaving the library
#: fully in-tree and maintained: tests, lint, docs build, and editable
#: installs still cover it.  The file's contents are a free-text note
#: recording why and when the library was parked.  See Decision 0107.
PARKED_MARKER = "PARKED"


def is_parked(library_dir: Path) -> bool:
    """Return True when *library_dir* carries a :data:`PARKED_MARKER` file.

    A parked library stays in the tree and stays green — tests, lint,
    docs, and editable install still cover it — but is held back from
    every publish channel until a real consumer appears.  Publish and
    bundle enumerations consult this predicate and skip parked
    libraries; discovery used for testing and linting does not.  This
    is the single shared check for the marker (Decision 0107); every
    consumer routes through it rather than reading the file itself.

    Args:
        library_dir: Root directory of the library.
    """
    return (library_dir / PARKED_MARKER).is_file()


def read_parked_reason(library_dir: Path) -> str | None:
    """Return the recorded reason a library is parked, or ``None``.

    Reads the free-text contents of the :data:`PARKED_MARKER` file (the
    why and when).  Returns ``None`` when the library is not parked or
    the marker is empty.

    Args:
        library_dir: Root directory of the library.
    """
    marker = library_dir / PARKED_MARKER
    if not marker.is_file():
        return None
    return marker.read_text().strip() or None


def find_publishable_packages(*, include_parked: bool = False) -> list[str]:
    """Return relative paths to every publishable package in the workspace.

    A package is publishable when it has both a ``VERSION`` file (which
    provides the release version) and a ``pyproject.toml`` (which
    defines build metadata).  Publishable packages live under
    ``libraries/`` (device libraries that ship to PyPI and the
    CircuitPython bundle), ``workbench/`` (host-only tools that ship
    to PyPI only; Decision 0032), or ``support/`` (host-only
    infrastructure that ships to PyPI only, no device bundle).  A
    support package stays unpublished until it gains a ``VERSION`` file,
    at which point it joins the publish set as PyPI-only (Decision
    0111); ``chumicro-test-harness`` is the first, which is what makes
    the ``[test]`` extra every library declares installable.  Because
    this enumeration keys on the ``VERSION`` file, a VERSION-less
    support package is skipped here while staying editable-installed via
    :func:`find_support_packages`.

    Parked libraries (those carrying a :data:`PARKED_MARKER`; Decision
    0107) are excluded by default — they stay in-tree and maintained
    but are held out of the publish set.  Pass ``include_parked=True``
    for dev-time consumers that must still see them: the
    editable-install step, for one, keeps parked libraries importable
    so their tests keep running.

    Args:
        include_parked: When True, parked libraries are returned
            alongside the rest.  Defaults to False (publish semantics).
    """
    packages = []
    for publishable_root in (ROOT / "libraries", ROOT / "workbench", ROOT / "support"):
        if not publishable_root.is_dir():
            continue
        for version_file in sorted(publishable_root.rglob("VERSION")):
            package_dir = version_file.parent
            if not (package_dir / "pyproject.toml").exists():
                continue
            if not include_parked and is_parked(package_dir):
                continue
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


def order_libraries_by_dependency(
    library_names: list[str],
    deps_for: Callable[[str], list[str]],
) -> list[str]:
    """Topologically sort library names so each library's deps come first.

    Used by validators (e.g. ``validate_mip_install``) to make sure a
    dependency is installed before the library that depends on it.

    Args:
        library_names: Library names to order (e.g. ``["runner", "timing"]``).
        deps_for: Callable returning the intra-workspace dependency
            library names for a given library name.  Dependencies that
            aren't in *library_names* are silently ignored (they're not
            in the validation set).

    Returns:
        A new list containing every entry of *library_names*, ordered
        so that each library follows everything it depends on.

    Raises:
        ValueError: If a dependency cycle is detected.
    """
    requested = set(library_names)
    permanent: set[str] = set()
    temporary: set[str] = set()
    ordered: list[str] = []

    def visit(name: str) -> None:
        if name in permanent:
            return
        if name in temporary:
            cycle_path = " → ".join([*sorted(temporary), name])
            raise ValueError(f"Dependency cycle detected: {cycle_path}")
        temporary.add(name)
        for dep in deps_for(name):
            if dep in requested:
                visit(dep)
        temporary.discard(name)
        permanent.add(name)
        ordered.append(name)

    for name in library_names:
        visit(name)
    return ordered


def release_tags(library_name: str, *, stable_only: bool = False) -> list[str]:
    """Return release tags for a publishable package, sorted newest first.

    Tags are emitted by ``release.yml`` as ``chumicro-<name>-v<version>``
    (with an optional ``-experimental`` suffix).  The glob here matches that
    canonical format for both ``libraries/`` and ``workbench/`` packages.

    ``git``'s ``-v:refname`` version sort, with no ``versionsort.suffix``
    configured, ranks a pre-release tag (``…-v0.10.0-experimental``) *above*
    the bare stable tag of the same version (``…-v0.10.0``).  Callers that
    need the last *stable* release — the API-breakage baseline compares the
    stable channel against it — must pass ``stable_only=True`` so an
    experimental tag can't shadow the stable one it was cut ahead of.

    Args:
        library_name: Package basename (e.g. ``"timing"`` or ``"deploy"``).
        stable_only: Drop pre-release tags (any ``-<suffix>`` after the
            version, e.g. ``-experimental``), leaving only bare-version
            stable releases.  Defaults to ``False`` (every tag).
    """
    prefix = f"chumicro-{library_name}-v"
    result = run_git(
        "tag", "--list", f"{prefix}*", "--sort=-v:refname",
    )
    if result.returncode != 0 or not result.stdout.strip():
        return []
    tags = result.stdout.strip().splitlines()
    if stable_only:
        # A pre-release marker is a ``-`` in the version portion (SemVer
        # denotes pre-releases that way); a bare stable version has none.
        tags = [tag for tag in tags if "-" not in tag[len(prefix):]]
    return tags


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

#: Paths within a publishable package that require a VERSION bump when
#: changed.  ``"src"`` matches as a directory prefix (any file under
#: ``src/``), while ``"pyproject.toml"`` matches as an exact filename at
#: the package root.  See ``plans/decisions/0002-per-library-version-files.md``.
RELEASE_RELEVANT = {"src", "pyproject.toml"}

#: Workspace directories that hold publishable packages.  All three feed
#: the same VERSION + check-api gate: workbench packages follow the same
#: release lifecycle as libraries minus bundle staging (Decision 0032),
#: and support packages do the same once they carry a VERSION file
#: (Decision 0111 — PyPI-only, no bundle).
PUBLISHABLE_ROOTS = ("libraries", "workbench", "support")


def changed_files(base_reference: str) -> list[str]:
    """Return files changed between *base_reference* and HEAD."""
    # Three-dot syntax finds changes since the merge-base, which is the
    # standard PR diff.  It fails in shallow clones (CI) where the
    # merge-base commit is not fetched.  The two-arg fallback gives a
    # full diff between the two refs: a superset that may include extra
    # files, but is safe (we'd rather over-test than under-test).
    result = run_git("diff", "--name-only", f"{base_reference}...HEAD")
    if result.returncode != 0:
        result = run_git("diff", "--name-only", base_reference, "HEAD")
    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr.strip()}")
    return [line for line in result.stdout.strip().splitlines() if line]


#: Environment variable naming the commit a CI push started from.  The
#: workflow sets it to ``github.event.before``; see ``effective_diff_base``.
DIFF_BASE_ENVIRONMENT_VARIABLE = "CHUMICRO_DIFF_BASE"

#: What GitHub sends as ``github.event.before`` for a branch's first
#: push.  There is no prior commit to diff against, so it is ignored.
_ZERO_SHA = "0" * 40


def effective_diff_base(base_reference: str) -> str:
    """Return the ref the changed-file gates should diff HEAD against.

    Resolved in three steps:

    1. ``$CHUMICRO_DIFF_BASE`` when it names a commit this clone holds.
       CI sets it to ``github.event.before``, the commit the branch
       pointed at before the push, so a push carrying several commits
       is examined whole.  Without it the ``HEAD^`` fallback below sees
       only the tip commit, and release-relevant changes in a push's
       earlier commits skip the VERSION and API gates entirely: on
       2026-07-28 seventeen ``pyproject.toml`` descriptions landed
       unbumped two commits back in a five-commit push, under a green
       CI, and reached neither channel until the next wave.  The
       override is ignored when unset, empty, the all-zero SHA of a
       first push, or a SHA this clone cannot resolve (force-pushed
       away), each of which falls through to step 2.
    2. ``HEAD^`` when *base_reference* IS HEAD.  On a direct-to-main
       push ``origin/main`` is the pushed commit, so an
       ``origin/main...HEAD`` diff is empty and every gate silently
       passes.  The first parent at least covers the tip commit.
    3. *base_reference* unchanged — when it doesn't resolve, when it
       differs from HEAD, or when HEAD has no parent (root commit).
       Callers keep their existing empty-diff behavior in those cases.
    """
    override = os.environ.get(DIFF_BASE_ENVIRONMENT_VARIABLE, "").strip()
    if override and override != _ZERO_SHA:
        resolved = run_git("rev-parse", "--verify", f"{override}^{{commit}}")
        if resolved.returncode == 0:
            print(
                f"NOTE: diffing against ${DIFF_BASE_ENVIRONMENT_VARIABLE} "
                f"({override}) — the commit this push started from."
            )
            return override
        print(
            f"NOTE: ${DIFF_BASE_ENVIRONMENT_VARIABLE} ({override}) does not "
            f"resolve here — falling back to {base_reference}."
        )

    base = run_git("rev-parse", "--verify", f"{base_reference}^{{commit}}")
    head = run_git("rev-parse", "--verify", "HEAD^{commit}")
    if base.returncode != 0 or head.returncode != 0:
        return base_reference
    if base.stdout.strip() != head.stdout.strip():
        return base_reference
    parent = run_git("rev-parse", "--verify", "HEAD^^{commit}")
    if parent.returncode != 0:
        return base_reference
    print(f"NOTE: {base_reference} == HEAD (direct-to-main push) — diffing against HEAD^.")
    return "HEAD^"


def changed_publishable_packages(base_reference: str) -> set[tuple[str, str]]:
    """Return ``(parent, name)`` pairs for packages with release-relevant changes.

    Covers ``libraries/``, ``workbench/``, and ``support/`` (the
    pre-merge VERSION + API gates apply uniformly to every publishable
    package; Decisions 0032 and 0111).  Returning the parent directory
    alongside the name lets callers construct paths and messages without
    a second lookup.

    parts[2] is checked against :data:`RELEASE_RELEVANT`:
    ``"src"`` acts as a directory prefix (any file under ``src/``
    qualifies) while ``"pyproject.toml"`` is an exact match
    (``len(parts) == 3`` at the package root).
    """
    changed = changed_files(base_reference)
    packages: set[tuple[str, str]] = set()
    for path in changed:
        parts = path.split("/")
        if (
            len(parts) >= 3
            and parts[0] in PUBLISHABLE_ROOTS
            and parts[2] in RELEASE_RELEVANT
        ):
            packages.add((parts[0], parts[1]))
    return packages
