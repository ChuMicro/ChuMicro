"""Build-time guard: curated-library sdists must ship their full content.

A curated workspace pulls chumicro libraries from their PyPI sdists into
the user's ``libraries/<name>/`` folder, then runs the deploy walker over
them.  For that to work the sdist has to carry what a curated consumer
needs — not just ``src/``.  Each library's ``pyproject.toml`` therefore
ships ``tests/``, ``examples/``, and ``docs/`` in the sdist, and declares
a ``[test]`` extra so the consumer can ``pip install chumicro-<lib>[test]``
and actually run the shipped tests.

Shipping the directories and declaring the extra are two independent
contracts a future edit could silently break (drop a line from
``[tool.hatch.build.targets.sdist].only-include``, delete the
``[project.optional-dependencies]`` block).  This guard runs after
``scripts/run.py build`` and fails the build if either regresses, so the
break is caught before it reaches PyPI.
"""

from __future__ import annotations

import tarfile
import tomllib
from pathlib import Path

#: Directories every library sdist must contain (in addition to ``src/``).
REQUIRED_SDIST_DIRS = ("tests", "examples", "docs")


def _sdist_distribution_name(pyproject: dict) -> str:
    """Return the normalized sdist filename stem for a project.

    A built sdist is named ``<name>-<version>.tar.gz`` with ``name``
    normalized per PEP 503/625 — runs of ``-``/``_``/``.`` collapsed to
    a single ``_``.  ``chumicro-http-server`` -> ``chumicro_http_server``.
    """
    raw = pyproject["project"]["name"]
    normalized = raw.lower()
    for separator in ("-", "."):
        normalized = normalized.replace(separator, "_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized


def check_library_sdist(library_dir: Path) -> list[str]:
    """Return a list of human-readable problems with one library's sdist.

    Empty list means the library's freshly built sdist carries every
    required directory and its ``pyproject.toml`` still declares the
    ``[test]`` extra.  Each returned string names the library and the
    specific contract that regressed.
    """
    name = library_dir.name
    pyproject_path = library_dir / "pyproject.toml"
    if not pyproject_path.is_file():
        return [f"{name}: no pyproject.toml"]

    pyproject = tomllib.loads(pyproject_path.read_text())
    version = (library_dir / "VERSION").read_text().strip()
    distribution = _sdist_distribution_name(pyproject)
    sdist_path = library_dir / "dist" / f"{distribution}-{version}.tar.gz"

    problems: list[str] = []

    test_extra = (
        pyproject.get("project", {})
        .get("optional-dependencies", {})
        .get("test")
    )
    if not test_extra:
        problems.append(
            f"{name}: pyproject.toml is missing the [project."
            "optional-dependencies] 'test' extra — a curated consumer "
            f"could not 'pip install chumicro-{name}[test]' to run the "
            "shipped tests"
        )

    if not sdist_path.is_file():
        problems.append(
            f"{name}: built sdist not found at "
            f"{sdist_path.relative_to(library_dir.parent.parent)} "
            "(was 'build' run for this version?)"
        )
        return problems

    base = f"{distribution}-{version}"
    with tarfile.open(sdist_path, "r:gz") as archive:
        members = archive.getnames()
    present_top = {
        member[len(base) + 1:].split("/", 1)[0]
        for member in members
        if member.startswith(f"{base}/") and "/" in member[len(base) + 1:]
    }
    for required in REQUIRED_SDIST_DIRS:
        if required not in present_top:
            problems.append(
                f"{name}: sdist {sdist_path.name} is missing '{required}/' "
                "— extend [tool.hatch.build.targets.sdist].only-include"
            )

    return problems


def check_all_library_sdists(library_dirs: list[Path]) -> list[str]:
    """Aggregate :func:`check_library_sdist` problems across libraries."""
    problems: list[str] = []
    for library_dir in library_dirs:
        problems.extend(check_library_sdist(library_dir))
    return problems
