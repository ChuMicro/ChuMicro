"""``dump-config`` and ``config-validate`` subcommands.

Read-only views over the deploy-time config-merge pipeline.
``dump-config`` prints what one project would receive; ``config-validate``
runs the same merge across every project (or a named subset) and
validates against the import-graph manifest union.
"""

from __future__ import annotations

import argparse
import json

from chumicro_workspace.cli._common import (
    _add_workspace_arg,
    _resolve_project_name,
    _resolve_workspace,
)
from chumicro_workspace.config_manifest import (
    ConfigManifestError,
    aggregate_manifests,
    find_library_roots,
    read_manifest,
    validate_runtime_config,
)
from chumicro_workspace.deploy_source import find_project_config
from chumicro_workspace.import_graph import build_search_paths
from chumicro_workspace.pipeline import compose_runtime_config


def _cmd_dump_config(args: argparse.Namespace) -> int:
    """Print the merged runtime config a project would receive on deploy.

    Runs the deploy-time pipeline up to (but not through) the msgpack
    write, deep-merging ``secrets.toml`` defaults with
    ``project_config.toml``, then pretty-prints the result so users can
    see what their on-device ``chumicro_config.runtime`` will read
    without deploying.

    Useful for: debugging which layer a key landed in after the merge,
    inspecting the shape before adding consumers on the device,
    confirming that gitignored credential overrides flowed through.

    Output format defaults to JSON (sorted keys, indent 2) for
    diffability.  ``--repr`` switches to ``repr()`` for cases where
    the raw Python types matter (e.g. seeing ``bytes`` vs ``str``).
    """
    workspace = _resolve_workspace(args)
    project_dir = workspace.project_dir(_resolve_project_name(workspace, args.project))
    if not project_dir.is_dir():
        raise SystemExit(f"error: project {project_dir} not found")

    try:
        project_config_path = find_project_config(project_dir)
    except FileNotFoundError:
        project_config_path = None

    resolved = compose_runtime_config(
        secrets_toml=workspace.secrets_toml,
        project_config=project_config_path,
    )

    if args.repr:
        print(repr(resolved))
    else:
        print(json.dumps(resolved, indent=2, sort_keys=True, default=repr))
    return 0


def _cmd_config_validate(args: argparse.Namespace) -> int:
    """Validate the merged runtime config for one or more projects.

    Runs ``compose_runtime_config`` against each named project (or all
    projects when none are named), unions the manifests of every
    library reachable from the import graph, and validates the merged
    flat dict against that union.

    Exits 0 when every project validates; exits 1 with a per-project
    summary when any fail.  Designed for CI: a fast pre-deploy gate
    that surfaces missing required keys with the exact dotted name
    the runtime accessor will request.
    """
    workspace = _resolve_workspace(args)
    project_names = (
        list(args.projects) if args.projects else workspace.list_projects()
    )
    if not project_names:
        print(
            "config-validate: no projects under "
            f"{workspace.projects_dir}; nothing to validate.",
        )
        return 0

    search_paths = list(build_search_paths(workspace))
    library_roots = find_library_roots(search_paths)
    union = aggregate_manifests(read_manifest(root) for root in library_roots)
    if union is None:
        print(
            "config-validate: no library declares a "
            "[tool.chumicro.config] manifest; nothing to validate against.",
        )
        return 0

    failed: list[tuple[str, str]] = []
    passed: list[str] = []
    for raw_name in project_names:
        project_name = _resolve_project_name(workspace, raw_name)
        project_dir = workspace.project_dir(project_name)
        if not project_dir.is_dir():
            failed.append((project_name, f"project directory not found: {project_dir}"))
            continue
        try:
            project_config_path = find_project_config(project_dir)
        except FileNotFoundError:
            project_config_path = None
        try:
            resolved = compose_runtime_config(
                secrets_toml=workspace.secrets_toml,
                project_config=project_config_path,
            )
            validate_runtime_config(resolved, union)
        except ConfigManifestError as error:
            failed.append((project_name, str(error)))
            continue
        except FileNotFoundError as error:
            failed.append((project_name, f"config source missing: {error}"))
            continue
        passed.append(project_name)

    for name in passed:
        print(f"config-validate: OK {name}")
    for name, message in failed:
        print(f"config-validate: FAIL {name}")
        for line in message.splitlines():
            print(f"  {line}")
    return 1 if failed else 0


def _add_config_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register ``dump-config`` / ``config-validate``."""
    dump_config_parser = subparsers.add_parser(
        "dump-config",
        help=(
            "Print the merged runtime config a project would receive on "
            "deploy (secrets.toml defaults + project_config.toml "
            "deep-merged), without actually deploying."
        ),
    )
    _add_workspace_arg(dump_config_parser)
    dump_config_parser.add_argument(
        "project",
        help="Project name (bare / slash / dotted).",
    )
    dump_config_parser.add_argument(
        "--repr",
        action="store_true",
        help=(
            "Use repr() instead of JSON for the dump.  Useful when the "
            "raw Python types matter (e.g. distinguishing bytes vs str)."
        ),
    )
    dump_config_parser.set_defaults(func=_cmd_dump_config)

    config_validate_parser = subparsers.add_parser(
        "config-validate",
        help=(
            "Validate the merged runtime config for one or more projects "
            "against the union manifest of every library reachable from "
            "the import graph.  Exits 1 on any failure; designed as a "
            "fast pre-deploy / CI gate."
        ),
    )
    _add_workspace_arg(config_validate_parser)
    config_validate_parser.add_argument(
        "projects",
        nargs="*",
        help=(
            "Project names to validate (bare / slash / dotted).  When "
            "omitted, every project under projects/ is validated."
        ),
    )
    config_validate_parser.set_defaults(func=_cmd_config_validate)
