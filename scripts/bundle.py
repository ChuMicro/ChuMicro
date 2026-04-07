"""Stage bundle artifacts for a library's mip/circup distribution.

Copies deployable .py source files, compiles .mpy bytecode with mpy-cross,
and generates a mip-compatible package.json manifest.

The two-repo bundle strategy (stable vs. experimental) is defined in
``plans/decisions/0018-distribution-bundle-repo.md``.

Subcommands:
    stage        Stage a single library's bundle artifacts.
    stage-matrix Stage artifacts for libraries in a JSON matrix (--matrix).
    readme       Generate a bundle repo README.md.

Examples:
    python scripts/bundle.py stage libraries/timing 0.1.0 .bundle-staging
    python scripts/bundle.py stage-matrix .bundle-staging --matrix '{"include": [...]}'
    python scripts/bundle.py readme --experimental -o README.md
    python scripts/bundle.py circup-zip .bundle-repo .circup-zips --repo-name ChuMicro-Bundle
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[import-not-found,no-redef]

from discovery import ROOT, find_package_dir

#: Bundle repository names for each channel.  Experimental uses a separate repository
#: so that circup's latest_tag works per-channel without prerelease tag tricks.
STABLE_BUNDLE_REPO = "ChuMicro-Bundle"
EXPERIMENTAL_BUNDLE_REPO = "ChuMicro-Bundle-Experimental"


def _find_bundle_modules(library_dir: Path) -> tuple[str, Path, list[Path]]:
    """Discover the package name, package dir, and deployable .py files.

    Returns ``(package_name, package_dir, python_files)`` where *python_files* are all
    ``.py`` modules to include in the bundle (both as source and compiled
    ``.mpy``).
    """
    package_dir = find_package_dir(library_dir)
    if package_dir is None:
        sys.exit(f"No importable package under {library_dir / 'src'}")

    # Exclude __pycache__ artifacts and testing.py — the testing module
    # contains test fakes only used by host-based pytest suites and should
    # not be deployed to microcontroller boards (saves flash space).
    python_files = [
        py_file
        for py_file in sorted(package_dir.rglob("*.py"))
        if "__pycache__" not in py_file.relative_to(package_dir).parts
        and py_file.name != "testing.py"
    ]
    return package_dir.name, package_dir, python_files


def _read_chumicro_dependencies(library_dir: Path) -> list[str]:
    """Return chumicro-* dependency names from pyproject.toml.

    Only intra-workspace dependencies are relevant for mip manifests —
    external PyPI packages are not installable via mip and are expected
    to be bundled or re-implemented within the library.
    """
    with open(library_dir / "pyproject.toml", "rb") as pyproject_file:
        data = tomllib.load(pyproject_file)
    dependencies = data.get("project", {}).get("dependencies", [])
    return [dep for dep in dependencies if dep.strip().startswith("chumicro-")]


def _dependency_to_mip_reference(dependency: str) -> str:
    """Convert 'chumicro-timing>=0.1' to a mip github reference.

    Dependencies always reference the stable (production) variant.
    An experimental library depends on production releases by default.
    If coordinated experimental changes across libraries are needed,
    the developer overrides specific dependencies manually.
    """
    # Strip version specifiers (e.g. "chumicro-timing>=0.1" → "chumicro-timing").
    # Splits on the first comparison operator, extras bracket, or environment marker.
    name = re.split(r"[><=!;~\[]", dependency, maxsplit=1)[0]
    package = name.strip().replace("-", "_")
    return f"github:{_GITHUB_ORG}/{STABLE_BUNDLE_REPO}/{package}"


def _compile_mpy(python_file: Path, mpy_file: Path, mpy_cross: str) -> None:
    """Compile a single .py file to .mpy."""
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
    mpy_cross: str = "mpy-cross",
    *,
    experimental: bool = False,
) -> None:
    """Stage bundle artifacts for a single library.

    Creates ``<staging_dir>/<package_name>/`` containing .py source, .mpy
    bytecode, and a package.json manifest for mip.

    When *experimental* is True the package.json URLs point to the
    experimental bundle repo.  Directory names are always the base
    package name (e.g. ``chumicro_timing``) — channel separation is
    by repo, not directory suffix.  This lets users swap between stable
    and experimental without changing import statements.
    """
    package_name, package_dir, python_files = _find_bundle_modules(library_dir)
    if not python_files:
        sys.exit(f"No deployable .py files found in {package_dir}")

    bundle_repo = EXPERIMENTAL_BUNDLE_REPO if experimental else STABLE_BUNDLE_REPO
    output_dir = staging_dir / package_name
    output_dir.mkdir(parents=True, exist_ok=True)

    # All modules get both .py source and .mpy bytecode.
    for source_file in python_files:
        relative_path = source_file.relative_to(package_dir)
        python_dest_file = output_dir / relative_path
        mpy_dest_file = (output_dir / relative_path).with_suffix(".mpy")
        python_dest_file.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, python_dest_file)
        _compile_mpy(source_file, mpy_dest_file, mpy_cross)

    # Generate mip package.json manifest.
    #
    # mip (MicroPython's package installer) reads package.json to know
    # which files to download and where to place them on-device.  Each
    # entry in "urls" is [target_path, source_url]:
    #   - target_path: on-device path relative to /lib/ (e.g. chumicro_timing/__init__.mpy)
    #   - source_url:  github: URI pointing to the .mpy file in this bundle repo
    #
    # Both target and source paths use package_name — the on-device import name
    # is always the base package name (e.g. chumicro_timing) regardless of
    # channel.  This lets users swap between stable and experimental by
    # changing which bundle repo they use, without changing imports.
    urls = []
    for source_file in python_files:
        relative_path = source_file.relative_to(package_dir)
        mpy_relative_path = relative_path.with_suffix(".mpy").as_posix()
        target = f"{package_name}/{mpy_relative_path}"
        source = f"github:ChuMicro/{bundle_repo}/{package_name}/{mpy_relative_path}"
        urls.append([target, source])

    manifest: dict = {"urls": urls, "version": version}
    # Dependencies always reference stable variants so that installing
    # one experimental library does not cascade into pulling experimental
    # versions of all transitive dependencies.
    mip_dependencies = [
        [_dependency_to_mip_reference(dep), "latest"]
        for dep in _read_chumicro_dependencies(library_dir)
    ]
    if mip_dependencies:
        manifest["deps"] = mip_dependencies

    with open(output_dir / "package.json", "w") as manifest_file:
        json.dump(manifest, manifest_file, indent=2)
        manifest_file.write("\n")

    print(f"Staged {package_name} v{version} -> {output_dir}")


def stage_matrix(
    staging_dir: Path,
    matrix_json: str,
    mpy_cross: str = "mpy-cross",
    *,
    experimental: bool = False,
) -> None:
    """Stage bundle artifacts for all libraries in a JSON matrix.

    Reads a GitHub Actions matrix JSON (with an ``include`` array of
    ``{library_dir, version, ...}`` entries) and calls :func:`build_bundle`
    for each entry in a single process.
    """
    data = json.loads(matrix_json)
    for entry in data["include"]:
        build_bundle(
            Path(entry["lib_dir"]),
            entry["version"],
            staging_dir,
            mpy_cross,
            experimental=experimental,
        )


def _derive_bundle_id(repo_name: str) -> str:
    """Derive the circup bundle_id from a bundle repository name.

    circup lowercases the repository name and replaces underscores with hyphens.
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

    Scans *bundle_dir* for ``chumicro_*`` package directories, then creates
    two zip files in *output_dir*:

    - ``{bundle_id}-py-{date_tag}.zip`` — ``.py`` source bundle
    - ``{bundle_id}-10.x-mpy-{date_tag}.zip`` — ``.mpy`` bytecode bundle

    The internal structure follows circup's convention::

        {bundle_id}-{platform}-{date_tag}/lib/{package_name}/...

    Returns the list of created zip paths.
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

    source_bundle_name = f"{bundle_id}-py-{date_tag}"
    # "10.x" refers to CircuitPython 10.x's mpy bytecode format (v6).
    # circup parses this pattern to match bundles to the running firmware
    # version on the board — the naming convention is a circup contract.
    bytecode_bundle_name = f"{bundle_id}-10.x-mpy-{date_tag}"

    source_zip_path = output_dir / f"{source_bundle_name}.zip"
    bytecode_zip_path = output_dir / f"{bytecode_bundle_name}.zip"

    with (
        zipfile.ZipFile(source_zip_path, "w", zipfile.ZIP_DEFLATED) as source_zip,
        zipfile.ZipFile(bytecode_zip_path, "w", zipfile.ZIP_DEFLATED) as bytecode_zip,
    ):
        for package_dir in package_dirs:
            package_name = package_dir.name

            # .py source bundle: all .py files.
            for source_file in sorted(package_dir.rglob("*.py")):
                relative_path = source_file.relative_to(package_dir)
                archive_path = f"{source_bundle_name}/lib/{package_name}/{relative_path}"
                source_zip.write(source_file, archive_path)

            # .mpy bytecode bundle: all .mpy files.
            for bytecode_file in sorted(package_dir.rglob("*.mpy")):
                relative_path = bytecode_file.relative_to(package_dir)
                archive_path = f"{bytecode_bundle_name}/lib/{package_name}/{relative_path}"
                bytecode_zip.write(bytecode_file, archive_path)

    created = [source_zip_path, bytecode_zip_path]
    for zip_path in created:
        print(f"Created {zip_path}")
    return created


def _collect_library_metadata(root_dir: Path) -> list[dict]:
    """Collect metadata for all publishable libraries.

    Returns a sorted list of dicts with keys: name, package_name, version,
    description.
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

        # Read description from pyproject.toml.
        with open(library_dir / "pyproject.toml", "rb") as pyproject_file:
            data = tomllib.load(pyproject_file)
        description = data.get("project", {}).get("description", "") or ""

        # Fall back to first non-heading, non-empty line of README.
        if not description and (library_dir / "README.md").exists():
            for line in (library_dir / "README.md").read_text().splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    description = stripped
                    break

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

    Scans *bundle_dir* for ``chumicro_*`` package directories with a
    ``package.json``, reads the version from each manifest, and pulls
    the description from the source workspace.
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


#: GitHub organization and source repository used for README links.
_GITHUB_ORG = "ChuMicro"
_SOURCE_REPO = "ChuMicro"


def generate_bundle_readme(
    root_dir: Path,
    *,
    experimental: bool = False,
    bundle_dir: Path | None = None,
) -> str:
    """Generate a rich README.md for a bundle repo.

    Reads library metadata from the workspace and produces markdown with
    install instructions and a library table linking back to the source repo.

    When *bundle_dir* is provided, only libraries whose packages actually
    exist in that directory are included (with versions from their
    ``package.json``).  This prevents the README from referencing
    libraries that haven't been published to the bundle repo yet.
    """
    if bundle_dir is not None:
        libraries = _collect_bundle_metadata(root_dir, bundle_dir)
    else:
        libraries = _collect_library_metadata(root_dir)

    bundle_repo = EXPERIMENTAL_BUNDLE_REPO if experimental else STABLE_BUNDLE_REPO
    alt_repo = STABLE_BUNDLE_REPO if experimental else EXPERIMENTAL_BUNDLE_REPO
    channel = "Experimental" if experimental else "Stable"
    alt_channel = "Stable" if experimental else "Experimental"
    source_url = f"https://github.com/{_GITHUB_ORG}/{_SOURCE_REPO}"
    alt_repo_url = f"https://github.com/{_GITHUB_ORG}/{alt_repo}"
    docs_url = "https://chumicro.github.io/ChuMicro/"
    pip_suffix = "-experimental" if experimental else ""

    banner = (
        "> ⚠️ **Pre-release channel** — these builds come from the "
        "`main` branch and may contain breaking changes."
        if experimental
        else "> **Stable channel** — production-ready releases from the "
        "`main` branch."
    )


    # Library table rows.
    library_rows = "\n".join(
        f"| [**chumicro-{library['name']}**]({source_url}/tree/main/libraries/{library['name']})"
        f" | {library['version']} | {library['description']} |"
        for library in libraries
    )

    return f"""\
# {bundle_repo}

{banner}

{channel} distribution bundle for \
[ChuMicro]({source_url}) libraries. \
Contains `.py` source, `.mpy` bytecode, and `package.json` \
manifests for [mip](https://docs.micropython.org/en/latest/reference/packages.html) and \
[circup](https://github.com/adafruit/circup) installation.

📖 **[Documentation, guides, and API reference]({docs_url})**

## Installation

### CircuitPython (circup)

Remove any other ChuMicro bundle first, then register this one:

```bash
circup bundle-remove {_GITHUB_ORG}/{alt_repo}   # skip if {alt_channel.lower()} was never added
circup bundle-add {_GITHUB_ORG}/{bundle_repo}
circup install chumicro-timing   # example
```

### MicroPython (mip)

Install directly from the bundle repo:

```bash
mpremote mip install github:{_GITHUB_ORG}/{bundle_repo}/chumicro_timing   # example
```

Or on a network-capable board:

```python
import mip
mip.install("github:{_GITHUB_ORG}/{bundle_repo}/chumicro_timing")   # example
```

### CPython (pip)

CPython users install from PyPI — the bundle repo is not involved:

```bash
pip install chumicro-timing{pip_suffix}   # example
```

## Available libraries

| Library | Version | Description |
| --- | --- | --- |
{library_rows}

Each library directory in this repo contains a `package.json` \
manifest for mip, `.py` source files, and `.mpy` compiled \
bytecode (CircuitPython 10.x, mpy format v6).

## About

This repository is **automatically maintained** by the \
[ChuMicro source repo]({source_url})'s release workflow. \
Do not edit it manually.

- **Source code and examples:** [{_GITHUB_ORG}/{_SOURCE_REPO}]({source_url})
- **Documentation:** [chumicro.github.io/ChuMicro]({docs_url})
- **{alt_channel} bundle:** [{_GITHUB_ORG}/{alt_repo}]({alt_repo_url})
- **License:** [MIT](LICENSE)
"""


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Stage bundle artifacts for mip/circup distribution.",
    )
    subparsers = parser.add_subparsers(dest="command")

    # Default (positional) staging command.
    stage_parser = subparsers.add_parser("stage", help="Stage bundle artifacts")
    stage_parser.add_argument(
        "lib_dir", type=Path, help="Library directory (e.g. libraries/timing)"
    )
    stage_parser.add_argument("version", help="Library version string")
    stage_parser.add_argument("staging_dir", type=Path, help="Output staging directory")
    stage_parser.add_argument(
        "--mpy-cross", default="mpy-cross", help="Path to mpy-cross binary"
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
        "--mpy-cross", default="mpy-cross", help="Path to mpy-cross binary"
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
        build_bundle(
            args.lib_dir,
            args.version,
            args.staging_dir,
            args.mpy_cross,
            experimental=args.experimental,
        )
    elif args.command == "stage-matrix":
        stage_matrix(
            args.staging_dir,
            args.matrix,
            args.mpy_cross,
            experimental=args.experimental,
        )
    elif args.command == "circup-zip":
        build_circup_zips(
            args.bundle_dir,
            args.output_dir,
            args.repo_name,
            date_tag=args.date_tag,
        )
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()
