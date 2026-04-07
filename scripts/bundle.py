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

#: Bundle repo names for each channel.  Experimental uses a separate repo
#: so that circup's latest_tag works per-channel without prerelease tag tricks.
STABLE_BUNDLE_REPO = "ChuMicro-Bundle"
EXPERIMENTAL_BUNDLE_REPO = "ChuMicro-Bundle-Experimental"


def _find_bundle_modules(lib_dir: Path) -> tuple[str, Path, list[Path]]:
    """Discover the package name, package dir, and deployable .py files.

    Returns ``(pkg_name, pkg_dir, py_files)`` where *py_files* are all
    ``.py`` modules to include in the bundle (both as source and compiled
    ``.mpy``).
    """
    pkg_dir = find_package_dir(lib_dir)
    if pkg_dir is None:
        sys.exit(f"No importable package under {lib_dir / 'src'}")

    py_files = [
        f
        for f in sorted(pkg_dir.rglob("*.py"))
        if "__pycache__" not in f.relative_to(pkg_dir).parts
    ]
    return pkg_dir.name, pkg_dir, py_files


def _read_chumicro_deps(lib_dir: Path) -> list[str]:
    """Return chumicro-* dependency names from pyproject.toml."""
    pyproject = lib_dir / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    deps = data.get("project", {}).get("dependencies", [])
    return [d for d in deps if d.strip().startswith("chumicro-")]


def _dep_to_mip_ref(dep: str) -> str:
    """Convert 'chumicro-timing>=0.1' to a mip github reference.

    Dependencies always reference the stable (production) variant.
    An experimental library depends on production releases by default.
    If coordinated experimental changes across libraries are needed,
    the developer overrides specific deps manually.
    """
    # Strip version specifiers.
    name = re.split(r"[><=!;~\[]", dep, maxsplit=1)[0]
    pkg = name.strip().replace("-", "_")
    return f"github:ChuMicro/ChuMicro-Bundle/{pkg}"


def _compile_mpy(py_file: Path, mpy_file: Path, mpy_cross: str) -> None:
    """Compile a single .py file to .mpy."""
    mpy_file.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [mpy_cross, "-o", str(mpy_file), str(py_file)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.exit(f"mpy-cross failed on {py_file}:\n{result.stderr}")


def build_bundle(
    lib_dir: Path,
    version: str,
    staging_dir: Path,
    mpy_cross: str = "mpy-cross",
    *,
    experimental: bool = False,
) -> None:
    """Stage bundle artifacts for a single library.

    Creates ``<staging_dir>/<pkg_name>/`` containing .py source, .mpy
    bytecode, and a package.json manifest for mip.

    When *experimental* is True the package.json URLs point to the
    experimental bundle repo.  Directory names are always the base
    package name (e.g. ``chumicro_timing``) — channel separation is
    by repo, not directory suffix.  This lets users swap between stable
    and experimental without changing import statements.
    """
    pkg_name, pkg_dir, py_files = _find_bundle_modules(lib_dir)
    if not py_files:
        sys.exit(f"No deployable .py files found in {pkg_dir}")

    bundle_repo = EXPERIMENTAL_BUNDLE_REPO if experimental else STABLE_BUNDLE_REPO
    out_dir = staging_dir / pkg_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # All modules get both .py source and .mpy bytecode.
    for f in py_files:
        rel = f.relative_to(pkg_dir)
        dest_py = out_dir / rel
        dest_mpy = (out_dir / rel).with_suffix(".mpy")
        dest_py.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest_py)
        _compile_mpy(f, dest_mpy, mpy_cross)

    # Generate mip package.json manifest.
    #
    # mip (MicroPython's package installer) reads package.json to know
    # which files to download and where to place them on-device.  Each
    # entry in "urls" is [target_path, source_url]:
    #   - target_path: on-device path relative to /lib/ (e.g. chumicro_timing/__init__.mpy)
    #   - source_url:  github: URI pointing to the .mpy file in this bundle repo
    #
    # Both target and source paths use pkg_name — the on-device import name
    # is always the base package name (e.g. chumicro_timing) regardless of
    # channel.  This lets users swap between stable and experimental by
    # changing which bundle repo they use, without changing imports.
    urls = []
    for f in py_files:
        rel = f.relative_to(pkg_dir)
        mpy_rel = rel.with_suffix(".mpy").as_posix()
        target = f"{pkg_name}/{mpy_rel}"
        source = f"github:ChuMicro/{bundle_repo}/{pkg_name}/{mpy_rel}"
        urls.append([target, source])

    manifest: dict = {"urls": urls, "version": version}
    # Dependencies always reference stable variants so that installing
    # one experimental library does not cascade into pulling experimental
    # versions of all transitive dependencies.
    mip_deps = [
        [_dep_to_mip_ref(d), "latest"] for d in _read_chumicro_deps(lib_dir)
    ]
    if mip_deps:
        manifest["deps"] = mip_deps

    with open(out_dir / "package.json", "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")

    print(f"Staged {pkg_name} v{version} -> {out_dir}")


def stage_matrix(
    staging_dir: Path,
    matrix_json: str,
    mpy_cross: str = "mpy-cross",
    *,
    experimental: bool = False,
) -> None:
    """Stage bundle artifacts for all libraries in a JSON matrix.

    Reads a GitHub Actions matrix JSON (with an ``include`` array of
    ``{lib_dir, version, ...}`` entries) and calls :func:`build_bundle`
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
    """Derive the circup bundle_id from a bundle repo name.

    circup lowercases the repo name and replaces underscores with hyphens.
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

        {bundle_id}-{platform}-{date_tag}/lib/{pkg_name}/...

    Returns the list of created zip paths.
    """
    if date_tag is None:
        date_tag = datetime.now(timezone.utc).strftime("%Y%m%d")  # noqa: UP017

    bundle_id = _derive_bundle_id(repo_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    pkg_dirs = sorted(
        d
        for d in bundle_dir.iterdir()
        if d.is_dir() and d.name.startswith("chumicro_")
    )
    if not pkg_dirs:
        print(f"No chumicro_* packages found in {bundle_dir}")
        return []

    py_name = f"{bundle_id}-py-{date_tag}"
    # "10.x" refers to CircuitPython 10.x's mpy bytecode format (v6).
    # circup parses this pattern to match bundles to the running firmware
    # version on the board — the naming convention is a circup contract.
    mpy_name = f"{bundle_id}-10.x-mpy-{date_tag}"

    py_zip_path = output_dir / f"{py_name}.zip"
    mpy_zip_path = output_dir / f"{mpy_name}.zip"

    with (
        zipfile.ZipFile(py_zip_path, "w", zipfile.ZIP_DEFLATED) as py_zip,
        zipfile.ZipFile(mpy_zip_path, "w", zipfile.ZIP_DEFLATED) as mpy_zip,
    ):
        for pkg_dir in pkg_dirs:
            pkg = pkg_dir.name

            # .py source bundle: all .py files.
            for f in sorted(pkg_dir.rglob("*.py")):
                rel = f.relative_to(pkg_dir)
                py_zip.write(f, f"{py_name}/lib/{pkg}/{rel}")

            # .mpy bytecode bundle: all .mpy files.
            for f in sorted(pkg_dir.rglob("*.mpy")):
                rel = f.relative_to(pkg_dir)
                mpy_zip.write(f, f"{mpy_name}/lib/{pkg}/{rel}")

    created = [py_zip_path, mpy_zip_path]
    for p in created:
        print(f"Created {p}")
    return created


def _collect_library_metadata(root: Path) -> list[dict]:
    """Collect metadata for all publishable libraries.

    Returns a sorted list of dicts with keys: name, pkg_name, version,
    description, has_readme.
    """
    libraries_dir = root / "libraries"
    if not libraries_dir.is_dir():
        return []
    entries = []
    for version_file in sorted(libraries_dir.rglob("VERSION")):
        lib_dir = version_file.parent
        if not (lib_dir / "pyproject.toml").exists():
            continue
        version = version_file.read_text().strip()
        name = lib_dir.name  # e.g. "timing"

        # Read description from pyproject.toml.
        with open(lib_dir / "pyproject.toml", "rb") as f:
            data = tomllib.load(f)
        description = data.get("project", {}).get("description", "") or ""

        # Fall back to first non-heading, non-empty line of README.
        if not description and (lib_dir / "README.md").exists():
            for line in (lib_dir / "README.md").read_text().splitlines():
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    description = stripped
                    break

        # Derive the import-name from the src/ directory.
        pkg = find_package_dir(lib_dir)
        pkg_name = pkg.name if pkg else f"chumicro_{name}"

        entries.append(
            {
                "name": name,
                "pkg_name": pkg_name,
                "version": version,
                "description": description,
            }
        )
    return entries


def _collect_bundle_metadata(root: Path, bundle_dir: Path) -> list[dict]:
    """Collect metadata only for libraries present in *bundle_dir*.

    Scans *bundle_dir* for ``chumicro_*`` package directories with a
    ``package.json``, reads the version from each manifest, and pulls
    the description from the source workspace.
    """
    pkg_dirs = sorted(
        d for d in bundle_dir.iterdir()
        if d.is_dir() and d.name.startswith("chumicro_") and (d / "package.json").exists()
    )
    if not pkg_dirs:
        return []

    # Build a description lookup from the source workspace.
    all_metadata = {m["pkg_name"]: m for m in _collect_library_metadata(root)}

    entries = []
    for pkg_dir in pkg_dirs:
        pkg_name = pkg_dir.name  # e.g. "chumicro_timing"
        with open(pkg_dir / "package.json") as f:
            manifest = json.load(f)
        version = manifest.get("version", "unknown")

        # Derive the short name (e.g. "timing" from "chumicro_timing").
        name = pkg_name.removeprefix("chumicro_")

        source = all_metadata.get(pkg_name, {})
        description = source.get("description", "")

        entries.append(
            {
                "name": name,
                "pkg_name": pkg_name,
                "version": version,
                "description": description,
            }
        )
    return entries


#: GitHub org and source repo used for README links.
_GITHUB_ORG = "ChuMicro"
_SOURCE_REPO = "ChuMicro"


def generate_bundle_readme(
    root: Path,
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
        libraries = _collect_bundle_metadata(root, bundle_dir)
    else:
        libraries = _collect_library_metadata(root)
    bundle_repo = EXPERIMENTAL_BUNDLE_REPO if experimental else STABLE_BUNDLE_REPO
    channel = "Experimental" if experimental else "Stable"
    source_url = f"https://github.com/{_GITHUB_ORG}/{_SOURCE_REPO}"

    lines: list[str] = []

    # Header.
    lines.append(f"# {bundle_repo}")
    lines.append("")
    if experimental:
        lines.append(
            "> ⚠️ **Pre-release channel** — these builds come from the "
            "`main` branch and may contain breaking changes."
        )
    else:
        lines.append(
            "> **Stable channel** — production-ready releases from the "
            "`main` branch."
        )
    lines.append("")
    lines.append(
        f"{channel} distribution bundle for "
        f"[ChuMicro]({source_url}) libraries.  "
        "Contains `.py` source, `.mpy` bytecode, and `package.json` "
        "manifests for [mip](https://docs.micropython.org/en/latest/"
        "reference/packages.html) and "
        "[circup](https://github.com/adafruit/circup) installation."
    )
    lines.append("")
    docs_url = "https://chumicro.github.io/ChuMicro/"
    lines.append(
        f"📖 **[Documentation, guides, and API reference]({docs_url})**"
    )
    lines.append("")

    # Install instructions.
    other_repo = STABLE_BUNDLE_REPO if experimental else EXPERIMENTAL_BUNDLE_REPO
    other_label = "stable" if experimental else "experimental"
    lines.append("## Installation")
    lines.append("")
    lines.append("### CircuitPython (circup)")
    lines.append("")
    lines.append(
        "Remove any other ChuMicro bundle first, then register this one:"
    )
    lines.append("")
    lines.append("```bash")
    lines.append(
        f"circup bundle-remove {_GITHUB_ORG}/{other_repo}   "
        f"# skip if {other_label} was never added"
    )
    lines.append(f"circup bundle-add {_GITHUB_ORG}/{bundle_repo}")
    lines.append("circup install chumicro-timing   # example")
    lines.append("```")
    lines.append("")
    lines.append("### MicroPython (mip)")
    lines.append("")
    lines.append("Install directly from the bundle repo:")
    lines.append("")
    lines.append("```bash")
    lines.append(
        f"mpremote mip install github:{_GITHUB_ORG}/{bundle_repo}/chumicro_timing"
        "   # example"
    )
    lines.append("```")
    lines.append("")
    lines.append("Or on a network-capable board:")
    lines.append("")
    lines.append("```python")
    lines.append("import mip")
    lines.append(
        f'mip.install("github:{_GITHUB_ORG}/{bundle_repo}/chumicro_timing")'
        "   # example"
    )
    lines.append("```")
    lines.append("")
    lines.append("### CPython (pip)")
    lines.append("")
    lines.append(
        "CPython users install from PyPI — the bundle repo is not involved:"
    )
    lines.append("")
    lines.append("```bash")
    if experimental:
        lines.append("pip install chumicro-timing-experimental   # example")
    else:
        lines.append("pip install chumicro-timing   # example")
    lines.append("```")
    lines.append("")

    # Library table.
    lines.append("## Available libraries")
    lines.append("")
    lines.append(
        "| Library | Version | Description |"
    )
    lines.append(
        "| --- | --- | --- |"
    )
    for lib in libraries:
        pip_name = f"chumicro-{lib['name']}"
        lib_url = f"{source_url}/tree/main/libraries/{lib['name']}"
        desc = lib["description"]
        lines.append(
            f"| [**{pip_name}**]({lib_url}) | {lib['version']} | {desc} |"
        )
    lines.append("")
    lines.append(
        "Each library directory in this repo contains a `package.json` "
        "manifest for mip, `.py` source files, and `.mpy` compiled "
        "bytecode (CircuitPython 10.x, mpy format v6)."
    )
    lines.append("")

    # About.
    lines.append("## About")
    lines.append("")
    lines.append(
        "This repository is **automatically maintained** by the "
        f"[ChuMicro source repo]({source_url})'s release workflow.  "
        "Do not edit it manually."
    )
    lines.append("")
    lines.append(
        f"- **Source code and examples:** [{_GITHUB_ORG}/{_SOURCE_REPO}]"
        f"({source_url})"
    )
    lines.append(
        "- **Documentation:** [chumicro.github.io/ChuMicro]"
        "(https://chumicro.github.io/ChuMicro/)"
    )
    if experimental:
        lines.append(
            f"- **Stable bundle:** [{_GITHUB_ORG}/{STABLE_BUNDLE_REPO}]"
            f"(https://github.com/{_GITHUB_ORG}/{STABLE_BUNDLE_REPO})"
        )
    else:
        lines.append(
            f"- **Experimental bundle:** [{_GITHUB_ORG}/{EXPERIMENTAL_BUNDLE_REPO}]"
            f"(https://github.com/{_GITHUB_ORG}/{EXPERIMENTAL_BUNDLE_REPO})"
        )
    lines.append(
        "- **License:** [MIT](LICENSE)"
    )
    lines.append("")
    return "\n".join(lines)


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
        "readme", help="Generate bundle repo README.md to stdout"
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
        help="Bundle repo name (e.g. ChuMicro-Bundle) — used to derive bundle_id",
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
