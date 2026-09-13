"""Build-time guard: curated-library sdists must ship their full content.

A curated workspace pulls chumicro libraries from their PyPI sdists into
the user's ``libraries/<name>/`` folder, then runs the deploy walker over
them.  For that to work the sdist has to carry what a curated consumer
needs, not just ``src/``.  Each library's ``pyproject.toml`` therefore
ships ``tests/``, ``examples/``, and ``docs/`` in the sdist, and declares
a ``[test]`` extra so the consumer can ``pip install chumicro-<lib>[test]``
and actually run the shipped tests.

Shipping the directories and declaring the extra are two independent
contracts a future edit could silently break (drop a line from
``[tool.hatch.build.targets.sdist].only-include``, delete the
``[project.optional-dependencies]`` block).  A third contract rides
along: every package declares ``License: MIT``, so its dir carries a
byte-identical copy of the repo root ``LICENSE`` and the built sdist
ships it (wheels land it in ``.dist-info/licenses/``).  This guard runs
after ``scripts/run.py build`` and fails the build if any of the three
regresses, so the break is caught before it reaches PyPI.
"""

from __future__ import annotations

import tarfile
import tomllib
from pathlib import Path

#: Directories every library sdist must contain (in addition to ``src/``).
REQUIRED_SDIST_DIRS = ("tests", "examples", "docs")


def _declared_data_files(library_dir: Path) -> list[Path]:
    """Return the on-disk data files a library's package declares.

    A module names sibling data files it opens at runtime via
    ``__chumicro_data_files__`` (e.g. ``chumicro_sockets/_ca_bundle.der``);
    the ``.py`` walk can't otherwise see them.  Reuses
    ``bundle_manager._bundle_data_files`` so the sdist gate discovers the
    same set the mip/circup bundler stages.  Returns absolute paths of the
    files that exist under the library's ``src/`` package (empty when the
    library has no importable package).
    """
    from bundle_manager import _bundle_data_files
    from repo_layout import find_package_dir

    package_dir = find_package_dir(library_dir)
    if package_dir is None:
        return []
    python_files = [
        py_file
        for py_file in sorted(package_dir.rglob("*.py"))
        if "__pycache__" not in py_file.relative_to(package_dir).parts
    ]
    return _bundle_data_files(python_files)


def _sdist_distribution_name(pyproject: dict) -> str:
    """Return the normalized sdist filename stem for a project.

    A built sdist is named ``<name>-<version>.tar.gz`` with ``name``
    normalized per PEP 503/625: runs of ``-``/``_``/``.`` collapsed to
    a single ``_``.  ``chumicro-http-server`` -> ``chumicro_http_server``.
    """
    raw = pyproject["project"]["name"]
    normalized = raw.lower()
    for separator in ("-", "."):
        normalized = normalized.replace(separator, "_")
    while "__" in normalized:
        normalized = normalized.replace("__", "_")
    return normalized


def check_library_sdist(
    library_dir: Path,
    *,
    canonical_license: Path | None = None,
) -> list[str]:
    """Return a list of human-readable problems with one library's sdist.

    Empty list means the library's freshly built sdist carries every
    required directory plus the license text, and its ``pyproject.toml``
    still declares the ``[test]`` extra.  Each returned string names the
    library and the specific contract that regressed.

    *canonical_license* is the license file every package copy must match
    byte-for-byte; ``None`` resolves to the repo root ``LICENSE``.
    """
    from repo_layout import ROOT

    name = library_dir.name
    pyproject_path = library_dir / "pyproject.toml"
    if not pyproject_path.is_file():
        return [f"{name}: no pyproject.toml"]

    pyproject = tomllib.loads(pyproject_path.read_text())
    version = (library_dir / "VERSION").read_text().strip()
    distribution = _sdist_distribution_name(pyproject)
    sdist_path = library_dir / "dist" / f"{distribution}-{version}.tar.gz"

    problems: list[str] = []

    # Every published artifact declares License: MIT, so it must carry
    # the actual text (PyPI wheels land it in .dist-info/licenses/).
    # The per-package copy exists for the build; the root file is the
    # single source of truth, so drift fails the build loudly.  A
    # library that absorbed third-party code appends that code's
    # copyright lines after the canonical text, so the check is a
    # prefix match, not equality.
    if canonical_license is None:
        canonical_license = ROOT / "LICENSE"
    license_path = library_dir / "LICENSE"
    if not license_path.is_file():
        problems.append(
            f"{name}: no LICENSE file — copy the repo root LICENSE into "
            "the package dir (published artifacts must carry the text "
            "they declare)"
        )
    elif not license_path.read_bytes().startswith(canonical_license.read_bytes()):
        problems.append(
            f"{name}: LICENSE does not start with the repo root LICENSE "
            "— the root text is canonical; third-party attributions "
            "append after it"
        )

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

    if f"{base}/LICENSE" not in members:
        problems.append(
            f"{name}: sdist {sdist_path.name} is missing LICENSE — keep "
            '[project] license-files = ["LICENSE"] and the package-dir copy'
        )

    # Each declared __chumicro_data_files__ sibling (e.g. a bundled .der)
    # must ride along in the sdist too: a curated consumer's deploy walker
    # reads it from the unpacked tree, and a sdist config that narrows
    # ``src/`` to ``*.py`` would silently drop it (same failure class as
    # the missing-dir checks above, but for non-.py data).
    member_set = set(members)
    for data_source in _declared_data_files(library_dir):
        relative = data_source.relative_to(library_dir).as_posix()
        if f"{base}/{relative}" not in member_set:
            problems.append(
                f"{name}: sdist {sdist_path.name} is missing declared data "
                f"file '{relative}' (__chumicro_data_files__) — a curated "
                "consumer would install the module without its data file"
            )

    return problems


def check_all_library_sdists(
    library_dirs: list[Path],
    *,
    canonical_license: Path | None = None,
) -> list[str]:
    """Aggregate :func:`check_library_sdist` problems across libraries."""
    problems: list[str] = []
    for library_dir in library_dirs:
        problems.extend(
            check_library_sdist(
                library_dir, canonical_license=canonical_license,
            ),
        )
    return problems
