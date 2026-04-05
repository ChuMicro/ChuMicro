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


def _dep_to_mip_ref(dep: str, *, experimental: bool = False) -> str:
    """Convert 'chumicro-timing>=0.1' to a mip github reference.

    When *experimental* is True, the reference points to the
    ``_experimental`` variant so that experimental packages depend on
    other experimental packages.
    """
    # Strip version specifiers.
    name = dep.split(">")[0].split("<")[0].split("=")[0].split("!")[0].split(";")[0]
    pkg = name.strip().replace("-", "_")
    if experimental:
        pkg = f"{pkg}_experimental"
    return f"github:ChuMicro/chumicro-bundle/{pkg}"


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

    Creates ``<staging_dir>/<bundle_name>/`` containing .py source, .mpy
    bytecode, and a package.json manifest for mip.

    When *experimental* is True the bundle directory gets an
    ``_experimental`` suffix (e.g. ``chumicro_timing_experimental/``).
    The mip manifest's on-device install paths still use the original
    package name so that ``import chumicro_timing`` works regardless of
    which channel the user installed from.
    """
    pkg_name, pkg_dir, compile_files, source_only_files = _find_bundle_modules(
        lib_dir,
    )
    all_files = compile_files + source_only_files
    if not all_files:
        sys.exit(f"No deployable .py files found in {pkg_dir}")

    # Bundle directory name — suffixed for experimental channel.
    bundle_name = f"{pkg_name}_experimental" if experimental else pkg_name
    out_dir = staging_dir / bundle_name
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
    # Target paths (first element) use pkg_name — the on-device import name.
    # Source URLs (second element) use bundle_name — where the file lives in
    # the bundle repo (includes _experimental suffix when applicable).
    # Compilable modules reference .mpy; testing modules reference .py.
    urls = []
    for f in compile_files:
        rel = f.relative_to(pkg_dir)
        mpy_rel = rel.with_suffix(".mpy").as_posix()
        target = f"{pkg_name}/{mpy_rel}"
        source = f"github:ChuMicro/chumicro-bundle/{bundle_name}/{mpy_rel}"
        urls.append([target, source])
    for f in source_only_files:
        rel = f.relative_to(pkg_dir)
        py_rel = rel.as_posix()
        target = f"{pkg_name}/{py_rel}"
        source = f"github:ChuMicro/chumicro-bundle/{bundle_name}/{py_rel}"
        urls.append([target, source])

    manifest: dict = {"urls": urls, "version": version}
    mip_deps = [
        [_dep_to_mip_ref(d, experimental=experimental), "latest"]
        for d in _read_chumicro_deps(lib_dir)
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
    parser.add_argument(
        "--experimental",
        action="store_true",
        help="Stage as experimental channel (adds _experimental suffix to bundle directory)",
    )
    args = parser.parse_args()
    build_bundle(
        args.lib_dir,
        args.version,
        args.staging_dir,
        args.mpy_cross,
        experimental=args.experimental,
    )


if __name__ == "__main__":
    main()

