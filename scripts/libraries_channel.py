"""Stage the full-source-tree libraries channel for workspace acquisition.

The device bundle (``bundle_manager``) flattens each library to
deployable ``.py``+``.mpy`` for circup/mip.  This producer is the
sibling for host-side ``chumicro-workspace library`` acquisition: it
copies each library's *whole* tree (the curated subset a workspace
needs to import, run, and adapt it) into a staging dir plus a root
``index.json`` catalog, then ``bundle_push`` tags+pushes it to
``ChuMicro-Libraries`` / ``-Experimental`` with the same snapshot
model the bundles use.

The staged layout is exactly what a GitHub source tarball of the
tagged repo unwraps to, so the workspace downloader
(``chumicro_workspace.library_channel``) reads it without translation:

    <repo>-<tag>/
      index.json                 {tag, libraries: {chumicro_<n>: {...}}}
      <name>/src|tests|examples|docs/...
      <name>/pyproject.toml | VERSION | README.md

``CURATED_TREES`` / ``CURATED_FILES`` match the downloader's
validation contract (kept in step deliberately: two repos, one
agreed shape).  A mismatch fails the workspace fetch loudly.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from bundle_layout import (
    EXPERIMENTAL_LIBRARIES_REPO,
    STABLE_LIBRARIES_REPO,
)
from repo_layout import read_pyproject_description

#: Trees copied into the channel.  ``src`` is what the deploy walker
#: needs; the rest make the library runnable/adaptable in-workspace.
CURATED_TREES = ("src", "tests", "examples", "docs")

#: Top-level files copied alongside the trees.
CURATED_FILES = ("pyproject.toml", "VERSION", "README.md")

#: Local build/test cruft a contributor's working tree accumulates.
#: ``shutil.copytree`` would otherwise haul it into the published
#: channel.  CI runs on a fresh checkout where most of these are
#: absent.  The filter exists for hand-invoked runs and for the
#: ``.DS_Store``-style entries that survive any checkout.
_COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "*.egg-info",
    ".DS_Store",
)


def channel_repo(*, experimental: bool) -> str:
    """Channel repo name for the requested release line."""
    return (
        EXPERIMENTAL_LIBRARIES_REPO
        if experimental
        else STABLE_LIBRARIES_REPO
    )


def _iter_libraries(root_dir: Path):
    """Yield ``(name, library_dir)`` for each publishable library.

    A library qualifies when it has both ``VERSION`` and
    ``pyproject.toml`` at its root: the same gate the release
    pipeline and ``check-version`` use.
    """
    libraries_dir = root_dir / "libraries"
    if not libraries_dir.is_dir():
        return
    for version_file in sorted(libraries_dir.glob("*/VERSION")):
        library_dir = version_file.parent
        if (library_dir / "pyproject.toml").is_file():
            yield library_dir.name, library_dir


def _example_paths(library_dir: Path, name: str) -> list[str]:
    """Repo-root-relative paths of a library's example files.

    Returned in the form the downloader fetches them by
    (``<name>/examples/...``), POSIX-sloped, deterministically sorted.
    """
    examples_dir = library_dir / "examples"
    if not examples_dir.is_dir():
        return []
    return sorted(
        f"{name}/examples/{path.relative_to(examples_dir).as_posix()}"
        for path in examples_dir.rglob("*")
        if path.is_file()
    )


def stage_libraries_channel(
    root_dir: Path,
    staging_dir: Path,
    *,
    tag: str,
) -> dict:
    """Stage every library tree + the catalog into *staging_dir*.

    Top-level entries in *staging_dir* are wiped (except ``.git/``, so
    a pre-cloned channel checkout passes straight through to the
    ``bundle_push`` step) and rebuilt so a stale library never rides
    a release.  If ``LICENSE`` is present at *root_dir*, it's copied
    in alongside the library trees, matching ``release.yml``'s
    explicit LICENSE copy onto the bundle repo.  Returns the written
    ``index.json`` document (also a convenient summary for the caller
    to log).
    """
    if staging_dir.exists():
        for entry in staging_dir.iterdir():
            if entry.name == ".git":
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    else:
        staging_dir.mkdir(parents=True)

    libraries: dict[str, dict] = {}
    for name, library_dir in _iter_libraries(root_dir):
        destination = staging_dir / name
        destination.mkdir()
        for tree in CURATED_TREES:
            source = library_dir / tree
            if source.is_dir():
                shutil.copytree(
                    source, destination / tree, ignore=_COPY_IGNORE,
                )
        for filename in CURATED_FILES:
            source = library_dir / filename
            if source.is_file():
                shutil.copy2(source, destination / filename)

        version = (library_dir / "VERSION").read_text().strip()
        libraries[f"chumicro_{name}"] = {
            "version": version,
            "description": read_pyproject_description(library_dir),
            "readme_path": f"{name}/README.md",
            "examples": _example_paths(library_dir, name),
        }

    license_source = root_dir / "LICENSE"
    if license_source.is_file():
        shutil.copy2(license_source, staging_dir / "LICENSE")

    document = {"tag": tag, "libraries": libraries}
    (staging_dir / "index.json").write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return document


def main(argv: list[str] | None = None) -> int:
    """Stage the channel; optionally tag+push it (CI / hand-invocation).

    Mirrors ``bundle_manager`` / ``bundle_push``'s entry shape.  The
    release pipeline calls this; ``--push`` reuses the shared
    ``bundle_push`` primitive so tagging stays one mechanism.
    """
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--staging-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument(
        "--experimental", action="store_true",
        help="Target the pre-release channel repo.",
    )
    parser.add_argument(
        "--push", action="store_true",
        help="Commit+tag+push the staged tree (else stage only).",
    )
    args = parser.parse_args(argv)

    document = stage_libraries_channel(
        args.root, args.staging_dir, tag=args.tag,
    )
    repo = channel_repo(experimental=args.experimental)
    print(
        f"Staged {len(document['libraries'])} libraries for {repo} "
        f"@ {args.tag} -> {args.staging_dir}",
    )
    if args.push:  # pragma: no cover - shells git; bundle_push owns its tests
        from bundle_push import push_bundle

        return push_bundle(
            args.staging_dir, args.tag,
            f"libraries channel {args.tag} ({repo})",
        )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
