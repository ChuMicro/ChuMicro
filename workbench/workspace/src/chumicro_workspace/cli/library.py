"""``chumicro-workspace library`` subcommands — curated library host.

``list`` / ``add`` / ``update`` / ``remove`` / ``forget`` /
``switch-channel`` pull chumicro libraries from PyPI into the
workspace's ``libraries/`` folder and maintain the ``libraries:``
table in ``workspace.yml``.  ``remove`` uninstalls but keeps the row
as ``declined: true`` (so ``update`` skips it and the decision is
auditable); ``forget`` drops the row entirely.  The heavy
lifting (fetch, sdist unpack, dep walk) lives in
:mod:`chumicro_workspace.library`; this module is the parser + the
prompt/IO surface.

Interactivity follows the workspace convention: default to
``sys.stdin.isatty()``, with ``--non-interactive`` as the explicit
override.  Non-interactive runs never prompt — ``add`` keeps the full
transitive set and the rest are prompt-free by nature.  Exit codes:
0 success, 1 a fetch/operation failed, 2 a usage error (unknown
library, bad channel, conflicting flags).
"""

from __future__ import annotations

import argparse
import sys

from chumicro_workspace.cli._common import (
    _add_non_interactive_arg,
    _add_workspace_arg,
    _resolve_workspace,
)
from chumicro_workspace.curated_libraries import (
    HEAD,
    VALID_CHANNELS,
    CuratedLibrary,
    read_curated_libraries,
    write_curated_libraries,
)
from chumicro_workspace.dep_resolver import chumicro_dependencies
from chumicro_workspace.library import (
    LibraryFetchError,
    fetch_closure,
    fetch_library,
    read_installed_version,
    remove_library,
)


def _interactive(args: argparse.Namespace) -> bool:
    """True when prompts are allowed (a TTY and not --non-interactive)."""
    return sys.stdin.isatty() and not args.non_interactive


def _confirm(question: str) -> bool:
    """Y/n prompt defaulting to yes."""
    answer = input(f"{question} [Y/n] ").strip().lower()
    return answer in ("", "y", "yes")


def _recorded_version(
    workspace_root, package: str, *, floating: bool, pin: str | None,
) -> str:
    """The version string to store: explicit pin, HEAD if floating, else
    the concrete version that landed on disk."""
    if pin is not None:
        return pin
    if floating:
        return HEAD
    return read_installed_version(workspace_root, package) or HEAD


def _cmd_library_list(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
    table = read_curated_libraries(workspace.workspace_yaml)
    if not table:
        print("No curated libraries.  Add one with 'library add <name>'.")
        return 0
    for name in sorted(table):
        entry = table[name]
        on_disk = (workspace.root / "libraries" / name).is_dir()
        flags = []
        if entry.declined:
            flags.append("declined")
        if not on_disk and not entry.declined:
            flags.append("missing-on-disk")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(
            f"{name}  {entry.channel}  {entry.version}{suffix}",
        )
    return 0


def _cmd_library_add(args: argparse.Namespace) -> int:
    if args.version is not None and args.floating:
        print(
            "library add: --version and --floating are mutually exclusive.",
            file=sys.stderr,
        )
        return 2
    workspace = _resolve_workspace(args)
    root_version = args.version if args.version is not None else HEAD

    try:
        closure = fetch_closure(
            args.name,
            channel=args.channel,
            version=root_version,
            workspace_root=workspace.root,
            subprocess_runner=args._env.subprocess_runner,
        )
    except LibraryFetchError as error:
        print(
            f"library add: {error} (kind: {error.kind.value})",
            file=sys.stderr,
        )
        return 1

    transitive = closure[1:]
    declined: set[str] = set()
    if transitive and _interactive(args) and not _confirm(
        f"Also pull transitive deps: {', '.join(transitive)}?",
    ):
        declined = set(transitive)

    table = read_curated_libraries(workspace.workspace_yaml)
    for name in closure:
        version = _recorded_version(
            workspace.root, name,
            floating=args.floating and name == args.name,
            pin=args.version if name == args.name else None,
        )
        if name in declined:
            remove_library(workspace.root, name)
            table[name] = CuratedLibrary(
                name, args.channel, version, declined=True,
            )
        else:
            table[name] = CuratedLibrary(name, args.channel, version)
    write_curated_libraries(workspace.workspace_yaml, table)

    kept = [pkg for pkg in closure if pkg not in declined]
    print(f"Added {', '.join(kept)} ({args.channel}).")
    if declined:
        print(f"Declined: {', '.join(sorted(declined))}.")
    return 0


def _cmd_library_update(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
    table = read_curated_libraries(workspace.workspace_yaml)
    targets = [args.name] if args.name else sorted(table)

    unknown = [name for name in targets if name not in table]
    if unknown:
        print(
            f"library update: not curated: {', '.join(unknown)}",
            file=sys.stderr,
        )
        return 2

    updated: list[str] = []
    for name in targets:
        entry = table[name]
        if entry.declined:
            continue
        if entry.version != HEAD:
            print(f"{name}: pinned to {entry.version}; skipping.")
            continue
        try:
            fetch_library(
                name,
                channel=entry.channel,
                version=HEAD,
                workspace_root=workspace.root,
                subprocess_runner=args._env.subprocess_runner,
            )
        except LibraryFetchError as error:
            print(
                f"library update: {name}: {error} "
                f"(kind: {error.kind.value})",
                file=sys.stderr,
            )
            return 1
        updated.append(name)
    print(
        f"Updated (floating): {', '.join(updated)}."
        if updated
        else "Nothing to update (all pinned or declined).",
    )
    return 0


def _dependents_of(workspace, table, name: str) -> list[str]:
    """Curated, non-declined libraries whose pyproject still needs *name*."""
    return sorted(
        other
        for other, entry in table.items()
        if other != name and not entry.declined
        and name in chumicro_dependencies(
            workspace.root / "libraries" / other / "pyproject.toml",
        )
    )


def _cmd_library_remove(args: argparse.Namespace) -> int:
    """Uninstall a library but keep its row as ``declined: true``.

    The row is retained so ``update`` skips it and the decision is
    auditable; ``library forget`` drops the row entirely.
    """
    workspace = _resolve_workspace(args)
    table = read_curated_libraries(workspace.workspace_yaml)
    if args.name not in table:
        print(f"library remove: not curated: {args.name}", file=sys.stderr)
        return 2

    dependents = _dependents_of(workspace, table, args.name)
    if dependents:
        print(
            f"warning: {', '.join(dependents)} still depend on "
            f"{args.name}; their deploy will fail without it.",
        )
        if _interactive(args) and not _confirm("Remove anyway?"):
            print("Aborted.")
            return 0

    remove_library(workspace.root, args.name)
    entry = table[args.name]
    table[args.name] = CuratedLibrary(
        args.name, entry.channel, entry.version, declined=True,
    )
    write_curated_libraries(workspace.workspace_yaml, table)
    print(
        f"Removed {args.name}; kept in workspace.yml as declined "
        f"(use 'library forget {args.name}' to drop the record).",
    )
    return 0


def _cmd_library_forget(args: argparse.Namespace) -> int:
    """Delete a library's row entirely (and uninstall it if present)."""
    workspace = _resolve_workspace(args)
    table = read_curated_libraries(workspace.workspace_yaml)
    if args.name not in table:
        print(f"library forget: not curated: {args.name}", file=sys.stderr)
        return 2

    dependents = _dependents_of(workspace, table, args.name)
    if dependents:
        print(
            f"warning: {', '.join(dependents)} still depend on "
            f"{args.name}; their deploy will fail without it.",
        )
        if _interactive(args) and not _confirm("Forget anyway?"):
            print("Aborted.")
            return 0

    remove_library(workspace.root, args.name)
    del table[args.name]
    write_curated_libraries(workspace.workspace_yaml, table)
    print(f"Forgot {args.name} (record removed).")
    return 0


def _cmd_library_switch_channel(args: argparse.Namespace) -> int:
    workspace = _resolve_workspace(args)
    table = read_curated_libraries(workspace.workspace_yaml)
    if args.name not in table:
        print(
            f"library switch-channel: not curated: {args.name}",
            file=sys.stderr,
        )
        return 2
    if args.channel not in VALID_CHANNELS:
        print(
            f"library switch-channel: bad channel {args.channel!r} "
            f"(expected {' or '.join(VALID_CHANNELS)})",
            file=sys.stderr,
        )
        return 2

    entry = table[args.name]
    if entry.channel == args.channel:
        print(f"{args.name} is already on {args.channel}.")
        return 0

    if entry.declined:
        table[args.name] = CuratedLibrary(
            args.name, args.channel, entry.version, declined=True,
        )
        write_curated_libraries(workspace.workspace_yaml, table)
        print(
            f"{args.name}: recorded channel {args.channel} "
            "(declined — nothing fetched).",
        )
        return 0

    pyproject = workspace.root / "libraries" / args.name / "pyproject.toml"
    deps_before = chumicro_dependencies(pyproject)
    floating = entry.version == HEAD
    try:
        fetch_library(
            args.name,
            channel=args.channel,
            version=HEAD,
            workspace_root=workspace.root,
            subprocess_runner=args._env.subprocess_runner,
        )
    except LibraryFetchError as error:
        print(
            f"library switch-channel: {error} (kind: {error.kind.value})",
            file=sys.stderr,
        )
        return 1
    new_version = (
        HEAD if floating
        else read_installed_version(workspace.root, args.name) or HEAD
    )
    table[args.name] = CuratedLibrary(args.name, args.channel, new_version)
    write_curated_libraries(workspace.workspace_yaml, table)
    print(f"{args.name}: switched to {args.channel} ({new_version}).")

    if chumicro_dependencies(pyproject) != deps_before:
        print(
            "note: the dependency set changed on this channel; "
            "run 'library update' to reconcile transitive deps.",
        )
    return 0


def _add_library_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``library`` command group."""
    library_parser = subparsers.add_parser(
        "library",
        help="Curate chumicro libraries into the workspace from PyPI.",
    )
    verbs = library_parser.add_subparsers(
        dest="library_command", required=True,
    )

    list_parser = verbs.add_parser(
        "list", help="Show curated libraries (channel, version, state).",
    )
    _add_workspace_arg(list_parser)
    _add_non_interactive_arg(list_parser)
    list_parser.set_defaults(func=_cmd_library_list)

    add_parser = verbs.add_parser(
        "add", help="Fetch a library + its chumicro deps from PyPI.",
    )
    add_parser.add_argument("name", help="Import name, e.g. chumicro_mqtt.")
    add_parser.add_argument(
        "--channel", choices=VALID_CHANNELS, default="stable",
        help="PyPI channel (default: stable).",
    )
    add_parser.add_argument(
        "--version", default=None,
        help="Pin the root library to this version (default: latest).",
    )
    add_parser.add_argument(
        "--floating", action="store_true",
        help="Track the channel's latest (records version: HEAD).",
    )
    _add_workspace_arg(add_parser)
    _add_non_interactive_arg(add_parser)
    add_parser.set_defaults(func=_cmd_library_add)

    update_parser = verbs.add_parser(
        "update", help="Re-fetch floating libraries (pinned ones skip).",
    )
    update_parser.add_argument(
        "name", nargs="?", default=None,
        help="Library to update (default: all curated).",
    )
    _add_workspace_arg(update_parser)
    _add_non_interactive_arg(update_parser)
    update_parser.set_defaults(func=_cmd_library_update)

    remove_parser = verbs.add_parser(
        "remove",
        help="Uninstall a library; keep its row as declined (audit trail).",
    )
    remove_parser.add_argument("name", help="Library to remove.")
    _add_workspace_arg(remove_parser)
    _add_non_interactive_arg(remove_parser)
    remove_parser.set_defaults(func=_cmd_library_remove)

    forget_parser = verbs.add_parser(
        "forget",
        help="Drop a library's record entirely (uninstalls if present).",
    )
    forget_parser.add_argument("name", help="Library to forget.")
    _add_workspace_arg(forget_parser)
    _add_non_interactive_arg(forget_parser)
    forget_parser.set_defaults(func=_cmd_library_forget)

    switch_parser = verbs.add_parser(
        "switch-channel", help="Move a library between stable/experimental.",
    )
    switch_parser.add_argument("name", help="Library to switch.")
    switch_parser.add_argument(
        "channel", choices=VALID_CHANNELS, help="Target channel.",
    )
    _add_workspace_arg(switch_parser)
    _add_non_interactive_arg(switch_parser)
    switch_parser.set_defaults(func=_cmd_library_switch_channel)
