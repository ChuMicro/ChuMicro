"""``chumicro-workspace library`` subcommands: curated library host.

``list`` / ``add`` / ``update`` / ``remove`` / ``forget`` /
``switch-channel`` pull chumicro libraries from a published snapshot
channel into the workspace's ``libraries/`` folder and maintain the
``libraries:`` table in ``workspace.yml``.  ``remove`` uninstalls but
keeps the row as ``declined: true`` (so ``update`` skips it and the
decision is auditable).  ``forget`` drops the row entirely.  The heavy
lifting (snapshot resolve, extract, dep walk) lives in
:mod:`chumicro_workspace.library`.  This module is the parser plus
the prompt/IO surface.

Interactivity follows the workspace convention: default to
``sys.stdin.isatty()``, with ``--non-interactive`` as the explicit
override.  Non-interactive runs never prompt.  ``add`` keeps the full
transitive set and the rest are prompt-free by nature.  Exit codes:
0 success, 1 a fetch/operation failed, 2 a usage error (unknown
library, bad channel, conflicting flags).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from chumicro_workspace.cli._common import (
    _add_non_interactive_arg,
    _add_workspace_arg,
    _resolve_workspace,
)
from chumicro_workspace.cli.library_browser import (
    BrowserModel,
    run_library_browser,
)
from chumicro_workspace.curated_libraries import (
    DEFAULT_CHANNEL,
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
    is_locally_held,
    read_installed_version,
    remove_library,
)
from chumicro_workspace.library_channel import (
    fetch_text_file,
    resolve_snapshot,
)
from chumicro_workspace.pyright_extra_paths import (
    PYRIGHT_CONFIG_FILENAME,
    InvalidPyrightConfigError,
    add_library_extra_paths,
    remove_library_extra_paths,
)
from chumicro_workspace.workspace import WorkspaceLayout

_PYRIGHT_INVALID_WARNING = (
    f"warning: {PYRIGHT_CONFIG_FILENAME} is not valid JSON; skipped "
    "extraPaths update (fix it so editor imports resolve)."
)


def _maintain_pyright_paths_added(
    workspace_root: Path, names: list[str],
) -> None:
    """Register acquired libraries' source dirs in ``pyrightconfig.json``.

    Prints a one-line note when the file changed.  A ``pyrightconfig.json``
    that exists but cannot be parsed prints a coached warning and is left
    untouched, so a broken config never fails the acquisition.

    Args:
        workspace_root: Workspace root holding ``pyrightconfig.json``.
        names: Import names of the libraries acquired on disk.
    """
    try:
        added = add_library_extra_paths(workspace_root, names)
    except InvalidPyrightConfigError:
        print(_PYRIGHT_INVALID_WARNING)
        return
    if added:
        print(
            f"Updated {PYRIGHT_CONFIG_FILENAME} "
            f"(added {', '.join(added)}); commit it alongside the "
            "acquired libraries/ trees.",
        )


def _maintain_pyright_paths_removed(
    workspace_root: Path, name: str,
) -> None:
    """Drop an uninstalled library's source dir from ``pyrightconfig.json``.

    Prints a one-line note when the file changed.  A ``pyrightconfig.json``
    that exists but cannot be parsed prints a coached warning and is left
    untouched, so a broken config never fails the uninstall.

    Args:
        workspace_root: Workspace root holding ``pyrightconfig.json``.
        name: Import name of the library being uninstalled.
    """
    try:
        removed = remove_library_extra_paths(workspace_root, [name])
    except InvalidPyrightConfigError:
        print(_PYRIGHT_INVALID_WARNING)
        return
    if removed:
        print(
            f"Updated {PYRIGHT_CONFIG_FILENAME} "
            f"(dropped {', '.join(removed)}).",
        )


def _interactive(args: argparse.Namespace) -> bool:
    """True when prompts are allowed (a TTY and not --non-interactive)."""
    return sys.stdin.isatty() and not args.non_interactive


def _confirm(question: str) -> bool:
    """Y/n prompt defaulting to yes."""
    answer = input(f"{question} [Y/n] ").strip().lower()
    return answer in ("", "y", "yes")


def _print_install_summary(
    workspace_root: Path,
    channel: str,
    primary: str,
    closure: list[str],
    declined: set[str],
) -> None:
    """Print one line per library in *closure* with its version + channel.

    *primary* (what the user asked for) prints as the headline.  The
    rest of *closure* came along through ``[project].dependencies`` and
    prints with a ``  + `` prefix.  Sentinel-held trees show their
    on-disk version with a ``(kept local edits: sentinel)`` marker so
    a closure member that kept the user's edits is distinguishable
    from one that tracked the channel.  Printing one line per library
    rather than a comma-joined list is what makes that distinction
    legible.
    """
    primary_version = read_installed_version(workspace_root, primary) or "?"
    print(f"Added {primary} v{primary_version} ({channel})")
    for name in closure:
        if name == primary:
            continue
        if name in declined:
            print(f"  + {name} (declined)")
            continue
        version = read_installed_version(workspace_root, name) or "?"
        if is_locally_held(workspace_root, name):
            print(f"  + {name} v{version} (kept local edits: sentinel)")
        else:
            print(f"  + {name} v{version}")


def _declined_transitive(
    transitive: list[str], args: argparse.Namespace,
) -> set[str]:
    """Per-dependency deselect prompt for the transitive set.

    Returns the deps the user declined.  Non-interactive (or an empty
    set) keeps everything (the agent-runnable default).  Interactive
    asks per dep so a user injecting a custom transport can drop just
    ``chumicro_sockets`` without losing the rest of the closure.
    """
    if not transitive or not _interactive(args):
        return set()
    print(
        f"{args.name} pulls transitive chumicro deps: "
        f"{', '.join(transitive)}",
    )
    return {dep for dep in transitive if not _confirm(f"  pull {dep}?")}


def _recorded_version(
    workspace_root: Path, package: str, *, floating: bool, pin: str | None,
) -> str:
    """Return the version string to record in ``workspace.yml``.

    Explicit *pin* wins; ``--floating`` records :data:`HEAD`; otherwise
    the concrete version that landed on disk (or ``HEAD`` when the
    library has no ``VERSION`` file yet).
    """
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
        if on_disk and is_locally_held(workspace.root, name):
            flags.append("local")
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
            http_get=args._env.http_get,
        )
    except LibraryFetchError as error:
        print(
            f"library add: {error} (kind: {error.kind.value})",
            file=sys.stderr,
        )
        return 1

    declined = _declined_transitive(closure[1:], args)

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

    _print_install_summary(
        workspace.root, args.channel, args.name, closure, declined,
    )
    _maintain_pyright_paths_added(
        workspace.root, [name for name in closure if name not in declined],
    )
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
                http_get=args._env.http_get,
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


def _dependents_of(
    workspace: WorkspaceLayout,
    table: dict[str, CuratedLibrary],
    name: str,
) -> list[str]:
    """Curated, non-declined libraries whose pyproject still needs *name*."""
    return sorted(
        other
        for other, entry in table.items()
        if other != name and not entry.declined
        and name in chumicro_dependencies(
            workspace.root / "libraries" / other / "pyproject.toml",
        )
    )


def _confirm_dependents_block(
    workspace: WorkspaceLayout,
    table: dict[str, CuratedLibrary],
    name: str,
    args: argparse.Namespace,
    *,
    action_label: str,
) -> bool:
    """Warn when *name* still has dependents; return whether to proceed.

    *action_label* fills the verb in the confirm prompt ("Remove anyway?"
    / "Forget anyway?").  No dependents → True; non-interactive →
    warning printed but True; interactive abort → False.
    """
    dependents = _dependents_of(workspace, table, name)
    if not dependents:
        return True
    verb = "depends" if len(dependents) == 1 else "depend"
    pronoun = "its" if len(dependents) == 1 else "their"
    print(
        f"warning: {', '.join(dependents)} still {verb} on "
        f"{name}; {pronoun} deploy will fail without it.",
    )
    if _interactive(args) and not _confirm(f"{action_label} anyway?"):
        print("Aborted.")
        return False
    return True


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

    if not _confirm_dependents_block(
        workspace, table, args.name, args, action_label="Remove",
    ):
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
    _maintain_pyright_paths_removed(workspace.root, args.name)
    return 0


def _cmd_library_forget(args: argparse.Namespace) -> int:
    """Delete a library's row entirely (and uninstall it if present)."""
    workspace = _resolve_workspace(args)
    table = read_curated_libraries(workspace.workspace_yaml)
    if args.name not in table:
        print(f"library forget: not curated: {args.name}", file=sys.stderr)
        return 2

    if not _confirm_dependents_block(
        workspace, table, args.name, args, action_label="Forget",
    ):
        return 0

    remove_library(workspace.root, args.name)
    del table[args.name]
    write_curated_libraries(workspace.workspace_yaml, table)
    print(f"Forgot {args.name} (record removed).")
    _maintain_pyright_paths_removed(workspace.root, args.name)
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
            "(declined: nothing fetched).",
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
            http_get=args._env.http_get,
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


def _apply_selected(
    workspace: WorkspaceLayout,
    channel: str,
    roots: list[str],
    http_get: Callable[[str], bytes],
) -> int:
    """Fetch each chosen root's closure and record it; the browser's tail.

    Pulls the full transitive closure for each root without the
    pin/floating/decline prompts: the browser already gave the user
    library-level selection control, so the closure is pulled
    wholesale.  A fetch failure persists the libraries recorded so
    far (caller decides whether to retry) and returns 1.
    """
    table = read_curated_libraries(workspace.workspace_yaml)
    closures: list[tuple[str, list[str]]] = []
    for root in roots:
        try:
            closure = fetch_closure(
                root,
                channel=channel,
                version=HEAD,
                workspace_root=workspace.root,
                http_get=http_get,
            )
        except LibraryFetchError as error:
            write_curated_libraries(workspace.workspace_yaml, table)
            print(
                f"library browse: {error} (kind: {error.kind.value})",
                file=sys.stderr,
            )
            return 1
        for name in closure:
            version = _recorded_version(
                workspace.root, name, floating=False, pin=None,
            )
            table[name] = CuratedLibrary(name, channel, version)
        closures.append((root, closure))
    write_curated_libraries(workspace.workspace_yaml, table)
    if not closures:
        print("Nothing selected.")
        return 0
    for root, closure in closures:
        _print_install_summary(
            workspace.root, channel, root, closure, declined=set(),
        )
    _maintain_pyright_paths_added(
        workspace.root,
        sorted({name for _, closure in closures for name in closure}),
    )
    return 0


def _run_browse(args: argparse.Namespace) -> int:  # pragma: no cover
    """Build the model, run the full-screen browser, apply the result.

    No coverage: the prompt_toolkit shell needs a real terminal (the
    device-adapter convention).  The model and :func:`_apply_selected`
    are tested directly.
    """
    workspace = _resolve_workspace(args)
    http_get = args._env.http_get
    model = BrowserModel(
        channel=args.channel,
        resolve_snapshot=lambda channel: resolve_snapshot(
            channel, http_get=http_get,
        ),
        fetch_text=lambda channel, tag, path: fetch_text_file(
            channel, tag, path, http_get=http_get,
        ),
    )
    chosen = run_library_browser(model)
    if not chosen:
        print("Nothing added.")
        return 0
    return _apply_selected(workspace, model.channel, chosen, http_get)


def _cmd_library_browse(args: argparse.Namespace) -> int:
    """Interactive catalog browser, the TTY twin of ``library add``."""
    if not sys.stdin.isatty():
        print(
            "library browse is interactive and needs a TTY; use "
            "'library add <name> [--channel ...]' for scripted/agent use.",
            file=sys.stderr,
        )
        return 2
    return _run_browse(args)


def _add_library_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register the ``library`` command group."""
    library_parser = subparsers.add_parser(
        "library",
        help="Curate chumicro libraries into the workspace from a channel.",
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

    browse_parser = verbs.add_parser(
        "browse",
        help="Interactive catalog browser (TTY only; scripted? use 'add').",
    )
    browse_parser.add_argument(
        "--channel", choices=VALID_CHANNELS, default=DEFAULT_CHANNEL,
        help=f"Channel to open on (Tab toggles in-app; default: {DEFAULT_CHANNEL}).",
    )
    _add_workspace_arg(browse_parser)
    browse_parser.set_defaults(func=_cmd_library_browse)

    add_parser = verbs.add_parser(
        "add", help="Fetch a library + its chumicro deps from a snapshot.",
    )
    add_parser.add_argument("name", help="Import name, e.g. chumicro_mqtt.")
    add_parser.add_argument(
        "--channel", choices=VALID_CHANNELS, default=DEFAULT_CHANNEL,
        help=f"Release channel (default: {DEFAULT_CHANNEL}).",
    )
    add_parser.add_argument(
        "--version", default=None,
        help="Pin to this channel snapshot tag (default: latest snapshot).",
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
