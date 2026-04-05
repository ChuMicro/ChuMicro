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


def _find_bundle_modules(lib_dir: Path) -> tuple[str, Path, list[Path]]:
    """Discover the package name, package directory, and deployable .py files.

    Excludes testing modules (test fakes not intended for deployment)
    and __pycache__ directories.
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
    py_files = []
    for f in sorted(pkg_dir.rglob("*.py")):
        rel = f.relative_to(pkg_dir)
        if "__pycache__" in rel.parts:
            continue
        # Exclude testing.py at package root and testing/ subpackage.
        if rel.parts[0] == "testing" or (
            len(rel.parts) == 1 and rel.name == "testing.py"
        ):
            continue
        py_files.append(f)

    return pkg_dir.name, pkg_dir, py_files


def _read_chumicro_deps(lib_dir: Path) -> list[str]:
    """Return chumicro-* dependency names from pyproject.toml."""
    pyproject = lib_dir / "pyproject.toml"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    deps = data.get("project", {}).get("dependencies", [])
    return [d for d in deps if d.strip().startswith("chumicro-")]


def _dep_to_mip_ref(dep: str) -> str:
    """Convert 'chumicro-timing>=0.1' to a mip github reference."""
    # Strip version specifiers.
    name = dep.split(">")[0].split("<")[0].split("=")[0].split("!")[0].split(";")[0]
    return f"github:ChuMicro/chumicro-bundle/{name.strip().replace('-', '_')}"


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
) -> None:
    """Stage bundle artifacts for a single library.

    Creates ``<staging_dir>/<pkg_name>/`` containing .py source, .mpy
    bytecode, and a package.json manifest for mip.
    """
    pkg_name, pkg_dir, py_files = _find_bundle_modules(lib_dir)
    if not py_files:
        sys.exit(f"No deployable .py files found in {pkg_dir}")

    out_dir = staging_dir / pkg_name
    out_dir.mkdir(parents=True, exist_ok=True)

    for f in py_files:
        rel = f.relative_to(pkg_dir)
        dest_py = out_dir / rel
        dest_mpy = (out_dir / rel).with_suffix(".mpy")
        dest_py.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest_py)
        _compile_mpy(f, dest_mpy, mpy_cross)

    # Generate mip package.json manifest.
    urls = []
    for f in py_files:
        rel = f.relative_to(pkg_dir)
        mpy_path = f"{pkg_name}/{rel.with_suffix('.mpy').as_posix()}"
        urls.append([mpy_path, f"github:ChuMicro/chumicro-bundle/{mpy_path}"])

    manifest: dict = {"urls": urls, "version": version}
    mip_deps = [
        [_dep_to_mip_ref(d), "latest"] for d in _read_chumicro_deps(lib_dir)
    ]
    if mip_deps:
        manifest["deps"] = mip_deps

    with open(out_dir / "package.json", "w") as fh:
        json.dump(manifest, fh, indent=2)
        fh.write("\n")

    print(f"Staged {pkg_name} v{version} -> {out_dir}")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Stage bundle artifacts for mip/circup distribution.",
    )
    parser.add_argument(
        "lib_dir", type=Path, help="Library directory (e.g. libraries/timing)"
    )
    parser.add_argument("version", help="Library version string")
    parser.add_argument("staging_dir", type=Path, help="Output staging directory")
    parser.add_argument(
        "--mpy-cross", default="mpy-cross", help="Path to mpy-cross binary"
    )
    args = parser.parse_args()
    build_bundle(args.lib_dir, args.version, args.staging_dir, args.mpy_cross)


if __name__ == "__main__":
    main()

