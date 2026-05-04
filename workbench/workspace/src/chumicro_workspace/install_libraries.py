"""Install chumicro libraries onto a device via ``circup`` (CP) or ``mip`` (MP).

The regular-mode mirror of dev-mode's ``library_sources:`` auto-sync
(:mod:`chumicro_workspace.chumicro_dev`).  In regular mode the user
hasn't pulled a sibling chumicro checkout — the project's
``import chumicro_<name>`` statements need their referents on the
board's flash, fetched from the published bundle.

The user-visible flow:

1. AST-walks every ``.py`` under the project directory and collects
   every ``chumicro_<name>`` top-level module imported.
2. Maps each to its bundle package name (``chumicro_kvstore`` →
   ``chumicro-kvstore``).
3. Builds the right shell command per target runtime:

   * **CircuitPython** — one ``circup install <pkg-list>`` invocation,
     optionally pinned to a specific CIRCUITPY drive via ``--path``.
     Assumes the user has already run ``circup bundle-add
     ChuMicro/ChuMicro-Bundle`` once for stable, or
     ``ChuMicro/ChuMicro-Bundle-Experimental`` for experimental.
   * **MicroPython** — one ``mpremote ... mip install
     github:ChuMicro/<bundle_repo>/<import_name>`` per package
     (``mip.install`` doesn't take a list).  No prior registration
     step — the bundle repo URL is in each invocation.

This module owns the host-side primitives (AST walk + command
builders).  Subprocess execution lives in the CLI command
(:func:`chumicro_workspace.cli._cmd_install_libraries`) so the
primitives stay pure-functional and trivially testable.

Gap #4 of the workspace-template dev-and-regular-mode-gaps audit.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

#: Canonical bundle repository for stable chumicro releases.  Mirrors
#: the constant in ``scripts/bundle_layout.py`` but re-stated here so
#: chumicro-workspace doesn't depend on the mono-repo's ``scripts/``
#: tree (workbench packages are independently publishable).
STABLE_BUNDLE_REPO = "ChuMicro-Bundle"

#: Pre-release bundle repository for chumicro experimental releases.
EXPERIMENTAL_BUNDLE_REPO = "ChuMicro-Bundle-Experimental"

#: GitHub organisation that owns both bundle repos.  Used in
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


def build_circup_command(
    packages: Iterable[str],
    *,
    drive_path: str | None = None,
) -> list[str]:
    """Build a ``circup install`` command for *packages*.

    Returns one command — circup accepts a package list inline.
    Caller is responsible for ensuring the chumicro bundle is
    registered first (one-time ``circup bundle-add
    ChuMicro/ChuMicro-Bundle``).

    Args:
        packages: bundle package names — e.g. ``"chumicro-kvstore"``.
        drive_path: optional explicit CIRCUITPY mount.  Pass when
            there are multiple CIRCUITPY drives so circup knows which
            one to install onto; omit to let circup auto-detect.
    """
    command = ["circup"]
    if drive_path is not None:
        command.extend(["--path", drive_path])
    command.append("install")
    command.extend(sorted(packages))
    return command


def build_mip_commands(
    packages: Iterable[str],
    *,
    bundle_repo: str = STABLE_BUNDLE_REPO,
    org: str = DEFAULT_GITHUB_ORG,
    address: str | None = None,
) -> list[list[str]]:
    """Build one ``mpremote ... mip install`` command per chumicro package.

    ``mip.install`` doesn't accept a list — one invocation per
    package.  Each command pulls
    ``github:<org>/<bundle_repo>/<import_name>``; the import-name
    form (underscored) is what the bundle's ``package.json`` files
    are keyed by.

    Args:
        packages: bundle package names — e.g. ``"chumicro-kvstore"``.
        bundle_repo: ``ChuMicro-Bundle`` (stable, default) or
            ``ChuMicro-Bundle-Experimental``.
        org: GitHub organisation owning the bundle repo.
        address: optional serial address for ``mpremote connect``.
            Pass when multiple boards are connected so mpremote
            knows which one to install onto.
    """
    commands: list[list[str]] = []
    for package_name in sorted(packages):
        import_name = package_name.replace("-", "_")
        command = ["mpremote"]
        if address is not None:
            command.extend(["connect", address])
        command.extend([
            "mip", "install",
            f"github:{org}/{bundle_repo}/{import_name}",
        ])
        commands.append(command)
    return commands
