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
    patch-experimental Patch pyproject.toml for experimental channel release.
    next-date-tag      Print the next available date-based tag for a bundle repo.

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
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

# Bundle repository names and mpy folder layout live in
# ``scripts/bundle_layout`` so the producer (this module) and the
# consumer (``validate_mip_install``) cannot drift.  Re-export the
# names here for backward compatibility with existing call sites.
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


def _dependency_to_mpy_mip_reference(dependency: str, bundle_repo: str) -> str:
    """Convert 'chumicro-timing>=0.1' to an mpy6 mip github reference.

    Args:
        dependency: PyPI dependency string (e.g. ``"chumicro-timing>=0.1"``).
        bundle_repo: Bundle repository name (e.g. ``"ChuMicro-Bundle"``).
    """
    package = strip_pip_dependency_version(dependency).replace("-", "_")
    return f"github:{GITHUB_ORG}/{bundle_repo}/{MPY_FORMAT_FOLDER}/{package}"


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
    mip_dependencies = [
        [_dependency_to_mip_reference(dependency, bundle_repo), "HEAD"]
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
        mpy_manifest_dir = staging_dir / MPY_FORMAT_FOLDER / package_name
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
                f"/{MPY_FORMAT_FOLDER}/{package_name}/{mpy_relative_path}"
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
                f"/{MPY_FORMAT_FOLDER}/{package_name}/{data_relative_path}"
            )
            mpy_urls.append([target, source])

        mpy_manifest: dict = {"urls": mpy_urls, "version": version}
        mpy_mip_dependencies = [
            [_dependency_to_mpy_mip_reference(dependency, bundle_repo), "HEAD"]
            for dependency in _read_chumicro_dependencies(library_dir)
        ]
        if mpy_mip_dependencies:
            mpy_manifest["deps"] = mpy_mip_dependencies

        with open(mpy_manifest_dir / "package.json", "w") as mpy_manifest_file:
            json.dump(mpy_manifest, mpy_manifest_file, indent=2)
            mpy_manifest_file.write("\n")

        print(f"Staged {MPY_FORMAT_FOLDER}/{package_name} (MicroPython) -> {mpy_manifest_dir}")


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
        # .py source bundle: all .py files from root package directories,
        # plus the sibling data files those modules declare via
        # __chumicro_data_files__ (read from the staged .py markers).
        for package_dir in package_dirs:
            package_name = package_dir.name
            python_files = sorted(package_dir.rglob("*.py"))
            for source_file in python_files:
                relative_path = source_file.relative_to(package_dir)
                archive_path = f"{source_bundle_name}/lib/{package_name}/{relative_path}"
                source_zip.write(source_file, archive_path)
            for data_source in _bundle_data_files(python_files):
                relative_path = data_source.relative_to(package_dir)
                archive_path = f"{source_bundle_name}/lib/{package_name}/{relative_path}"
                source_zip.write(data_source, archive_path)

        # .mpy bytecode bundle: CircuitPython .mpy from circuitpython-10.x-mpy/,
        # plus any raw data files staged alongside them (non-.mpy siblings).
        for mpy_dir in cp_mpy_package_dirs:
            package_name = mpy_dir.name
            for staged_file in sorted(mpy_dir.rglob("*")):
                if not staged_file.is_file():
                    continue
                relative_path = staged_file.relative_to(mpy_dir)
                archive_path = f"{bytecode_bundle_name}/lib/{package_name}/{relative_path}"
                bytecode_zip.write(staged_file, archive_path)

    created = [source_zip_path, bytecode_zip_path]
    for zip_path in created:
        print(f"Created {zip_path}")
    return created


def _collect_library_metadata(root_dir: Path) -> list[dict]:
    """Collect metadata for all publishable libraries.

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


def patch_experimental(library_dir: Path) -> None:
    """Patch a library's pyproject.toml for experimental channel release.

    Renames the PyPI package to ``*-experimental``, redirects the Bundle
    URL to the experimental bundle repo, and switches the Documentation
    URL from ``/stable/`` to ``/experimental/``.

    Args:
        library_dir: Root directory of the library (e.g. ``libraries/timing``).
    """
    pyproject_path = library_dir / "pyproject.toml"
    content = pyproject_path.read_text()
    library_name = library_dir.name

    # 1. Rename the PyPI package.
    original_name = f'name = "chumicro-{library_name}"'
    experimental_name = f'name = "chumicro-{library_name}-experimental"'
    if original_name not in content:
        sys.exit(f"Cannot find '{original_name}' in {pyproject_path}")
    content = content.replace(original_name, experimental_name)

    # 2. Point Bundle URL to the experimental bundle repository.
    content = content.replace('ChuMicro-Bundle"', 'ChuMicro-Bundle-Experimental"')

    # 3. Point Documentation URL to the experimental docs channel.
    content = content.replace('/stable/"', '/experimental/"')

    pyproject_path.write_text(content)

    # Print patched lines for verification.
    print("Patched pyproject.toml:")
    for line in content.splitlines():
        if line.startswith(("name =", "Bundle =", "Documentation =")):
            print(f"  {line}")


def next_date_tag(bundle_dir: Path) -> str:
    """Compute the next available date-based tag for a bundle release.

    Tags use ``YYYYMMDD`` for the first release of a day, with
    ``.1``, ``.2``, etc. suffixes for subsequent releases.

    Args:
        bundle_dir: Path to the cloned bundle repository.

    Returns:
        The next available date tag string.
    """
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
        help='JSON matrix string (e.g. \'{"include": [{"lib_dir": "...", "version": "..."}]}\')',
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
        help="Patch pyproject.toml for experimental channel release",
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
        print(next_date_tag(args.bundle_dir))
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
