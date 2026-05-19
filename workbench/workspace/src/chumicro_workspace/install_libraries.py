"""Acquire chumicro libraries the project imports into a host-local tree.

The regular-mode mirror of dev-mode's ``library_sources:`` auto-sync
(:mod:`chumicro_workspace.chumicro_dev`).  In regular mode the user
hasn't pulled a sibling chumicro checkout, so the project's
``import chumicro_<name>`` statements have no host-side referent for
the deploy-time import-graph walker to bundle.

Acquisition is **host-local**: nothing here writes a device.  A
library reaches a board only by being made resolvable to host source
the import-graph walker can see, after which the one deploy stages it
like any other payload (the single device-staging path).  Regular
mode becomes dev mode pointed at a fetched local tree instead of a
sibling checkout.

The user-visible flow:

1. AST-walks every ``.py`` under the project directory and collects
   every ``chumicro_<name>`` top-level module imported.
2. Maps each to its distribution name (``chumicro_kvstore`` →
   ``chumicro-kvstore``).
3. Fetches each into ``<workspace>/_libraries/<name>/src/`` — the
   gitignored, tool-managed cache (``pip install --target`` is the
   primary backend; ``mpremote mip install --target`` the
   download-to-local fallback for mip-only packages).  Never a board
   or CIRCUITPY mount.
4. Registers each fetched tree in ``workspace.yml``'s managed
   ``library_sources:`` block so the deploy-time walker resolves it —
   the same mechanism dev mode uses.

This module owns the host-side primitives (AST walk + name map +
fetch-command builders + cache-path resolution).  Subprocess
execution lives in the CLI command
(:func:`chumicro_workspace.cli._cmd_install_libraries`) so the
primitives stay pure-functional and trivially testable.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

#: Canonical bundle repository for stable chumicro releases.  Mirrors
#: the constant in ``scripts/bundle_layout.py`` but re-stated here so
#: chumicro-workspace doesn't depend on the mono-repo's ``scripts/``
#: tree (workbench packages are independently publishable).
STABLE_BUNDLE_REPO = "ChuMicro-Bundle"

#: Pre-release bundle repository for chumicro experimental releases.
EXPERIMENTAL_BUNDLE_REPO = "ChuMicro-Bundle-Experimental"

#: GitHub organization that owns both bundle repos.  Used in
#: ``circup bundle-add <org>/<repo>`` and ``mpremote mip install
#: github:<org>/<repo>/<package>`` URLs.
DEFAULT_GITHUB_ORG = "ChuMicro"


def discover_chumicro_imports(project_dir: Path) -> set[str]:
    """Return every ``chumicro_*`` top-level module name imported under *project_dir*.

    Walks every ``.py`` under *project_dir* recursively and collects
    the top-level segment of every ``import`` / ``from ... import``
    target whose name starts with ``chumicro_``.  AST-only — no module
    execution, no search-path resolution — so it works on a fresh
    workspace without needing the libraries already installed
    anywhere.

    Catches:

    * ``import chumicro_foo``
    * ``import chumicro_foo as bar``
    * ``import chumicro_foo, chumicro_bar``
    * ``from chumicro_foo import baz``
    * ``from chumicro_foo.submod import baz`` (returns the top-level)

    Misses dynamic imports (``__import__``,
    ``importlib.import_module``).  Users who rely on those need to
    pass the package list explicitly.

    Files with syntax errors are skipped silently — the user's bug,
    not ours; whatever Python the user runs will surface the error
    on its own.
    """
    discovered: set[str] = set()
    for source_path in sorted(project_dir.rglob("*.py")):
        if not source_path.is_file():
            continue
        try:
            tree = ast.parse(source_path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".", 1)[0]
                    if top.startswith("chumicro_"):
                        discovered.add(top)
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    # Relative ``from . import X`` — never chumicro-shaped.
                    continue
                top = node.module.split(".", 1)[0]
                if top.startswith("chumicro_"):
                    discovered.add(top)
    return discovered


def import_name_to_package(import_name: str) -> str:
    """``chumicro_kvstore`` → ``chumicro-kvstore``.

    The on-PyPI / circup / mip name uses dashes; the Python module
    name uses underscores.
    """
    return import_name.replace("_", "-")


#: Gitignored, tool-managed cache dir under the workspace root.  Each
#: fetched library lands at ``<workspace>/_libraries/<name>/src/`` —
#: the same ``libraries/<name>/src/`` shape dev mode resolves against,
#: so the deploy-time import-graph walker treats fetched and
#: sibling-checkout libraries identically.  Joins ``_generated/`` as a
#: never-committed workspace artifact dir; reproducible from the
#: project's imports + the distribution.
LIBRARIES_CACHE_DIRNAME = "_libraries"

#: Marker comment written above the managed ``library_sources:`` block
#: when ``install-libraries`` owns it (regular mode).  Distinct from
#: dev mode's marker so a human opening ``workspace.yml`` sees which
#: tool wrote the block; the sync is the same raw-text primitive.
LIBRARY_SOURCES_MARKER = (
    "managed by chumicro-workspace install-libraries — host-local fetch"
)


def local_src_dir(workspace_root: Path, import_name: str) -> Path:
    """Host-local src dir a fetched *import_name* is acquired into.

    ``chumicro_kvstore`` → ``<workspace_root>/_libraries/kvstore/src``.
    The directory's child is the importable package
    (``chumicro_kvstore/``), so the path is exactly what
    ``library_sources:`` maps the import name to.
    """
    short_name = import_name.removeprefix("chumicro_")
    return (
        workspace_root / LIBRARIES_CACHE_DIRNAME / short_name / "src"
    )


def build_pip_fetch_command(package: str, target_dir: Path) -> list[str]:
    """``pip install --target`` *package* into *target_dir* (the primary backend).

    ``--target`` writes the package tree (and its dependency closure)
    straight into *target_dir* on the host — no virtualenv mutation,
    no board contact.  ``--upgrade`` keeps a re-run idempotent against
    a newer release.  Runs under the active interpreter so it uses the
    workspace's own pip.

    Args:
        package: distribution name — e.g. ``"chumicro-kvstore"``.
        target_dir: ``<workspace>/_libraries/<name>/src`` (created by
            pip if absent).
    """
    return [
        sys.executable, "-m", "pip", "install",
        "--target", str(target_dir), "--upgrade", package,
    ]


def build_mip_fetch_command(
    import_name: str,
    target_dir: Path,
    *,
    bundle_repo: str = STABLE_BUNDLE_REPO,
    org: str = DEFAULT_GITHUB_ORG,
) -> list[str]:
    """``mpremote mip install --target`` *import_name* into *target_dir*.

    The download-to-local fallback for packages served only from the
    bundle repo (not PyPI).  ``--target`` makes ``mip`` write to a
    host directory instead of a connected board — no device, no
    CIRCUITPY mount.  Pulls ``github:<org>/<bundle_repo>/<import_name>``
    (the underscored import name is what the bundle's ``package.json``
    files are keyed by).

    Args:
        import_name: importable module name — e.g. ``"chumicro_kvstore"``.
        target_dir: ``<workspace>/_libraries/<name>/src``.
        bundle_repo: ``ChuMicro-Bundle`` (stable, default) or
            ``ChuMicro-Bundle-Experimental``.
        org: GitHub organization owning the bundle repo.
    """
    return [
        "mpremote", "mip", "install",
        "--target", str(target_dir),
        f"github:{org}/{bundle_repo}/{import_name}",
    ]
