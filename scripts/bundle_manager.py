"""Stage bundle artifacts for a library's mip/circup distribution.

Copies deployable .py source files, compiles .mpy bytecode with mpy-cross,
and generates a mip-compatible package.json manifest.

CircuitPython and MicroPython use different mpy-cross compilers that produce
incompatible .mpy files (different magic bytes: 'C' vs 'M').  The bundle
stages separate directories for each runtime:

- ``circuitpython-10.x-mpy/``: compiled with CircuitPython mpy-cross,
  consumed by circup via zip bundles.
- ``mpy6/``: compiled with MicroPython mpy-cross, consumed by mip via
  ``package.json`` manifests.

The two-repo bundle strategy (stable vs. experimental) is defined in
``plans/decisions/0018-distribution-bundle-repo.md``.

Subcommands:
    stage              Stage a single library's bundle artifacts.
    stage-matrix       Stage artifacts for libraries in a JSON matrix (--matrix).
    readme             Generate a bundle repo README.md.
    circup-zip         Build circup-format zip bundles from a bundle directory.
    patch-experimental Patch pyproject.toml + README.md for experimental channel release.
    next-date-tag      Print the next available date-based tag for a bundle repo
                       (``--reuse-if-clean`` reuses HEAD's tag on a no-change re-run).
    finalize-tag       Pin staged package.json dep refs to the release tag and
                       print it (next-date-tag plus dep pinning; what the
                       release workflows call before bundle_push).

Examples:
    python scripts/bundle_manager.py stage libraries/timing 0.1.0 .bundle-staging
    python scripts/bundle_manager.py stage libraries/timing 0.1.0 .bundle-staging \\
        --cp-mpy-cross .tools/circuitpython-10.1.4/mpy-cross/build/mpy-cross \\
        --mp-mpy-cross mpy-cross
    python scripts/bundle_manager.py stage-matrix .bundle-staging --matrix '{"include": [...]}'
    python scripts/bundle_manager.py readme --experimental -o README.md
    python scripts/bundle_manager.py circup-zip .bundle-repo .circup-zips \\
        --repo-name ChuMicro-Bundle
    python scripts/bundle_manager.py patch-experimental libraries/timing
    python scripts/bundle_manager.py next-date-tag .bundle-repo
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Bundle repository names and mpy folder layout live in
# ``scripts/bundle_layout`` so the producer (this module) and the
# consumer (``validate_mip_install``) cannot drift.
from bundle_layout import (
    CP_MPY_FOLDER,
    EXPERIMENTAL_BUNDLE_REPO,
    MPY_FORMAT_FOLDER,
    STABLE_BUNDLE_REPO,
)
from chumicro_deploy.runtime_marker import (
    DEVICE_RUNTIMES,
    file_targets_runtime,
    is_test_support_module,
)
from repo_layout import (
    GITHUB_ORG,
    ROOT,
    find_package_dir,
    is_parked,
    load_tomllib,
    read_pyproject_description,
    run_git,
    strip_pip_dependency_version,
)
from shared import TEMPLATES_DIR, resolve_cp_mpy_cross, resolve_mp_mpy_cross


def _find_bundle_modules(
    library_dir: Path,
    *,
    target_runtime: str | frozenset[str] | None = None,
) -> tuple[str, Path, list[Path]]:
    """Discover the package name, package dir, and deployable .py files.

    Args:
        library_dir: Root directory of the library.
        target_runtime: Runtime selector applied via the
            ``__chumicro_runtimes__`` marker (Decisions 0037 + 0044).
            ``"circuitpython"`` / ``"micropython"`` for per-runtime mpy
            bundles.  :data:`DEVICE_RUNTIMES` (frozenset of both MCU
            runtimes) for the universal source bundle, which drops files
            marked exclusively for ``cpython`` so they land only in the
            PyPI sdist / wheel.  ``None`` skips filtering.
            Files without a marker always ship (default-safe).

    Returns:
        ``(package_name, package_dir, python_files)`` where *python_files*
        are the ``.py`` modules destined for the requested bundle.
        ``__pycache__`` is always excluded.
    """
    package_dir = find_package_dir(library_dir)
    if package_dir is None:
        sys.exit(f"No importable package under {library_dir / 'src'}")

    python_files = [
        py_file
        for py_file in sorted(package_dir.rglob("*.py"))
        if "__pycache__" not in py_file.relative_to(package_dir).parts
        and file_targets_runtime(py_file, target_runtime=target_runtime)
        and not is_test_support_module(py_file)
    ]
    return package_dir.name, package_dir, python_files


def _data_files_from(python_file: Path) -> list[str]:
    """Return the string entries of a module-level
    ``__chumicro_data_files__`` assignment, or ``[]`` when absent.

    Read via AST (no import) so it works on a host that can't import
    the device module.  Names sibling data files the module opens at
    runtime (e.g. ``chumicro_sockets/_ca_bundle.der``) that the .py /
    .mpy walk can't otherwise discover.
    """
    try:
        tree = ast.parse(python_file.read_bytes())
    except (SyntaxError, ValueError):
        return []
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Name)
                and target.id == "__chumicro_data_files__"
                and isinstance(node.value, (ast.Tuple, ast.List))
            ):
                return [
                    element.value
                    for element in node.value.elts
                    if isinstance(element, ast.Constant)
                    and isinstance(element.value, str)
                ]
    return []


def _bundle_data_files(python_files: list[Path]) -> list[Path]:
    """Return sibling data files declared by *python_files*.

    A module declares ``__chumicro_data_files__ = ("name", ...)`` to
    name files it opens at runtime that the .py / .mpy walk can't see.
    Returns the existing sibling files (in first-declared order,
    de-duplicated) so the bundle ships them next to the module; a named
    file absent from disk is skipped.
    """
    data_files: list[Path] = []
    for python_file in python_files:
        for data_name in _data_files_from(python_file):
            data_source = python_file.parent / data_name
            if data_source.is_file() and data_source not in data_files:
                data_files.append(data_source)
    return data_files


def _read_chumicro_dependencies(library_dir: Path) -> list[str]:
    """Return chumicro-* dependency names from pyproject.toml.

    Only intra-workspace dependencies are relevant for mip manifests.

    Args:
        library_dir: Root directory of the library.
    """
    tomllib = load_tomllib()
    with open(library_dir / "pyproject.toml", "rb") as pyproject_file:
        data = tomllib.load(pyproject_file)
    dependencies = data.get("project", {}).get("dependencies", [])
    return [dependency for dependency in dependencies if dependency.strip().startswith("chumicro-")]


def _dependency_to_mip_reference(dependency: str, bundle_repo: str) -> str:
    """Convert 'chumicro-timing>=0.1' to a mip github reference.

    Args:
        dependency: PyPI dependency string (e.g. ``"chumicro-timing>=0.1"``).
        bundle_repo: Bundle repository name (e.g. ``"ChuMicro-Bundle"``).
    """
    package = strip_pip_dependency_version(dependency).replace("-", "_")
    return f"github:{GITHUB_ORG}/{bundle_repo}/{package}"


def _dependency_to_mpy_mip_reference(
    dependency: str,
    bundle_repo: str,
    mpy_folder: str = MPY_FORMAT_FOLDER,
) -> str:
    """Convert 'chumicro-timing>=0.1' to an mpy mip github reference.

    *mpy_folder* is the format folder the manifest being written lives in,
    so a package's deps resolve inside its own ABI generation.  It is a
    parameter rather than the module constant because the bundle carries a
    folder per live ABI once one bumps (Decision 0112): a manifest staged
    into a newer folder whose deps pointed at the older one would install a
    mixed-format tree onto the board.

    Args:
        dependency: PyPI dependency string (e.g. ``"chumicro-timing>=0.1"``).
        bundle_repo: Bundle repository name (e.g. ``"ChuMicro-Bundle"``).
        mpy_folder: Format folder to resolve the dependency within.
    """
    package = strip_pip_dependency_version(dependency).replace("-", "_")
    return f"github:{GITHUB_ORG}/{bundle_repo}/{mpy_folder}/{package}"


def _compile_mpy(python_file: Path, mpy_file: Path, mpy_cross: str) -> None:
    """Compile a single .py file to .mpy.

    Args:
        python_file: Source Python file.
        mpy_file: Destination .mpy file.
        mpy_cross: Path to the mpy-cross binary.
    """
    mpy_file.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [mpy_cross, "-o", str(mpy_file), str(python_file)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"mpy-cross failed on {python_file}:\n{result.stderr}")


def build_bundle(
    library_dir: Path,
    version: str,
    staging_dir: Path,
    *,
    cp_mpy_cross: str | None = None,
    mp_mpy_cross: str | None = None,
    experimental: bool = False,
) -> None:
    """Stage bundle artifacts for a single library.

    Creates ``<staging_dir>/<package_name>/`` containing .py source and a
    mip package.json manifest.

    When *cp_mpy_cross* is provided, compiles CircuitPython .mpy bytecode
    into ``<staging_dir>/circuitpython-10.x-mpy/<package_name>/`` for circup
    zip bundles.

    When *mp_mpy_cross* is provided, compiles MicroPython .mpy bytecode
    into ``<staging_dir>/mpy6/<package_name>/`` with a package.json manifest
    for mip.

    CircuitPython and MicroPython mpy-cross produce incompatible .mpy files
    (magic byte 'C' vs 'M'), so each runtime requires its own compiler.

    Args:
        library_dir: Root directory of the library.
        version: Version string for the manifest.
        staging_dir: Output directory for staged artifacts.
        cp_mpy_cross: Path to CircuitPython's mpy-cross binary.
        mp_mpy_cross: Path to MicroPython's mpy-cross binary.
        experimental: When True, package.json URLs point to the
            experimental bundle repo.
    """
    package_name, package_dir, python_files = _find_bundle_modules(
        library_dir, target_runtime=DEVICE_RUNTIMES,
    )
    if not python_files:
        sys.exit(f"No deployable .py files found in {package_dir}")

    bundle_repo = EXPERIMENTAL_BUNDLE_REPO if experimental else STABLE_BUNDLE_REPO
    output_dir = staging_dir / package_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # Copy .py source files into the root package directory.
    for source_file in python_files:
        relative_path = source_file.relative_to(package_dir)
        python_dest_file = output_dir / relative_path
        python_dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, python_dest_file)

    # Copy sibling data files declared via __chumicro_data_files__ (e.g.
    # chumicro_sockets/_ca_bundle.der).  The .py walk can't see a runtime
    # ``open`` of these, so without staging them the mip/circup channel
    # ships the module but not its data file and a TLS connect crashes.
    data_files = _bundle_data_files(python_files)
    for data_source in data_files:
        relative_path = data_source.relative_to(package_dir)
        data_dest_file = output_dir / relative_path
        data_dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(data_source, data_dest_file)

    # Copy README.md into the bundle directory so GitHub renders it when
    # users browse the bundle repo.  The file is not included in circup zips
    # (which only glob *.py and *.mpy) or mip manifests, so it never ends up
    # on-device.
    readme_source = library_dir / "README.md"
    if readme_source.exists():
        shutil.copy2(readme_source, output_dir / "README.md")

    # Generate mip package.json manifest for .py source.
    #
    # mip reads package.json to know which files to download and where to
    # place them on-device.  Each entry in "urls" is [target_path, source_url].
    # The root manifest lists .py source files: the safe universal path
    # that works on all runtimes without version matching.
    urls = []
    for source_file in python_files:
        relative_path = source_file.relative_to(package_dir)
        py_relative_path = relative_path.as_posix()
        target = f"{package_name}/{py_relative_path}"
        source = f"github:{GITHUB_ORG}/{bundle_repo}/{package_name}/{py_relative_path}"
        urls.append([target, source])
    for data_source in data_files:
        data_relative_path = data_source.relative_to(package_dir).as_posix()
        target = f"{package_name}/{data_relative_path}"
        source = f"github:{GITHUB_ORG}/{bundle_repo}/{package_name}/{data_relative_path}"
        urls.append([target, source])

    manifest: dict = {"urls": urls, "version": version}
    # Dependencies reference the same bundle repo so that experimental
    # installs pull experimental deps and stable installs pull stable deps.
    # The ref is a stage-time placeholder: the snapshot tag doesn't exist
    # yet, so finalize_bundle_tag rewrites it before the bundle push.
    mip_dependencies = [
        [_dependency_to_mip_reference(dependency, bundle_repo), _STAGE_TIME_DEP_PIN]
        for dependency in _read_chumicro_dependencies(library_dir)
    ]
    if mip_dependencies:
        manifest["deps"] = mip_dependencies

    with open(output_dir / "package.json", "w") as manifest_file:
        json.dump(manifest, manifest_file, indent=2)
        manifest_file.write("\n")

    print(f"Staged {package_name} v{version} -> {output_dir}")

    # --- CircuitPython .mpy (for circup zip bundles) ---
    #
    # CircuitPython's mpy-cross produces .mpy files with magic byte 'C'.
    # These go into circuitpython-10.x-mpy/ following Adafruit's naming
    # convention where "10.x" is the CircuitPython version range.  circup
    # consumes these via zip bundles named with the same pattern.
    # No package.json needed: circup uses zip naming, not mip manifests.
    #
    # Decision 0037: filter out files marked for other runtimes
    # (e.g. mp_esp32.py, cpython.py) so the CP bundle only ships what
    # CircuitPython devices actually use.
    if cp_mpy_cross is not None:
        _, _, cp_python_files = _find_bundle_modules(
            library_dir, target_runtime="circuitpython",
        )
        cp_mpy_dir = staging_dir / CP_MPY_FOLDER / package_name
        cp_mpy_dir.mkdir(parents=True, exist_ok=True)

        for source_file in cp_python_files:
            relative_path = source_file.relative_to(package_dir)
            mpy_dest_file = cp_mpy_dir / relative_path.with_suffix(".mpy")
            mpy_dest_file.parent.mkdir(parents=True, exist_ok=True)
            _compile_mpy(source_file, mpy_dest_file, cp_mpy_cross)

        # Data files ship raw (not compiled) next to the .mpy modules.
        for data_source in _bundle_data_files(cp_python_files):
            relative_path = data_source.relative_to(package_dir)
            data_dest_file = cp_mpy_dir / relative_path
            data_dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(data_source, data_dest_file)

        print(f"Staged {CP_MPY_FOLDER}/{package_name} (CircuitPython) -> {cp_mpy_dir}")

    # --- MicroPython .mpy (for mip install) ---
    #
    # MicroPython's mpy-cross produces .mpy files with magic byte 'M'.
    # These go into mpy6/ following MicroPython's mpy format version
    # convention.  A package.json manifest lets MicroPython users opt in
    # to .mpy bytecode via mip:
    #   mpremote mip install github:ChuMicro/ChuMicro-Bundle/mpy6/chumicro_timing
    #
    # Decision 0037: filter out files marked for other runtimes (e.g.
    # cp.py, cpython.py) so the MP bundle only ships what MicroPython
    # devices actually use.
    if mp_mpy_cross is not None:
        _, _, mp_python_files = _find_bundle_modules(
            library_dir, target_runtime="micropython",
        )
        # The folder this pass stages into.  One compiler is pinned, so one
        # folder is produced; naming it locally keeps every path and every
        # dep reference below agreeing with each other rather than each
        # reaching for the module constant on its own.
        mpy_folder = MPY_FORMAT_FOLDER
        mpy_manifest_dir = staging_dir / mpy_folder / package_name
        mpy_manifest_dir.mkdir(parents=True, exist_ok=True)

        mpy_urls = []
        for source_file in mp_python_files:
            relative_path = source_file.relative_to(package_dir)
            mpy_relative_path = relative_path.with_suffix(".mpy").as_posix()
            mpy_dest_file = mpy_manifest_dir / relative_path.with_suffix(".mpy")
            mpy_dest_file.parent.mkdir(parents=True, exist_ok=True)
            _compile_mpy(source_file, mpy_dest_file, mp_mpy_cross)
            target = f"{package_name}/{mpy_relative_path}"
            source = (
                f"github:{GITHUB_ORG}/{bundle_repo}"
                f"/{mpy_folder}/{package_name}/{mpy_relative_path}"
            )
            mpy_urls.append([target, source])

        # Data files ship raw (not compiled) and are listed in the mip
        # manifest so mip downloads them alongside the .mpy modules.
        for data_source in _bundle_data_files(mp_python_files):
            relative_path = data_source.relative_to(package_dir)
            data_relative_path = relative_path.as_posix()
            data_dest_file = mpy_manifest_dir / relative_path
            data_dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(data_source, data_dest_file)
            target = f"{package_name}/{data_relative_path}"
            source = (
                f"github:{GITHUB_ORG}/{bundle_repo}"
                f"/{mpy_folder}/{package_name}/{data_relative_path}"
            )
            mpy_urls.append([target, source])

        mpy_manifest: dict = {"urls": mpy_urls, "version": version}
        mpy_mip_dependencies = [
            [
                _dependency_to_mpy_mip_reference(
                    dependency, bundle_repo, mpy_folder,
                ),
                _STAGE_TIME_DEP_PIN,
            ]
            for dependency in _read_chumicro_dependencies(library_dir)
        ]
        if mpy_mip_dependencies:
            mpy_manifest["deps"] = mpy_mip_dependencies

        with open(mpy_manifest_dir / "package.json", "w") as mpy_manifest_file:
            json.dump(mpy_manifest, mpy_manifest_file, indent=2)
            mpy_manifest_file.write("\n")

        print(f"Staged {mpy_folder}/{package_name} (MicroPython) -> {mpy_manifest_dir}")


def stage_matrix(
    staging_dir: Path,
    matrix_json: str,
    *,
    cp_mpy_cross: str | None = None,
    mp_mpy_cross: str | None = None,
    experimental: bool = False,
) -> None:
    """Stage bundle artifacts for all libraries in a JSON matrix.

    Args:
        staging_dir: Output directory for staged artifacts.
        matrix_json: GitHub Actions matrix JSON string.
        cp_mpy_cross: Path to CircuitPython's mpy-cross binary.
        mp_mpy_cross: Path to MicroPython's mpy-cross binary.
        experimental: When True, stage as experimental channel.
    """
    data = json.loads(matrix_json)
    for entry in data["include"]:
        build_bundle(
            Path(entry["library_dir"]),
            entry["version"],
            staging_dir,
            cp_mpy_cross=cp_mpy_cross,
            mp_mpy_cross=mp_mpy_cross,
            experimental=experimental,
        )


def _derive_bundle_id(repo_name: str) -> str:
    """Derive the circup bundle_id from a bundle repository name.

    Args:
        repo_name: Bundle repository name (e.g. ``"ChuMicro-Bundle"``).
    """
    return repo_name.lower().replace("_", "-")


def _manifest_current_relpaths(package_dir: Path) -> set[Path] | None:
    """Return the package-relative paths this build declared current.

    ``build_bundle`` regenerates ``<package>/package.json`` every release,
    listing only the files the current source tree produced (the same
    manifest mip installs from).  Reading it lets the circup zips ship
    exactly the current tree even though the bundle repo on disk still
    carries a prior release's removed or renamed modules — the ``cp -r``
    overlay that merges each release onto the accumulated bundle clone
    never deletes.  Returns ``None`` when the directory has no manifest
    (not a staged bundle package).
    """
    manifest_path = package_dir / "package.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    prefix = f"{package_dir.name}/"
    relpaths: set[Path] = set()
    for entry in manifest.get("urls", []):
        if not isinstance(entry, (list, tuple)) or not entry:
            continue
        # Each manifest entry is ``[target, source]``; target is
        # ``"<package_name>/<relpath>"`` for both .py and data files.
        target = entry[0]
        if not isinstance(target, str):
            continue
        relative = target[len(prefix):] if target.startswith(prefix) else target
        relpaths.add(Path(relative))
    return relpaths


def _manifest_dependency_packages(package_dir: Path) -> list[str]:
    """Return the chumicro package names *package_dir* depends on.

    Read from the staged ``package.json`` rather than from pyproject, so
    the circup requirements and the mip manifest can never disagree: both
    project the same ``deps`` list.  Each dep is a mip reference whose
    last path segment is the package name (``github:Org/Repo/chumicro_x``).
    """
    manifest_path = package_dir / "package.json"
    if not manifest_path.is_file():
        return []
    with open(manifest_path) as manifest_file:
        manifest = json.load(manifest_file)
    packages = []
    for entry in manifest.get("deps", []):
        if not isinstance(entry, list) or not entry:
            continue
        reference = entry[0]
        if isinstance(reference, str) and reference:
            packages.append(reference.rstrip("/").rsplit("/", 1)[-1])
    return sorted(set(packages))


def _circup_requirements_text(package_dir: Path) -> str | None:
    """Return the circup ``requirements.txt`` body for *package_dir*.

    circup resolves a library's dependencies by reading
    ``requirements/<library>/requirements.txt`` out of the bundle and
    splitting each line on pip version specifiers
    (``libraries_from_requirements``).  It matches the result against the
    module names in ``lib/``, which are underscored, so the names written
    here are the import names rather than the hyphenated PyPI ones.

    Returns None when the package has no chumicro dependencies, so no
    file is written and circup's lookup simply finds nothing.
    """
    packages = _manifest_dependency_packages(package_dir)
    if not packages:
        return None
    return "".join(f"{package}\n" for package in packages)


def build_circup_zips(
    bundle_dir: Path,
    output_dir: Path,
    repo_name: str,
    *,
    date_tag: str | None = None,
) -> list[Path]:
    """Build circup-format zip bundles from a bundle directory.

    The source zip contains .py files from root ``chumicro_*`` directories.
    The bytecode zip contains .mpy files from ``circuitpython-10.x-mpy/``
    directories, compiled with CircuitPython's mpy-cross (magic byte 'C').

    Args:
        bundle_dir: Directory containing ``chumicro_*`` package directories.
        output_dir: Output directory for zip files.
        repo_name: Bundle repository name used to derive bundle_id.
        date_tag: Date tag for zip filenames (default: today UTC).

    Returns:
        List of created zip file paths.
    """
    if date_tag is None:
        date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")  # noqa: UP017

    bundle_id = _derive_bundle_id(repo_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    package_dirs = sorted(
        entry
        for entry in bundle_dir.iterdir()
        if entry.is_dir() and entry.name.startswith("chumicro_")
    )
    if not package_dirs:
        print(f"No chumicro_* packages found in {bundle_dir}")
        return []

    # CircuitPython .mpy bytecode lives under circuitpython-10.x-mpy/
    # (compiled with CircuitPython's mpy-cross, magic byte 'C').
    # The folder name follows Adafruit's naming convention.
    cp_mpy_base = bundle_dir / CP_MPY_FOLDER
    cp_mpy_package_dirs = sorted(
        entry
        for entry in (cp_mpy_base.iterdir() if cp_mpy_base.is_dir() else [])
        if entry.is_dir() and entry.name.startswith("chumicro_")
    )

    source_bundle_name = f"{bundle_id}-py-{date_tag}"
    # "10.x" refers to CircuitPython 10.x's mpy bytecode format (v6).
    # circup parses this pattern to match bundles to the running firmware
    # version on the board.  The naming convention is a circup contract.
    bytecode_bundle_name = f"{bundle_id}-10.x-mpy-{date_tag}"

    source_zip_path = output_dir / f"{source_bundle_name}.zip"
    bytecode_zip_path = output_dir / f"{bytecode_bundle_name}.zip"

    with (
        zipfile.ZipFile(source_zip_path, "w", zipfile.ZIP_DEFLATED) as source_zip,
        zipfile.ZipFile(bytecode_zip_path, "w", zipfile.ZIP_DEFLATED) as bytecode_zip,
    ):
        # .py source bundle: the .py + declared data files this build's
        # package.json manifest lists, so a stale module the overlay left
        # on disk can't ride in.
        for package_dir in package_dirs:
            package_name = package_dir.name
            current = _manifest_current_relpaths(package_dir)
            if current is None:
                raise ValueError(
                    f"{package_dir} has no package.json manifest; every "
                    f"staged bundle package carries one."
                )
            source_files = [
                (package_dir / relative_path, relative_path)
                for relative_path in sorted(current)
                if (package_dir / relative_path).is_file()
            ]
            for source_file, relative_path in source_files:
                archive_path = f"{source_bundle_name}/lib/{package_name}/{relative_path}"
                source_zip.write(source_file, archive_path)

            # circup reads dependencies from requirements/<library>/ beside
            # lib/, the layout Adafruit's bundles use.  Without it circup
            # installs the named library alone and the board raises
            # ImportError on its first import: mip carries deps in
            # package.json and was the only install path with any coverage,
            # so the whole CircuitPython side shipped dependency-less.
            requirements = _circup_requirements_text(package_dir)
            if requirements is not None:
                source_zip.writestr(
                    f"{source_bundle_name}/requirements/{package_name}"
                    "/requirements.txt",
                    requirements,
                )

        # .mpy bytecode bundle: CircuitPython .mpy from circuitpython-10.x-mpy/,
        # plus any raw data files staged alongside them (non-.mpy siblings).
        # The CP mpy folder carries no manifest of its own, so derive the
        # current set from the source package's manifest (each current .py
        # maps to its .mpy; data files ship raw) and skip any stale .mpy
        # whose source .py this build no longer declares.
        for mpy_dir in cp_mpy_package_dirs:
            package_name = mpy_dir.name
            current = _manifest_current_relpaths(bundle_dir / package_name)
            allowed: set[Path] | None = None
            if current is not None:
                allowed = {
                    relative_path.with_suffix(".mpy")
                    if relative_path.suffix == ".py"
                    else relative_path
                    for relative_path in current
                }
            for staged_file in sorted(mpy_dir.rglob("*")):
                if not staged_file.is_file():
                    continue
                relative_path = staged_file.relative_to(mpy_dir)
                if allowed is not None and relative_path not in allowed:
                    continue
                archive_path = f"{bytecode_bundle_name}/lib/{package_name}/{relative_path}"
                bytecode_zip.write(staged_file, archive_path)

            # Adafruit ships requirements/ in the mpy bundles too, and a
            # user who registered only this one should still resolve deps.
            requirements = _circup_requirements_text(bundle_dir / package_name)
            if requirements is not None:
                bytecode_zip.writestr(
                    f"{bytecode_bundle_name}/requirements/{package_name}"
                    "/requirements.txt",
                    requirements,
                )

    created = [source_zip_path, bytecode_zip_path]
    for zip_path in created:
        print(f"Created {zip_path}")
    return created


def _collect_library_metadata(root_dir: Path) -> list[dict]:
    """Collect metadata for all publishable libraries.

    Parked libraries (Decision 0107) are skipped: this metadata drives
    the bundle README, and a parked library never enters the bundle, so
    it must not be advertised there.

    Args:
        root_dir: Workspace root directory.

    Returns:
        Sorted list of dicts with ``name``, ``package_name``, ``version``,
        ``description``.
    """
    libraries_dir = root_dir / "libraries"
    if not libraries_dir.is_dir():
        return []
    entries = []
    for version_file in sorted(libraries_dir.rglob("VERSION")):
        library_dir = version_file.parent
        if not (library_dir / "pyproject.toml").exists():
            continue
        if is_parked(library_dir):
            continue
        version = version_file.read_text().strip()
        name = library_dir.name  # e.g. "timing"

        description = read_pyproject_description(library_dir)

        # Derive the import-name from the src/ directory.
        package_dir = find_package_dir(library_dir)
        package_name = package_dir.name if package_dir else f"chumicro_{name}"

        entries.append(
            {
                "name": name,
                "package_name": package_name,
                "version": version,
                "description": description,
            }
        )
    return entries


def _collect_bundle_metadata(root_dir: Path, bundle_dir: Path) -> list[dict]:
    """Collect metadata only for libraries present in *bundle_dir*.

    Args:
        root_dir: Workspace root directory.
        bundle_dir: Bundle directory to scan for packages.
    """
    package_dirs = sorted(
        entry for entry in bundle_dir.iterdir()
        if entry.is_dir()
        and entry.name.startswith("chumicro_")
        and (entry / "package.json").exists()
    )
    if not package_dirs:
        return []

    # Build a description lookup from the source workspace.
    all_metadata = {meta["package_name"]: meta for meta in _collect_library_metadata(root_dir)}

    entries = []
    for package_dir in package_dirs:
        package_name = package_dir.name  # e.g. "chumicro_timing"
        with open(package_dir / "package.json") as manifest_file:
            manifest = json.load(manifest_file)
        version = manifest.get("version", "unknown")

        # Derive the short name (e.g. "timing" from "chumicro_timing").
        name = package_name.removeprefix("chumicro_")

        source = all_metadata.get(package_name, {})
        description = source.get("description", "")

        entries.append(
            {
                "name": name,
                "package_name": package_name,
                "version": version,
                "description": description,
            }
        )
    return entries


#: GitHub source repository name used for README links.
_SOURCE_REPO = "ChuMicro"


def generate_bundle_readme(
    root_dir: Path,
    *,
    experimental: bool = False,
    bundle_dir: Path | None = None,
) -> str:
    """Generate a rich README.md for a bundle repo.

    Args:
        root_dir: Workspace root directory.
        experimental: Generate for the experimental bundle repo.
        bundle_dir: When provided, only include libraries whose packages
            exist in this directory.

    Returns:
        README markdown content.
    """
    if bundle_dir is not None:
        libraries = _collect_bundle_metadata(root_dir, bundle_dir)
    else:
        libraries = _collect_library_metadata(root_dir)

    bundle_repo = EXPERIMENTAL_BUNDLE_REPO if experimental else STABLE_BUNDLE_REPO
    alt_repo = STABLE_BUNDLE_REPO if experimental else EXPERIMENTAL_BUNDLE_REPO
    channel = "Experimental" if experimental else "Stable"
    alt_channel = "Stable" if experimental else "Experimental"
    source_url = f"https://github.com/{GITHUB_ORG}/{_SOURCE_REPO}"
    alt_repo_url = f"https://github.com/{GITHUB_ORG}/{alt_repo}"
    docs_url = "https://chumicro.github.io/ChuMicro/"
    pip_suffix = "-experimental" if experimental else ""

    banner = (
        "> ⚠️ **Pre-release channel** — these builds come from "
        "`main` and may contain breaking changes."
        if experimental
        else ""
    )

    banner_block = f"\n{banner}\n" if banner else ""

    # Library table rows.
    library_rows = "\n".join(
        f"| [**chumicro-{library['name']}**]({source_url}/tree/main/libraries/{library['name']})"
        f" | {library['version']} | {library['description']} |"
        for library in libraries
    )

    logo_url = f"https://raw.githubusercontent.com/{GITHUB_ORG}/{_SOURCE_REPO}/main/support/docs/chumicro.png"

    template_text = (TEMPLATES_DIR / "bundle_readme.md.template").read_text()
    return template_text.format(
        source_url=source_url,
        logo_url=logo_url,
        bundle_repo=bundle_repo,
        channel=channel,
        docs_url=docs_url,
        alt_repo_url=alt_repo_url,
        alt_channel=alt_channel,
        banner_block=banner_block,
        github_org=GITHUB_ORG,
        alt_repo=alt_repo,
        alt_channel_lower=alt_channel.lower(),
        mpy_format_folder=MPY_FORMAT_FOLDER,
        cp_mpy_folder=CP_MPY_FOLDER,
        pip_suffix=pip_suffix,
        library_rows=library_rows,
        source_repo=_SOURCE_REPO,
    )


def _experimental_dependency(dependency: str) -> str:
    """Append ``-experimental`` to a chumicro dependency's name.

    The version specifier / extras / marker are preserved verbatim so an
    experimental wheel pins the experimental project:
    ``"chumicro-deploy>=0.1.0"`` -> ``"chumicro-deploy-experimental>=0.1.0"``.
    An entry whose name already ends with ``-experimental`` is returned
    unchanged.

    Args:
        dependency: A ``project.dependencies`` entry (e.g.
            ``"chumicro-deploy>=0.1.0"``).
    """
    name = strip_pip_dependency_version(dependency)
    # Re-suffixing would pin a nonexistent *-experimental-experimental
    # project.
    if name.endswith("-experimental"):
        return dependency
    split_at = dependency.index(name) + len(name)
    return f"{dependency[:split_at]}-experimental{dependency[split_at:]}"


def _project_dependencies_span(content: str) -> tuple[int, int] | None:
    """Return the ``[start, end)`` char slice of the ``[project].dependencies``
    array, or ``None`` when the array is absent.

    The array opens at a ``dependencies = [`` line.  A single-line array
    (``dependencies = ["chumicro-msgpack>=0.2.0"]``) closes on that same
    line; otherwise each entry sits on its own line (the workspace
    convention) and the array closes at the first following line that is
    a bare ``]``.  Scoping to this block keeps the dependency rewrite from
    touching an identically-named entry in
    ``[project.optional-dependencies]``.

    Args:
        content: Raw pyproject.toml text.
    """
    offset = 0
    open_index: int | None = None
    for line in content.splitlines(keepends=True):
        if open_index is None:
            if line.replace(" ", "").replace("\t", "").startswith("dependencies=["):
                open_index = offset
                # A single-line array — scanning on would extend the span
                # into [project.optional-dependencies] (or off the end of
                # the file, returning None).
                if line.rstrip().endswith("]"):
                    return open_index, offset + len(line)
        elif line.strip() == "]":
            return open_index, offset + len(line)
        offset += len(line)
    return None


def _rewrite_experimental_dependencies(
    content: str, dependencies: list[str], pyproject_path: Path,
) -> str:
    """Rewrite intra-chumicro ``[project].dependencies`` for experimental.

    Every ``chumicro-*`` entry gets ``-experimental`` appended to its
    name (Decision-point 1a): an experimental wheel must require the
    experimental projects, since the stable projects don't exist on the
    pre-release channel and pip would otherwise fail to resolve them.
    Non-chumicro deps are left untouched.

    Args:
        content: Raw pyproject.toml text.
        dependencies: The parsed ``[project].dependencies`` list.
        pyproject_path: Source path, for the error message when the array
            can't be located.
    """
    chumicro_dependencies = [
        dependency
        for dependency in dependencies
        if strip_pip_dependency_version(dependency).startswith("chumicro-")
    ]
    if not chumicro_dependencies:
        return content

    span = _project_dependencies_span(content)
    if span is None:
        # tomllib parsed chumicro deps but the raw array can't be located
        # for a scoped rewrite — fail rather than silently ship stable
        # deps on the experimental wheel (the B2 uninstallable-bootstrap
        # trap this rewrite exists to close).
        sys.exit(f"Cannot locate [project].dependencies array in {pyproject_path}")

    open_index, close_index = span
    block = content[open_index:close_index]
    for dependency in chumicro_dependencies:
        experimental = _experimental_dependency(dependency)
        for quote in ('"', "'"):
            block = block.replace(
                f"{quote}{dependency}{quote}",
                f"{quote}{experimental}{quote}",
            )
    return content[:open_index] + block + content[close_index:]


def _optional_dependencies_span(content: str) -> tuple[int, int] | None:
    """Return the ``[start, end)`` char slice of the
    ``[project.optional-dependencies]`` table, or ``None`` when absent.

    The table opens at its header line and runs until the next table header
    (a line whose first non-space character is ``[``) or end of file.
    Scoping the rewrite to this block keeps it off the main
    ``[project].dependencies`` array and every ``[tool.*]`` table.

    Args:
        content: Raw pyproject.toml text.
    """
    offset = 0
    open_index: int | None = None
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        if open_index is None:
            if stripped == "[project.optional-dependencies]":
                open_index = offset
        elif stripped.startswith("["):
            return open_index, offset
        offset += len(line)
    if open_index is not None:
        return open_index, len(content)
    return None


def _rewrite_experimental_optional_dependencies(
    content: str,
    optional_dependencies: dict[str, list[str]],
    pyproject_path: Path,
) -> str:
    """Rewrite intra-chumicro ``[project.optional-dependencies]`` entries.

    A library's ``test`` extra pins ``chumicro-test-harness`` /
    ``chumicro-pytest-device`` / ``chumicro-workspace``; on the pre-release
    channel the stable projects don't exist, so an unrewritten extra makes
    ``pip install chumicro-<lib>-experimental[test]`` fail to resolve.  Every
    ``chumicro-*`` entry across every extra gets ``-experimental`` appended,
    mirroring :func:`_rewrite_experimental_dependencies` (non-chumicro deps
    such as ``pytest`` untouched).

    Args:
        content: Raw pyproject.toml text.
        optional_dependencies: The parsed ``[project.optional-dependencies]``
            table (extra name -> dependency list).
        pyproject_path: Source path, for the error message when the table
            can't be located.
    """
    chumicro_dependencies = [
        dependency
        for extra_dependencies in optional_dependencies.values()
        for dependency in extra_dependencies
        if strip_pip_dependency_version(dependency).startswith("chumicro-")
    ]
    if not chumicro_dependencies:
        return content

    span = _optional_dependencies_span(content)
    if span is None:
        # tomllib parsed chumicro extras but the raw table can't be located
        # for a scoped rewrite — fail rather than ship an uninstallable
        # experimental [test] extra.
        sys.exit(
            f"Cannot locate [project.optional-dependencies] in {pyproject_path}"
        )

    open_index, close_index = span
    block = content[open_index:close_index]
    for dependency in chumicro_dependencies:
        experimental = _experimental_dependency(dependency)
        for quote in ('"', "'"):
            block = block.replace(
                f"{quote}{dependency}{quote}",
                f"{quote}{experimental}{quote}",
            )
    return content[:open_index] + block + content[close_index:]


def _patch_experimental_readme(readme_path: Path, name: str) -> None:
    """Patch a library's README.md for experimental channel release.

    The README ships verbatim as the PyPI long-description, so an
    experimental project page must not show stable install COMMANDS.
    Rewrites are scoped to install-command lines only (``pip install``,
    ``mip install``, ``circup bundle-add``) — prose and footer links
    that legitimately reference both channels (e.g. a labeled "Stable
    docs" link) keep their targets, otherwise the labels would lie:

    - ``pip install`` lines referencing the stable *name* gain the
      ``-experimental`` suffix.
    - ``ChuMicro-Bundle`` references on install-command lines point at
      the experimental bundle repo.  A reference already reading
      ``ChuMicro-Bundle-Experimental`` is left alone (no double suffix).
    - ``/stable/`` on install-command lines switches to
      ``/experimental/``.

    Args:
        readme_path: Path to the library's README.md.
        name: The stable ``[project].name`` (e.g. ``chumicro-timing``).
    """
    original = readme_path.read_text()

    # Suffix the package name only on pip install lines, and only when
    # the match is the whole name — a name followed by another name
    # character is a longer (possibly already-suffixed) package.
    name_pattern = re.compile(rf"{re.escape(name)}(?![A-Za-z0-9._-])")
    bundle_pattern = re.compile(rf"{re.escape(STABLE_BUNDLE_REPO)}(?!-Experimental)")
    lines = original.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if "pip install" in line:
            line = name_pattern.sub(f"{name}-experimental", line)
        if "install" in line or "bundle-add" in line:
            line = bundle_pattern.sub(EXPERIMENTAL_BUNDLE_REPO, line)
            line = line.replace("/stable/", "/experimental/")
        lines[index] = line
    content = "".join(lines)

    if content == original:
        return
    readme_path.write_text(content)

    # Print patched lines for verification.
    print("Patched README.md:")
    # Line counts always match — every rewrite substitutes within a line.
    patched_pairs = zip(original.splitlines(), content.splitlines(), strict=True)
    for original_line, patched_line in patched_pairs:
        if original_line != patched_line:
            print(f"  {patched_line}")


def patch_experimental(library_dir: Path) -> None:
    """Patch a library's pyproject.toml and README.md for experimental release.

    Renames the PyPI package to ``*-experimental`` (read from
    ``[project].name`` rather than derived from the directory, so a
    hyphenated name like ``chumicro-http-server`` in ``libraries/http_server/``
    patches correctly), rewrites intra-chumicro ``[project].dependencies``
    to their ``-experimental`` counterparts, redirects the Bundle URL to
    the experimental bundle repo, and switches the Documentation URL from
    ``/stable/`` to ``/experimental/``.  The README.md (the PyPI
    long-description), when present, gets the matching install-command and
    link rewrites via :func:`_patch_experimental_readme`.

    Args:
        library_dir: Root directory of the library (e.g. ``libraries/timing``).
    """
    pyproject_path = library_dir / "pyproject.toml"
    content = pyproject_path.read_text()

    tomllib = load_tomllib()
    with pyproject_path.open("rb") as pyproject_file:
        data = tomllib.load(pyproject_file)
    project = data.get("project", {})
    name = project.get("name")
    if not isinstance(name, str) or not name.strip():
        sys.exit(f"Cannot find a [project].name in {pyproject_path}")

    # Idempotency guard: patching an already-patched tree would produce a
    # "*-experimental-experimental" name and double-suffixed deps — and
    # publish a brand-new, wrong PyPI project.
    if name.endswith("-experimental"):
        print(f"{pyproject_path} is already patched ({name}) — nothing to do.")
        return

    # 1. Rename the PyPI package to its experimental counterpart.
    original_name = f'name = "{name}"'
    experimental_name = f'name = "{name}-experimental"'
    if original_name not in content:
        sys.exit(f"Cannot find '{original_name}' in {pyproject_path}")
    content = content.replace(original_name, experimental_name)

    # 2. Rewrite intra-chumicro dependencies to the experimental channel
    #    so the wheel requires -experimental deps (which exist) instead of
    #    stable projects (which don't, on the pre-release channel).
    content = _rewrite_experimental_dependencies(
        content, project.get("dependencies", []), pyproject_path,
    )

    # 2b. Rewrite intra-chumicro optional-dependencies the same way, so
    #     `pip install chumicro-<lib>-experimental[test]` resolves against
    #     the experimental test tooling instead of the stable projects that
    #     don't exist on the pre-release channel.
    content = _rewrite_experimental_optional_dependencies(
        content, project.get("optional-dependencies", {}), pyproject_path,
    )

    # 3. Point Bundle URL to the experimental bundle repository.
    content = content.replace('ChuMicro-Bundle"', 'ChuMicro-Bundle-Experimental"')

    # 4. Point Documentation URL to the experimental docs channel.
    content = content.replace('/stable/"', '/experimental/"')

    pyproject_path.write_text(content)

    # Print patched lines for verification.
    print("Patched pyproject.toml:")
    for line in content.splitlines():
        stripped = line.strip()
        if line.startswith(("name =", "Bundle =", "Documentation =")):
            print(f"  {line}")
        elif stripped.startswith(('"chumicro-', "'chumicro-")) and "-experimental" in stripped:
            print(f"  {line}")

    # The README ships verbatim as the PyPI long-description, so its
    # install commands and links must follow the channel rename.
    readme_path = library_dir / "README.md"
    if readme_path.exists():
        _patch_experimental_readme(readme_path, name)


#: A bundle release tag: YYYYMMDD with optional numeric suffix segments.
_DATE_TAG_PATTERN = re.compile(r"^\d{8}(\.\d+)*$")

#: Stage-time placeholder for manifest dep refs.  The snapshot tag a
#: package ships under doesn't exist until push time, so build_bundle
#: stages deps pinned to this value and finalize_bundle_tag rewrites
#: them to the real tag.  A pushed manifest must never carry it: an
#: install would resolve deps at whatever the bundle repo's HEAD is at
#: install time, not at the snapshot the package was validated with.
_STAGE_TIME_DEP_PIN = "HEAD"


def _head_date_tag(bundle_dir: Path) -> str | None:
    """Return the highest date tag on HEAD, or None if HEAD has none.

    Args:
        bundle_dir: Path to the cloned bundle repository.
    """
    head_tags = run_git("tag", "--points-at", "HEAD", cwd=bundle_dir)
    date_tags = [
        tag
        for tag in head_tags.stdout.strip().splitlines()
        if _DATE_TAG_PATTERN.match(tag)
    ]
    if not date_tags:
        return None
    return max(date_tags, key=lambda tag: tuple(int(part) for part in tag.split(".")))


def pin_bundle_deps(
    bundle_dir: Path,
    tag: str,
    *,
    manifests: list[Path] | None = None,
) -> list[Path]:
    """Rewrite package.json dep pins under *bundle_dir* to *tag*.

    When *manifests* is None, scans every manifest in the tree and
    rewrites dep entries pinned to the stage-time placeholder.  Passing
    an explicit list instead rewrites all dep entries of exactly those
    manifests — used when a freshly minted tag supersedes the reuse
    candidate they were just pinned to — without touching manifests
    from earlier pushes, whose pins must keep naming their own snapshot.

    Args:
        bundle_dir: Path to the cloned bundle repository.
        tag: The tag to pin dep entries to.
        manifests: Explicit manifests to re-pin, or None to scan.

    Returns:
        The manifests that were rewritten.
    """
    if manifests is None:
        targets = [
            manifest_path
            for manifest_path in sorted(bundle_dir.rglob("package.json"))
            if ".git" not in manifest_path.relative_to(bundle_dir).parts
        ]
        only_value = _STAGE_TIME_DEP_PIN
    else:
        targets = manifests
        only_value = None

    rewritten: list[Path] = []
    for manifest_path in targets:
        manifest = json.loads(manifest_path.read_text())
        changed = False
        for entry in manifest.get("deps", []):
            if only_value is not None and entry[1] != only_value:
                continue
            if entry[1] != tag:
                entry[1] = tag
                changed = True
        if changed:
            with open(manifest_path, "w") as manifest_file:
                json.dump(manifest, manifest_file, indent=2)
                manifest_file.write("\n")
            rewritten.append(manifest_path)
    return rewritten


def finalize_bundle_tag(bundle_dir: Path, *, reuse_if_clean: bool = False) -> str:
    """Pin staged dep placeholders and return the release tag.

    Breaks the circularity between "what tag does this push get"
    (depends on whether the staged overlay changed anything) and "what
    do the staged manifests' dep pins say" (part of the content being
    compared):

    1. Pin placeholders to HEAD's own date tag.  On a no-change re-run
       the tree becomes byte-identical to HEAD, so the reuse branch of
       :func:`next_date_tag` fires and the already-pushed tag is
       reused.
    2. Otherwise the tree is genuinely dirty: mint the next tag and
       re-pin the same manifests to it.

    Every pushed manifest's dep pins therefore name the tag of the
    snapshot they shipped in — an install of ``package@tag`` resolves
    its deps at that same validated snapshot.

    Args:
        bundle_dir: Path to the cloned bundle repository, with staged
            artifacts already overlaid.
        reuse_if_clean: Passed through to :func:`next_date_tag`.

    Returns:
        The release tag the bundle push should use.
    """
    candidate = _head_date_tag(bundle_dir)
    pinned: list[Path] = []
    if candidate is not None:
        pinned = pin_bundle_deps(bundle_dir, candidate)
    tag = next_date_tag(bundle_dir, reuse_if_clean=reuse_if_clean)
    if tag != candidate:
        if candidate is None:
            pinned = pin_bundle_deps(bundle_dir, tag)
        elif pinned:
            pinned = pin_bundle_deps(bundle_dir, tag, manifests=pinned)
    if pinned:
        print(
            f"Pinned deps in {len(pinned)} manifest(s) to {tag}",
            file=sys.stderr,
        )
    return tag


def next_date_tag(bundle_dir: Path, *, reuse_if_clean: bool = False) -> str:
    """Compute the next available date-based tag for a bundle release.

    Tags use ``YYYYMMDD`` for the first release of a day, with
    ``.1``, ``.2``, etc. suffixes for subsequent releases.

    Args:
        bundle_dir: Path to the cloned bundle repository.
        reuse_if_clean: When True and the checkout's working tree is
            clean (``git status --porcelain`` empty) and the HEAD commit
            already carries at least one date tag, return the highest
            such tag instead of minting a new one — a release re-run
            that produced no content changes reuses its existing tag.

    Returns:
        The next available date tag string (or the reused HEAD tag).
    """
    if reuse_if_clean:
        status = run_git("status", "--porcelain", cwd=bundle_dir)
        if not status.stdout.strip():
            head_tag = _head_date_tag(bundle_dir)
            if head_tag is not None:
                return head_tag

    today = datetime.now(timezone.utc).strftime("%Y%m%d")  # noqa: UP017

    result = run_git(
        "tag", "-l", f"{today}*", "--sort=v:refname",
        cwd=bundle_dir,
    )
    tags = [tag for tag in result.stdout.strip().splitlines() if tag]

    if not tags:
        return today

    latest = tags[-1]
    if latest == today:
        return f"{today}.1"

    suffix_str = latest.removeprefix(f"{today}.")
    try:
        return f"{today}.{int(suffix_str) + 1}"
    except ValueError:
        return f"{today}.1"


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Stage bundle artifacts for mip/circup distribution.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Default (positional) staging command.
    stage_parser = subparsers.add_parser("stage", help="Stage bundle artifacts")
    stage_parser.add_argument(
        "library_dir", type=Path, help="Library directory (e.g. libraries/timing)"
    )
    stage_parser.add_argument("version", help="Library version string")
    stage_parser.add_argument("staging_dir", type=Path, help="Output staging directory")
    stage_parser.add_argument(
        "--cp-mpy-cross", default=None,
        help="Path to CircuitPython's mpy-cross binary "
        "(default: auto-discover from target-runtimes.toml and .tools/)",
    )
    stage_parser.add_argument(
        "--mp-mpy-cross", default=None,
        help="Path to MicroPython's mpy-cross binary "
        "(default: auto-discover from target-runtimes.toml, .tools/, or PATH)",
    )
    stage_parser.add_argument(
        "--experimental",
        action="store_true",
        help="Stage as experimental channel "
        "(package.json URLs point to the experimental bundle repo)",
    )

    # Batch staging from a JSON matrix.
    stage_matrix_parser = subparsers.add_parser(
        "stage-matrix",
        help="Stage artifacts for libraries described in a JSON matrix",
    )
    stage_matrix_parser.add_argument(
        "staging_dir", type=Path, help="Output staging directory"
    )
    stage_matrix_parser.add_argument(
        "--matrix", required=True,
        help="JSON matrix string as emitted by release_matrix.py, with "
        "library_dir/version/library_name keys per entry (e.g. "
        '\'{"include": [{"library_dir": "libraries/timing", "version": "1.2.3", ...}]}\')',
    )
    stage_matrix_parser.add_argument(
        "--cp-mpy-cross", default=None,
        help="Path to CircuitPython's mpy-cross binary "
        "(default: auto-discover from target-runtimes.toml and .tools/)",
    )
    stage_matrix_parser.add_argument(
        "--mp-mpy-cross", default=None,
        help="Path to MicroPython's mpy-cross binary "
        "(default: auto-discover from target-runtimes.toml, .tools/, or PATH)",
    )
    stage_matrix_parser.add_argument(
        "--experimental",
        action="store_true",
        help="Stage as experimental channel",
    )

    # README generation command.
    readme_parser = subparsers.add_parser(
        "readme", help="Generate bundle repository README.md to stdout"
    )
    readme_parser.add_argument(
        "--experimental",
        action="store_true",
        help="Generate for the experimental bundle repo",
    )
    readme_parser.add_argument(
        "-o", "--output", type=Path, help="Write to file instead of stdout"
    )
    readme_parser.add_argument(
        "--bundle-dir", type=Path, default=None,
        help="Only include libraries present in this directory "
        "(reads versions from package.json)",
    )

    # circup zip generation command.
    zip_parser = subparsers.add_parser(
        "circup-zip", help="Build circup-format zip bundles from a bundle directory"
    )
    zip_parser.add_argument(
        "bundle_dir",
        type=Path,
        help="Directory containing chumicro_* package directories",
    )
    zip_parser.add_argument(
        "output_dir", type=Path, help="Output directory for zip files"
    )
    zip_parser.add_argument(
        "--repo-name",
        required=True,
        help="Bundle repository name (e.g. ChuMicro-Bundle) — used to derive bundle_id",
    )
    zip_parser.add_argument(
        "--date-tag",
        default=None,
        help="Date tag for zip filenames (default: today UTC as YYYYMMDD)",
    )

    # Patch pyproject.toml for experimental release.
    patch_parser = subparsers.add_parser(
        "patch-experimental",
        help="Patch pyproject.toml and README.md for experimental channel release",
    )
    patch_parser.add_argument(
        "library_dir", type=Path,
        help="Library directory (e.g. libraries/timing)",
    )

    # Compute the next available date-based tag.
    date_tag_parser = subparsers.add_parser(
        "next-date-tag",
        help="Print the next available date-based tag for a bundle repo",
    )
    date_tag_parser.add_argument(
        "bundle_dir", type=Path,
        help="Path to the cloned bundle repository",
    )
    date_tag_parser.add_argument(
        "--reuse-if-clean",
        action="store_true",
        help="When the checkout is clean and HEAD already carries a date tag, "
        "print the highest such tag instead of minting a new one",
    )

    # Pin staged dep placeholders and print the release tag.
    finalize_parser = subparsers.add_parser(
        "finalize-tag",
        help="Pin staged package.json dep refs to the release tag and print it",
    )
    finalize_parser.add_argument(
        "bundle_dir", type=Path,
        help="Path to the cloned bundle repository with staging overlaid",
    )
    finalize_parser.add_argument(
        "--reuse-if-clean",
        action="store_true",
        help="When pinning to HEAD's tag leaves the checkout clean, "
        "print that tag instead of minting a new one",
    )

    args = parser.parse_args()

    if args.command == "readme":
        content = generate_bundle_readme(
            ROOT, experimental=args.experimental, bundle_dir=args.bundle_dir,
        )
        if args.output:
            args.output.write_text(content)
            print(f"Wrote {args.output}")
        else:
            print(content)
    elif args.command == "stage":
        cp_cross = resolve_cp_mpy_cross(args.cp_mpy_cross)
        mp_cross = resolve_mp_mpy_cross(args.mp_mpy_cross)
        build_bundle(
            args.library_dir,
            args.version,
            args.staging_dir,
            cp_mpy_cross=cp_cross,
            mp_mpy_cross=mp_cross,
            experimental=args.experimental,
        )
    elif args.command == "stage-matrix":
        cp_cross = resolve_cp_mpy_cross(args.cp_mpy_cross)
        mp_cross = resolve_mp_mpy_cross(args.mp_mpy_cross)
        stage_matrix(
            args.staging_dir,
            args.matrix,
            cp_mpy_cross=cp_cross,
            mp_mpy_cross=mp_cross,
            experimental=args.experimental,
        )
    elif args.command == "circup-zip":
        build_circup_zips(
            args.bundle_dir,
            args.output_dir,
            args.repo_name,
            date_tag=args.date_tag,
        )
    elif args.command == "patch-experimental":
        patch_experimental(args.library_dir)
    elif args.command == "next-date-tag":
        print(next_date_tag(args.bundle_dir, reuse_if_clean=args.reuse_if_clean))
    elif args.command == "finalize-tag":
        print(finalize_bundle_tag(args.bundle_dir, reuse_if_clean=args.reuse_if_clean))
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
