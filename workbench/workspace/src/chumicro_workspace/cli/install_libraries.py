"""``install-libraries`` subcommand — host-local library acquisition.

Fetches the chumicro libraries the project imports into the
gitignored ``<workspace>/_libraries/<name>/src/`` cache and registers
them in ``workspace.yml``'s managed ``library_sources:`` block.  The
one deploy then bundles them onto the board — nothing here touches a
device.  Regular-mode counterpart to dev-mode's sibling-checkout
``library_sources:`` auto-sync.
"""

from __future__ import annotations

import argparse
import sys

from chumicro_workspace.cli._common import (
    _add_workspace_arg,
    _resolve_project_name,
    _resolve_workspace,
)
from chumicro_workspace.install_libraries import (
    LIBRARIES_CACHE_DIRNAME,
    LIBRARY_SOURCES_MARKER,
    build_mip_fetch_command,
    build_pip_fetch_command,
    discover_chumicro_imports,
    import_name_to_package,
    local_src_dir,
)
from chumicro_workspace.managed_block import sync_managed_block


def _cmd_install_libraries(args: argparse.Namespace) -> int:
    """Acquire the project's chumicro libraries into the host-local cache.

    AST-walks PROJECT for ``chumicro_<name>`` imports, fetches each
    into ``<workspace>/_libraries/<name>/src/`` (``pip install
    --target`` by default; ``--backend mip`` for the
    ``mpremote mip install --target`` download-to-local fallback),
    then registers every fetched tree in ``workspace.yml``'s managed
    ``library_sources:`` block.  No device is contacted — the next
    ``chumicro-workspace deploy`` bundles the libraries onto the board
    through the one staging path.

    ``--experimental`` swaps the mip bundle repo to
    ``ChuMicro-Bundle-Experimental`` (no effect on the pip backend).
    ``--dry-run`` prints the fetch commands without executing them and
    skips the ``library_sources:`` write.
    """
    workspace = _resolve_workspace(args)
    project_name = _resolve_project_name(workspace, args.project)
    project_dir = workspace.project_dir(project_name)
    if not project_dir.is_dir():
        print(
            f"install-libraries: project {project_dir} not found",
            file=sys.stderr,
        )
        return 1

    imports = discover_chumicro_imports(project_dir)
    if not imports:
        print(
            f"install-libraries: no chumicro imports found in "
            f"{project_name} — nothing to acquire.",
        )
        return 0
    import_names = sorted(imports)
    print(
        f"install-libraries: {project_name} imports "
        f"{len(import_names)} chumicro libraries:",
    )
    for import_name in import_names:
        print(f"  {import_name}")

    registered: dict[str, str] = {}
    for import_name in import_names:
        target_dir = local_src_dir(workspace.root, import_name)
        if args.backend == "mip":
            command = build_mip_fetch_command(
                import_name,
                target_dir,
                bundle_repo=(
                    "ChuMicro-Bundle-Experimental"
                    if args.experimental
                    else "ChuMicro-Bundle"
                ),
            )
        else:
            command = build_pip_fetch_command(
                import_name_to_package(import_name), target_dir,
            )
        print(f"  $ {' '.join(command)}")
        if args.dry_run:
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        completed = args._env.subprocess_runner(command, check=False)  # noqa: S603 — args fully controlled
        if completed.returncode != 0:
            print(
                f"install-libraries: fetch of {import_name} failed "
                f"(exit {completed.returncode}); fix the underlying "
                "tool error and re-run install-libraries.",
                file=sys.stderr,
            )
            return completed.returncode
        registered[import_name] = (
            f"{LIBRARIES_CACHE_DIRNAME}/"
            f"{import_name.removeprefix('chumicro_')}/src"
        )

    if args.dry_run:
        print(
            "install-libraries: --dry-run — no fetch ran, "
            "library_sources unchanged.",
        )
        return 0

    child_lines = [
        f"  {name}: {registered[name]}" for name in sorted(registered)
    ]
    sync_managed_block(
        workspace.workspace_yaml,
        "library_sources",
        LIBRARY_SOURCES_MARKER,
        child_lines,
    )
    print(
        f"install-libraries: acquired {len(registered)} libraries into "
        f"{LIBRARIES_CACHE_DIRNAME}/ and registered library_sources.\n"
        f"  next: chumicro-workspace deploy {project_name}",
    )
    return 0


def _add_install_libraries_parser(subparsers: argparse._SubParsersAction) -> None:
    """``install-libraries`` — host-local library acquisition per project."""
    install_libraries_parser = subparsers.add_parser(
        "install-libraries",
        help=(
            "Fetch the chumicro libraries the project imports into the "
            "host-local cache and register library_sources."
        ),
        description=(
            "AST-walks PROJECT for chumicro_<name> imports, fetches "
            "each into <workspace>/_libraries/<name>/src/ (pip "
            "--target by default; --backend mip for the mip "
            "download-to-local fallback), and registers them in "
            "workspace.yml's managed library_sources block.  No device "
            "is contacted — run `chumicro-workspace deploy` afterwards "
            "to bundle them onto the board.  Regular-mode counterpart "
            "to dev-mode's sibling-checkout library_sources sync.  Use "
            "--dry-run to preview the fetch commands."
        ),
    )
    _add_workspace_arg(install_libraries_parser)
    install_libraries_parser.add_argument(
        "project",
        help=(
            "Project name (bare, slash, or dotted form).  Looked up "
            "across the workspace's projects/ tree."
        ),
    )
    install_libraries_parser.add_argument(
        "--backend",
        choices=("pip", "mip"),
        default="pip",
        help=(
            "Acquisition backend.  pip (default) runs `pip install "
            "--target`; mip runs `mpremote mip install --target` "
            "against the bundle repo for packages not on PyPI.  Both "
            "write the host-local cache only — never a board."
        ),
    )
    install_libraries_parser.add_argument(
        "--experimental",
        action="store_true",
        help=(
            "mip backend only: fetch from ChuMicro-Bundle-Experimental "
            "instead of ChuMicro-Bundle (stable, default).  No effect "
            "with the pip backend."
        ),
    )
    install_libraries_parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Print the fetch commands without executing them and "
            "without touching library_sources.  Useful for air-gapped "
            "hosts or reviewing what gets fetched."
        ),
    )
    install_libraries_parser.set_defaults(func=_cmd_install_libraries)
