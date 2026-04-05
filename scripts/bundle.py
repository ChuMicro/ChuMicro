"""Stage bundle artifacts for a library's mip/circup distribution.

Copies deployable .py source files, compiles .mpy bytecode with mpy-cross,
and generates a mip-compatible package.json manifest.

Usage:
    python scripts/bundle.py <lib_dir> <version> <staging_dir> [--mpy-cross PATH]

Example:
    python scripts/bundle.py libraries/timing 0.1.0 .bundle-staging
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

#: Bundle repo names for each channel.  Experimental uses a separate repo
#: so that circup's latest_tag works per-channel without prerelease tag tricks.
STABLE_BUNDLE_REPO = "ChuMicro-Bundle"
EXPERIMENTAL_BUNDLE_REPO = "ChuMicro-Bundle-Experimental"


def _is_testing_module(rel: Path) -> bool:
    """Return True if *rel* (relative to the package root) is a testing module.

    Testing modules (``testing.py`` at the package root and the ``testing/``
    subpackage) ship as source-only — they provide mock/fake layers for users
    and must not be compiled to ``.mpy``.
    """
    return rel.parts[0] == "testing" or (
        len(rel.parts) == 1 and rel.name == "testing.py"
    )


def _find_bundle_modules(
    lib_dir: Path,
) -> tuple[str, Path, list[Path], list[Path]]:
    """Discover the package name, package dir, compilable and source-only files.

    Returns ``(pkg_name, pkg_dir, compile_files, source_only_files)`` where
    *compile_files* get both ``.py`` and ``.mpy`` artifacts and
    *source_only_files* (testing modules) are shipped as ``.py`` only.
    """
    src_dir = lib_dir / "src"
    candidates = [
        d
        for d in src_dir.iterdir()
        if d.is_dir()
        and not d.name.startswith((".", "_"))
        and not d.name.endswith(".egg-info")
    ]
    if len(candidates) != 1:
        sys.exit(
            f"Expected exactly one package under {src_dir}, "
            f"found {len(candidates)}: {[c.name for c in candidates]}"
        )

    pkg_dir = candidates[0]
    compile_files: list[Path] = []
    source_only_files: list[Path] = []
    for f in sorted(pkg_dir.rglob("*.py")):
        rel = f.relative_to(pkg_dir)
        if "__pycache__" in rel.parts:
            continue
        if _is_testing_module(rel):
            source_only_files.append(f)
        else:
            compile_files.append(f)

    return pkg_dir.name, pkg_dir, compile_files, source_only_files


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
    name = dep.split(">")[0].split("<")[0].split("=")[0].split("!")[0].split(";")[0]
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
    pkg_name, pkg_dir, compile_files, source_only_files = _find_bundle_modules(
        lib_dir,
    )
    all_files = compile_files + source_only_files
    if not all_files:
        sys.exit(f"No deployable .py files found in {pkg_dir}")

    bundle_repo = EXPERIMENTAL_BUNDLE_REPO if experimental else STABLE_BUNDLE_REPO
    out_dir = staging_dir / pkg_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Compilable modules get both .py and .mpy artifacts.
    for f in compile_files:
        rel = f.relative_to(pkg_dir)
        dest_py = out_dir / rel
        dest_mpy = (out_dir / rel).with_suffix(".mpy")
        dest_py.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest_py)
        _compile_mpy(f, dest_mpy, mpy_cross)

    # Testing modules ship as .py only (mock/fake layer for users).
    for f in source_only_files:
        rel = f.relative_to(pkg_dir)
        dest_py = out_dir / rel
        dest_py.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest_py)

    # Generate mip package.json manifest.
    #
    # Both target and source paths use pkg_name — the on-device import name
    # is always the base package name (e.g. chumicro_timing) regardless of
    # channel.  This lets users swap between stable and experimental by
    # changing which bundle repo they use, without changing imports.
    # Compilable modules reference .mpy; testing modules reference .py.
    urls = []
    for f in compile_files:
        rel = f.relative_to(pkg_dir)
        mpy_rel = rel.with_suffix(".mpy").as_posix()
        target = f"{pkg_name}/{mpy_rel}"
        source = f"github:ChuMicro/{bundle_repo}/{pkg_name}/{mpy_rel}"
        urls.append([target, source])
    for f in source_only_files:
        rel = f.relative_to(pkg_dir)
        py_rel = rel.as_posix()
        target = f"{pkg_name}/{py_rel}"
        source = f"github:ChuMicro/{bundle_repo}/{pkg_name}/{py_rel}"
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
        src_dir = lib_dir / "src"
        pkg_name = f"chumicro_{name}"
        if src_dir.is_dir():
            for d in src_dir.iterdir():
                if (
                    d.is_dir()
                    and d.name.startswith("chumicro_")
                    and not d.name.endswith(".egg-info")
                ):
                    pkg_name = d.name
                    break

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


def generate_bundle_readme(root: Path, *, experimental: bool = False) -> str:
    """Generate a rich README.md for a bundle repo.

    Reads library metadata from the workspace and produces markdown with
    install instructions and a library table linking back to the source repo.
    """
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
            "`develop` branch and may contain breaking changes."
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
        lib_url = f"{source_url}/tree/develop/libraries/{lib['name']}"
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
        f"- **Source code, docs, and examples:** [{_GITHUB_ORG}/{_SOURCE_REPO}]"
        f"({source_url})"
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
        f"- **License:** [MIT]({source_url}/blob/develop/LICENSE)"
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

    args = parser.parse_args()

    if args.command == "readme":
        root = Path(__file__).resolve().parent.parent
        content = generate_bundle_readme(root, experimental=args.experimental)
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
    else:
        parser.print_help()
        raise SystemExit(1)


if __name__ == "__main__":
    main()

