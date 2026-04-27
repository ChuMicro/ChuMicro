"""``chumicro-workspace`` command dispatch.

Thin wrapper over the public ``chumicro_workspace`` /
``chumicro_deploy`` / ``chumicro_repl`` APIs.  Workspace template
repos vendor a tiny ``run.py`` shim that simply calls
:func:`main`; every command the workspace user invokes
(``python run.py deploy back-porch``, ``python run.py repl``, etc.)
routes through this dispatcher.

The full command set is documented in
``plans/workstreams/project-workspace.md`` Phase 4a.  Commands are
shipped at three depths:

* **Implemented** — full behaviour wired to the underlying library
  (``deploy``, ``probe``, ``devices``, ``repl``, ``new``,
  ``install-firmware`` / ``upgrade-firmware``, ``discover``,
  ``test``, ``setup``).
* **Stubbed for a planned slice** — registered with help text and a
  clear "implemented in Slice X" error so the dispatcher contract is
  stable before the implementation lands (``add-device``, ``rename``,
  ``sim``, ``env``, ``use``, ``sync``, ``upgrade``).

Stubs raise :exc:`NotImplementedError` carrying a one-line pointer to
the slice or workstream phase that will land them.  CLI invocation
catches the exception and exits 2 with a descriptive message — the
test suite asserts on that exit code so the rollout sequence stays
visible.
"""

from __future__ import annotations

import argparse
import keyword
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from chumicro_workspace.boot_shim import thing_boot_source
from chumicro_workspace.deploy_source import thing_directory_source
from chumicro_workspace.devices_yaml import (
    DeviceAlreadyExistsError,
    DeviceNotFoundError,
    HardwareOverwriteError,
    add_device,
    dump_devices,
    find_device,
    load_devices,
    rename_device,
    update_device_address,
    update_device_firmware_version,
    update_device_hardware,
)
from chumicro_workspace.firmware_support import (
    FirmwareSupportStatus,
    check_firmware_supported,
)
from chumicro_workspace.firmware_support import (
    explain as explain_firmware_support,
)
from chumicro_workspace.firmware_url import (
    UnresolvableFirmwareError,
    derive_firmware_url,
)
from chumicro_workspace.health import (
    HealthFinding,
    HealthLevel,
    collect_health_findings,
)
from chumicro_workspace.import_graph import thing_import_graph_source
from chumicro_workspace.onboarding import (
    BoardState,
    detect_board_state,
    probe_with_runtime_inference,
)
from chumicro_workspace.workspace import (
    ThingClassification,
    WorkspaceLayout,
    WorkspaceNotFoundError,
)

if TYPE_CHECKING:  # pragma: no cover — type-only
    from chumicro_deploy import Device, DeviceImplementation


# ---------------------------------------------------------------------------
# Common argparse helpers
# ---------------------------------------------------------------------------


def _add_workspace_arg(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--workspace-dir`` flag.

    Defaults to walking up from the current working directory until a
    ``workspace.yml`` is found (mirrors ``git`` discovery).  Override
    when running multiple workspaces in parallel or when the user
    invokes the CLI from outside the tree (CI runners, IDE tasks).
    """
    parser.add_argument(
        "--workspace-dir",
        type=Path,
        default=None,
        help=(
            "Workspace root.  Defaults to walking up from the current "
            "directory until a workspace.yml is found."
        ),
    )


def _add_device_selector(parser: argparse.ArgumentParser) -> None:
    """Attach the shared ``--device`` / ``--runtime`` selectors.

    Resolved against ``<workspace>/devices.yml`` via
    :mod:`chumicro_deploy.config.default`.  Mutually-exclusive at
    runtime (the loader raises if both are passed alongside two
    runtime defaults).
    """
    parser.add_argument(
        "--device",
        dest="device_id",
        default=None,
        help="Pick a specific entry from devices.yml by id.",
    )
    parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help="Pick the default device for the named runtime.",
    )


def _resolve_workspace(args: argparse.Namespace) -> WorkspaceLayout:
    """Locate the workspace root for *args*.

    Wraps :class:`WorkspaceLayout.from_dir` so missing workspaces
    surface as a uniform ``SystemExit`` with a helpful message
    instead of a stack trace.
    """
    try:
        return WorkspaceLayout.from_dir(args.workspace_dir)
    except WorkspaceNotFoundError as exception:
        raise SystemExit(f"error: {exception}") from exception


def _find_devices_yml_entry_for_args(
    workspace: WorkspaceLayout,
    args: argparse.Namespace,
) -> Mapping[str, Any] | None:
    """Locate the raw ``devices.yml`` entry matching *args*' selectors.

    Mirrors :func:`chumicro_deploy.config.default.load_devices_yml`'s
    resolution order — explicit ``--device id`` wins outright, then
    ``--runtime`` picks ``defaults.<runtime>``, finally a single
    runtime default in the file picks itself.  Returns the matching
    raw dict (with comments + key order intact since it comes from
    :func:`load_devices`) or ``None`` when nothing matches.

    Distinct from :func:`_resolve_device` because the
    ``firmware_source`` / ``hardware`` fields aren't on the
    :class:`Device` dataclass — they live in the raw entry.
    """
    if not workspace.devices_yaml.is_file():
        return None
    data = load_devices(workspace.devices_yaml)
    if args.device_id is not None:
        return find_device(data, args.device_id)
    defaults = data.get("defaults") or {}
    runtime = getattr(args, "runtime", None)
    if runtime is not None:
        default_id = defaults.get(runtime)
        if default_id is not None:
            return find_device(data, default_id)
    candidates = [
        defaults.get("micropython"),
        defaults.get("circuitpython"),
    ]
    picks = [candidate for candidate in candidates if candidate]
    if len(picks) == 1:
        return find_device(data, picks[0])
    return None


def _resolve_device(workspace: WorkspaceLayout, args: argparse.Namespace) -> Device:
    """Construct a :class:`Device` for the selected entry in devices.yml."""
    if not workspace.devices_yaml.is_file():
        raise SystemExit(
            f"error: {workspace.devices_yaml} not found — run "
            "'add-device' to register a board first.",
        )
    from chumicro_deploy.config.default import load_devices_yml  # noqa: PLC0415

    return load_devices_yml(
        workspace.devices_yaml,
        device_id=args.device_id,
        runtime=args.runtime,
    )


# ---------------------------------------------------------------------------
# Implemented commands
# ---------------------------------------------------------------------------


def _cmd_setup(args: argparse.Namespace) -> int:
    """Install workspace dependencies and materialize template files.

    Runs ``pip install -e .`` in the workspace root when a
    ``pyproject.toml`` is present, then walks ``_templates/`` and
    creates any missing files at the workspace root (Decision 0038
    §5).  Idempotent — re-running is safe.
    """
    workspace = _resolve_workspace(args)
    pyproject = workspace.root / "pyproject.toml"
    if pyproject.is_file():
        print(f"setup: installing {workspace.root} (editable)")
        completed = subprocess.run(  # noqa: S603 — args fully controlled
            [sys.executable, "-m", "pip", "install", "-e", str(workspace.root)],
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode
    else:
        print(
            f"setup: no pyproject.toml at {workspace.root} — "
            "skipping editable install.",
        )
    from chumicro_workspace.template_apply import (  # noqa: PLC0415
        ApplyAction,
        materialize_templates,
    )

    report = materialize_templates(workspace.root)
    new_files = report.count(ApplyAction.MATERIALIZED)
    if new_files:
        print(f"setup: materialized {new_files} file(s) from _templates/")
        for path, action in report:
            if action == ApplyAction.MATERIALIZED:
                print(f"  {path}")
    return 0


def _cmd_init(args: argparse.Namespace) -> int:
    """Clone the workspace template into a target directory."""
    from chumicro_workspace.template_apply import (  # noqa: PLC0415
        DEFAULT_TEMPLATE_URL,
        ApplyAction,
        init,
    )

    template_url = args.template_url or DEFAULT_TEMPLATE_URL
    try:
        report = init(
            args.target,
            template_url=template_url,
            git_reference=args.git_reference,
            force=args.force,
        )
    except FileExistsError as error:
        print(f"init: {error}", file=sys.stderr)
        print(
            "Pass --force to clear the target directory and reclone.",
            file=sys.stderr,
        )
        return 1
    except RuntimeError as error:
        print(f"init: {error}", file=sys.stderr)
        return 2
    written = report.count(ApplyAction.WRITTEN)
    print(f"init: cloned {template_url} into {args.target} ({written} files)")
    print(f"next: cd {args.target} && python3 run.py setup")
    return 0


def _cmd_update(args: argparse.Namespace) -> int:
    """Re-flow tool-owned template files from the canonical upstream."""
    from chumicro_workspace.template_apply import (  # noqa: PLC0415
        DEFAULT_TEMPLATE_URL,
        ApplyAction,
    )
    from chumicro_workspace.template_apply import (
        update as apply_update,
    )

    workspace = _resolve_workspace(args)
    template_url = args.template_url or DEFAULT_TEMPLATE_URL
    try:
        report = apply_update(
            workspace.root,
            template_url=template_url,
            git_reference=args.git_reference,
        )
    except RuntimeError as error:
        print(f"update: {error}", file=sys.stderr)
        return 2
    refreshed = report.count(ApplyAction.REFRESHED)
    unchanged = report.count(ApplyAction.UNCHANGED)
    skipped = report.count(ApplyAction.SKIPPED)
    print(
        f"update: refreshed={refreshed} unchanged={unchanged} skipped={skipped}",
    )
    for path, action in report:
        print(f"  {action:>11}  {path}")
    return 0


def _validate_thing_name(name: str) -> None:
    """Reject thing names that won't survive ``import things.<name>.app``.

    Accepts three shapes: bare (``"bedroom_sensor"``), slash-form
    (``"upstairs/bedroom_sensor"``), and dotted
    (``"upstairs.bedroom_sensor"``).  Each path segment is validated
    independently — the on-device import path is
    ``things.<seg1>.<seg2>.app`` so every segment must be a valid
    Python identifier (no hyphens, leading digits, leading underscore,
    or Python keywords).

    Leading underscore is reserved at every level for
    workspace-internal directories such as ``_template`` /
    ``_generated``; the recursive thing classifier filters those out,
    so a user-created ``_foo/bar`` segment would be invisible to
    ``things``/``deploy``.
    """
    if not name:
        raise SystemExit("error: thing name must not be empty")
    segments = re.split(r"[/.]", name)
    for segment in segments:
        if not segment:
            raise SystemExit(
                f"error: thing name {name!r} has an empty path segment "
                "— check for stray '/' or '.' separators.",
            )
        if not segment.isidentifier():
            raise SystemExit(
                f"error: thing name segment {segment!r} (in {name!r}) "
                "is not a valid Python identifier — thing directories "
                "are imported as modules, so each segment must use "
                "snake_case (letters, digits, underscores; no hyphens "
                "or spaces; no leading digit).",
            )
        if segment.startswith("_"):
            raise SystemExit(
                f"error: thing name segment {segment!r} (in {name!r}) "
                "starts with '_' — leading underscore is reserved for "
                "workspace-internal directories (e.g. _template).",
            )
        if keyword.iskeyword(segment):
            raise SystemExit(
                f"error: thing name segment {segment!r} (in {name!r}) "
                "is a Python keyword.",
            )


_THING_ENTRY_POINT_FILENAMES: tuple[str, ...] = ("app.py", "code.py", "main.py")


def _ensure_namespace_parents(
    workspace: WorkspaceLayout, target: Path,
) -> list[Path]:
    """Create empty ``__init__.py``-marked namespace dirs above *target*.

    Returns the list of namespace dirs newly created so the caller can
    print a per-command trace line.  Pre-existing namespace dirs are
    reused silently.  Used by both ``new`` and ``rename`` so a thing
    moved into ``garage/sensors/`` lands with the same host-side
    namespace marker layout ``new`` would produce.
    """
    workspace.things_dir.mkdir(parents=True, exist_ok=True)
    parent = target.parent
    if parent == workspace.things_dir:
        return []
    created: list[Path] = []
    relative_parent = parent.relative_to(workspace.things_dir)
    for segment_count in range(1, len(relative_parent.parts) + 1):
        namespace_dir = workspace.things_dir.joinpath(
            *relative_parent.parts[:segment_count],
        )
        init_path = namespace_dir / "__init__.py"
        if not namespace_dir.exists():
            namespace_dir.mkdir(parents=True)
            created.append(namespace_dir)
        if not init_path.exists():
            init_path.write_text("")
    return created


def _resolve_new_source(
    workspace: WorkspaceLayout, from_path: str | None,
) -> Path:
    """Pick the directory ``new`` will copy into the target.

    Without ``--from``, returns ``things/_template/`` (same default as
    before Slice 3 added the flag).  With ``--from <path>``, resolves
    *path* relative to the workspace root and validates that the
    resulting directory exists and looks like a thing — i.e. has at
    least one of :data:`_THING_ENTRY_POINT_FILENAMES`.  An entry-point
    is the only way to confirm the source is a thing (vs. a
    namespace dir or a docs folder).
    """
    if from_path is None:
        template = workspace.things_dir / "_template"
        if not template.is_dir():
            raise SystemExit(
                f"error: template {template} not found — run "
                "`chumicro-workspace init` to clone the canonical "
                "template, or create `things/_template/` by hand.",
            )
        return template
    candidate = (workspace.root / from_path).resolve()
    # Defence against `--from ../../etc/passwd` shenanigans — keep the
    # source under the workspace root.
    try:
        candidate.relative_to(workspace.root.resolve())
    except ValueError as exception:
        raise SystemExit(
            f"error: --from path {from_path!r} resolves outside the "
            f"workspace root {workspace.root}.",
        ) from exception
    if not candidate.is_dir():
        raise SystemExit(
            f"error: --from source {candidate} is not a directory.",
        )
    has_entry_point = any(
        (candidate / filename).is_file()
        for filename in _THING_ENTRY_POINT_FILENAMES
    )
    if not has_entry_point:
        raise SystemExit(
            f"error: --from source {candidate} has no entry-point "
            "file (app.py / code.py / main.py) — pick a thing "
            "directory, not a namespace.",
        )
    return candidate


def _cmd_new(args: argparse.Namespace) -> int:
    """Create ``things/<path>/`` by copying a template or example tree.

    *path* may be bare (``"bedroom_sensor"``), slash-form
    (``"upstairs/bedroom_sensor"``), or dotted
    (``"upstairs.bedroom_sensor"``).  Intermediate namespace
    directories are auto-created with empty ``__init__.py`` markers
    so host-side tooling can ``import things.upstairs.bedroom_sensor.app``
    without surprises (the on-device boot shim emits its own
    namespace inits separately — Slice 2 boot_shim work).

    Each path segment is validated against the Python identifier
    grammar (Slice 1's ``_validate_thing_name``).

    With ``--from <path>`` the source tree is *path* (resolved
    relative to the workspace root and validated as a thing) instead
    of ``things/_template/``.  The workstream design note is explicit
    (Phase 4a §"Open questions"): ``new`` is a ``cp -r`` convenience,
    not a code generator — no template variables, no post-copy edits.
    """
    _validate_thing_name(args.name)
    workspace = _resolve_workspace(args)
    source = _resolve_new_source(workspace, args.from_path)
    target = workspace.thing_dir(args.name)
    if target.exists():
        raise SystemExit(f"error: {target} already exists")
    created_namespaces = _ensure_namespace_parents(workspace, target)
    for namespace_dir in created_namespaces:
        print(
            f"new: creating namespace "
            f"{namespace_dir.relative_to(workspace.root)}/",
        )
    shutil.copytree(source, target)
    print(f"new: created {target}")
    return 0


def _cmd_probe(args: argparse.Namespace) -> int:
    """Probe a board's runtime identity (delegates to chumicro-deploy)."""
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)
    from chumicro_deploy import probe_device  # noqa: PLC0415

    info = probe_device(device)
    if info.implementation is None:
        print("probe: no implementation marker", file=sys.stderr)
        return 1
    print(f"runtime: {info.implementation.name}")
    print(f"version: {info.implementation.version}")
    print(f"machine: {info.implementation.machine}")
    if info.uid:
        print(f"uid: {info.uid}")
    return 0


def _cmd_discover(args: argparse.Namespace) -> int:
    """List serial ports the host can see (pyserial-backed)."""
    # pyserial ships as a chumicro-deploy dep so it's always present.
    from serial.tools import list_ports  # noqa: PLC0415

    ports = sorted(list_ports.comports(), key=lambda port: port.device)
    if not ports:
        print("discover: no serial ports detected")
        return 0
    for port in ports:
        description = port.description or "(no description)"
        print(f"{port.device}\t{description}")
    return 0


def _cmd_devices(args: argparse.Namespace) -> int:
    """Print the entries in ``devices.yml`` (one per line)."""
    workspace = _resolve_workspace(args)
    if not workspace.devices_yaml.is_file():
        print(f"devices: {workspace.devices_yaml} does not exist yet")
        return 0
    import yaml  # noqa: PLC0415

    raw = yaml.safe_load(workspace.devices_yaml.read_text()) or {}
    devices = raw.get("devices", [])
    if not devices:
        print("devices: no entries")
        return 0
    for entry in devices:
        identifier = entry.get("id", "?")
        runtime = entry.get("runtime", "?")
        address = entry.get("address", "?")
        print(f"{identifier}\t{runtime}\t{address}")
    return 0


def _resolve_thing_name(workspace: WorkspaceLayout, name: str) -> str:
    """Resolve a user-typed thing name to a canonical slash-form path.

    Accepts three shapes:

    * **Bare** (``"door_open"``) — looked up across the whole
      ``things/`` tree.  Unique match → that thing.  Multiple matches →
      ``SystemExit`` listing the candidates.  No match → caller's
      existence check surfaces the ``FileNotFoundError``-shaped
      message.
    * **Slash** (``"garage/sensors/door_open"``) — direct path.
    * **Dotted** (``"garage.sensors.door_open"``) — same as slash;
      normalised before return because ``/`` is the canonical form
      used by :meth:`WorkspaceLayout.list_things`.

    Slice 2 of the nested-things-and-examples plan; replaces the
    flat-only ``names = list(args.names)`` lookup that preceded it.
    """
    normalised = name.replace(".", "/")
    if "/" in normalised:
        return normalised
    candidates = [
        path for path in workspace.list_things()
        if path == name or path.endswith("/" + name)
    ]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        candidate_list = "\n".join(f"  {path}" for path in candidates)
        raise SystemExit(
            f"deploy: {name!r} is ambiguous — multiple things match:\n"
            f"{candidate_list}\n"
            f"specify the path: `python run.py deploy {candidates[0]}`",
        )
    # No match — let the caller's existence check produce the standard
    # "thing not found" message after constructing the dir path.
    return name


def _cmd_deploy(args: argparse.Namespace) -> int:
    """Deploy a thing to a device.

    Single-thing default uses :func:`thing_directory_source` — the
    flat layout where the thing's files land at the device root.
    ``--import-graph`` ships only transitively-imported modules.
    ``--boot-shim`` ships under ``/lib/things/<...>/<name>/``; combine
    with the workspace-runtime convention (``app.py`` exporting
    ``def run()``).

    Positional name accepts bare (``"door_open"``), slash
    (``"garage/sensors/door_open"``), or dotted forms; bare names that
    match more than one thing in the tree exit 2 with a list of
    candidates.

    When invoked with no positional name and the workspace contains
    exactly one thing, that thing is deployed by default — covers the
    "I only have one app" beginner case (Decision 0029).  Zero things
    or multiple things both require an explicit positional.

    Multi-thing deploys (``deploy <a> <b> <c>``) are not supported —
    Slice 7 of the nested-things-and-examples workstream retired the
    multi-thing-staging path; pass one positional per ``deploy`` call.
    """
    workspace = _resolve_workspace(args)
    if not args.names:
        candidates = workspace.list_things()
        if not candidates:
            print(
                "deploy: no things to deploy.  Create one with "
                "`new <name>` first.",
                file=sys.stderr,
            )
            return 2
        if len(candidates) > 1:
            print(
                "deploy: multiple things in workspace; specify which "
                f"to deploy ({', '.join(candidates)}).",
                file=sys.stderr,
            )
            return 2
        names = [candidates[0]]
        print(f"deploy: defaulting to {names[0]} (only thing in workspace).")
    else:
        if len(args.names) > 1:
            print(
                "deploy: multi-thing deploys are no longer supported — "
                "pass one positional name per `deploy` call.",
                file=sys.stderr,
            )
            return 2
        names = [_resolve_thing_name(workspace, args.names[0])]
    if args.import_graph and args.boot_shim:
        print(
            "deploy: --import-graph and --boot-shim are mutually exclusive.",
            file=sys.stderr,
        )
        return 2
    thing_dirs: list[Path] = []
    for name in names:
        thing_dir = workspace.thing_dir(name)
        if not thing_dir.is_dir():
            raise SystemExit(f"error: thing {thing_dir} not found")
        thing_dirs.append(thing_dir)
    device = _resolve_device(workspace, args)
    from chumicro_deploy import Deployer  # noqa: PLC0415

    if args.boot_shim:
        source = thing_boot_source(
            thing_dirs[0],
            workspace=workspace,
            thing_name=names[0],
            entrypoint_filename=device.effective_entrypoint,
        )
    elif args.import_graph:
        device_entrypoint = args.entrypoint or f"/{device.effective_entrypoint}"
        source = thing_import_graph_source(
            thing_dirs[0],
            workspace=workspace,
            entrypoint_filename=device.effective_entrypoint,
            device_entrypoint=device_entrypoint,
        )
    else:
        source = thing_directory_source(
            thing_dirs[0],
            workspace_yaml=workspace.workspace_yaml,
            secrets_yaml=workspace.secrets_yaml,
            entrypoint=args.entrypoint or f"/{device.effective_entrypoint}",
        )
    result = Deployer(device).deploy(source)
    if result.execute_output:
        print(result.execute_output, end="")
    if not result.success:
        if result.traceback:
            print(f"\n--- traceback ---\n{result.traceback}", file=sys.stderr)
        return 1
    return 0


def _render_things_tree(
    workspace: WorkspaceLayout,
) -> str:
    """Format the workspace's things as an indented Unicode tree.

    Empty workspace prints a friendly marker.  Otherwise:

    .. code-block:: text

        things/
        ├── thermostat
        ├── upstairs/
        │   ├── bedroom_sensor
        │   └── nightstand_lamp
        └── garage/
            ├── controls/
            │   └── heater
            └── sensors/
                └── door_open

    Driven by :meth:`WorkspaceLayout.iter_things_with_classification`
    so namespace dirs (``upstairs/``) always sit above their thing
    leaves, matching depth-first display order.
    """
    items = workspace.iter_things_with_classification()
    if not items:
        return "(no things in this workspace)"
    classification_by_path: dict[str, ThingClassification] = dict(items)
    # children["parent/path"] = sorted list of leaf segments.  Empty
    # string is the top level (children of `things/`).
    children: dict[str, list[str]] = {"": []}
    for path in classification_by_path:
        segments = path.split("/")
        for depth in range(len(segments)):
            parent_key = "/".join(segments[:depth])
            children.setdefault(parent_key, [])
            leaf = segments[depth]
            if depth == len(segments) - 1 and leaf not in children[parent_key]:
                children[parent_key].append(leaf)
    for kids in children.values():
        kids.sort()

    lines = ["things/"]

    def _walk(parent_path: str, prefix: str) -> None:
        kids = children.get(parent_path, [])
        for index, leaf in enumerate(kids):
            full_path = f"{parent_path}/{leaf}" if parent_path else leaf
            is_last = index == len(kids) - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "
            classification = classification_by_path[full_path]
            if classification is ThingClassification.NAMESPACE:
                lines.append(f"{prefix}{connector}{leaf}/")
                _walk(full_path, prefix + extension)
            else:
                lines.append(f"{prefix}{connector}{leaf}")

    _walk("", "")
    return "\n".join(lines)


def _cmd_things(args: argparse.Namespace) -> int:
    """List the things defined in the workspace under ``things/``.

    Two views: the default :func:`_render_things_tree` (Slice 4)
    draws an indented Unicode tree so namespaced workspaces are
    legible at a glance; ``--flat`` falls back to the legacy
    one-thing-per-line slash-form output (handy for shell pipelines
    and ``grep``-style filtering).

    Local-only: walks ``things/`` via
    :meth:`WorkspaceLayout.list_things` and
    :meth:`WorkspaceLayout.iter_things_with_classification`, both of
    which skip ``_template`` and leading ``.`` / ``_`` names.  An
    on-device variant that probes ``/lib/things/`` for installed
    payloads is a follow-on once the REPL one-shot pattern lands as
    a public helper.
    """
    workspace = _resolve_workspace(args)
    if args.flat:
        names = workspace.list_things()
        if not names:
            print("(no things in this workspace)")
            return 0
        for name in names:
            print(name)
        return 0
    print(_render_things_tree(workspace))
    return 0


#: Glyphs for ``status`` line prefixes.  Plain Unicode dingbats so
#: every reasonable terminal renders them; downstream consumers
#: that want strict ASCII can pipe through ``sed`` to remap.
_HEALTH_LEVEL_PREFIX: dict[HealthLevel, str] = {
    HealthLevel.OK: "✓",
    HealthLevel.WARN: "⚠",
    HealthLevel.ERROR: "✗",
}

#: Width of the label column in ``status`` output.  Picked so the
#: longest current label (``WORKSPACE.YML``) plus a 2-space gutter
#: lines up the prefix glyph at the same column for every row.
_STATUS_LABEL_WIDTH: int = 16


def _format_health_finding(finding: HealthFinding) -> str:
    """Return the one-line representation of *finding* for ``status``."""
    prefix = _HEALTH_LEVEL_PREFIX[finding.level]
    label = finding.label.ljust(_STATUS_LABEL_WIDTH)
    return f"{label}{prefix} {finding.message}"


def _cmd_status(args: argparse.Namespace) -> int:
    """Print a one-line-per-check workspace health snapshot.

    Each finding from :func:`collect_health_findings` renders as
    ``LABEL <glyph> message``; warning / error findings carry an
    optional hint that prints on the next line indented under the
    label column.  The exit code is non-zero only when at least one
    finding is at :attr:`HealthLevel.ERROR` — warnings (placeholder
    secrets, empty things tree) leave it at zero so ``status``
    composes cleanly with shell-pipe checks.

    Phase 2a of the workspace-ecosystem workstream.  ``doctor``
    (Phase 2b) is the stricter sibling that runs every check
    plus device-side probes and treats warnings as failures.
    """
    workspace = _resolve_workspace(args)
    print(f"WORKSPACE       {workspace.root}")
    findings = collect_health_findings(workspace)
    has_error = False
    for finding in findings:
        print(_format_health_finding(finding))
        if finding.hint and finding.level is not HealthLevel.OK:
            print(f"{' ' * _STATUS_LABEL_WIDTH}  hint: {finding.hint}")
        if finding.level is HealthLevel.ERROR:
            has_error = True
    return 1 if has_error else 0


#: Built-in demo payload — Step 5 of the beginner-onramp workstream.
#:
#: Cross-runtime safe (CircuitPython + MicroPython): only ``time.sleep``
#: + ``print``.  No hardware access — every supported board reaches the
#: print path identically, so the demo "just works" out-of-the-box on
#: any registered device without runtime-config or pin pickers.  Runs
#: for ~5 seconds and exits cleanly so the deploy command's
#: synchronous-execute path doesn't appear to hang.
DEMO_PAYLOAD: str = (
    "import time\n"
    "print('Hello from ChuMicro!')\n"
    "print('Your board is alive.')\n"
    "for index in range(5):\n"
    "    time.sleep(1)\n"
    "    print('  tick ' + str(index + 1) + '/5')\n"
    "print('demo complete!')\n"
)


def _cmd_demo(args: argparse.Namespace) -> int:
    """Deploy a baked-in LED-blink-shaped "hello world" to the active device.

    Step 5 of the beginner-onramp workstream — gives a user with a
    freshly-registered board something to ship on day one without
    having to write code, configure wifi, or pick a thing.  Runs
    synchronously: deploys the payload, captures execute output,
    prints it.  Total wall-clock ~5 seconds.

    The payload is a runtime-agnostic print loop (no ``board`` /
    ``machine`` imports) so the demo works on any supported runtime
    + board.  An LED-blink variant is a future enhancement once the
    LED-pin abstraction lands; see Decision 0029 for the workspace
    LED contract sketch.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)
    from chumicro_deploy import Deployer, FileMapSource  # noqa: PLC0415

    entrypoint_path = f"/{device.effective_entrypoint}"
    source = FileMapSource(
        files={entrypoint_path: DEMO_PAYLOAD},
        entrypoint=entrypoint_path,
    )
    print(
        f"demo: deploying built-in payload to "
        f"{device.transport} @ {device.address} ...",
    )
    result = Deployer(device).deploy(source)
    if result.execute_output:
        print(result.execute_output, end="")
    if not result.success:
        if result.traceback:
            print(f"\n--- traceback ---\n{result.traceback}", file=sys.stderr)
        return 1
    return 0


def _stdin_prompt(prompt_text: str) -> str:
    """Real-stdin prompt — tests inject a deterministic substitute.

    Sole indirection point for ``_cmd_bootstrap`` so the wizard's
    branching logic stays unit-testable without TTY plumbing.
    """
    return input(prompt_text)


def _suggest_device_id(implementation: DeviceImplementation) -> str:
    """Suggest a device id from the probed machine string.

    Strips non-identifier characters and lowercases — a Pi Pico W
    probing as ``"Raspberry Pi Pico W with rp2040"`` becomes
    ``"raspberry-pi-pico-w"``.  Falls back to the runtime name
    when ``machine`` is empty (older firmware) or sanitises to
    nothing.
    """
    machine = implementation.machine or ""
    # Trim the trailing " with rp2040" / " with esp32s2" tail
    # — common in CP machine strings, never present in the user's
    # natural mental id for the board.
    cleaned = re.sub(r"\s+with\s+\w+$", "", machine, flags=re.IGNORECASE)
    # Replace non-identifier runs with single hyphens, lowercase.
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", cleaned).strip("-").lower()
    return slug or implementation.name or "board"


def _resolve_bootstrap_port(
    explicit_port: str | None,
    *,
    prompt_func: Callable[[str], str] = _stdin_prompt,
) -> str | None:
    """Pick the port to onboard against.

    * ``explicit_port`` set → use it verbatim.
    * No ports detected → print a hint, return ``None`` (caller exits 1).
    * Exactly one port → use it without prompting.
    * Multiple ports → list them, prompt for a number.

    Args:
        explicit_port: ``--port`` flag value, or ``None`` to discover
            interactively.
        prompt_func: Indirection point for tests.  Defaults to
            ``_stdin_prompt``.

    Returns:
        The chosen port path, or ``None`` on no-discovery / invalid
        input.
    """
    if explicit_port:
        return explicit_port
    from serial.tools import list_ports as _list_ports  # noqa: PLC0415

    ports = sorted(_list_ports.comports(), key=lambda port: port.device)
    if not ports:
        print(
            "bootstrap: no serial ports detected.  "
            "Plug in a board and try again.",
            file=sys.stderr,
        )
        return None
    if len(ports) == 1:
        only_port = ports[0]
        print(f"bootstrap: only one port found — using {only_port.device}.")
        return only_port.device
    print("bootstrap: pick a board:")
    for index, port in enumerate(ports, start=1):
        description = port.description or "(no description)"
        print(f"  [{index}] {port.device}  {description}")
    raw_choice = prompt_func(f"  Pick [1-{len(ports)}]: ")
    try:
        chosen_index = int(raw_choice.strip())
    except ValueError:
        print(
            f"bootstrap: invalid choice {raw_choice!r}", file=sys.stderr,
        )
        return None
    if chosen_index < 1 or chosen_index > len(ports):
        print(
            f"bootstrap: choice {chosen_index} out of range",
            file=sys.stderr,
        )
        return None
    return ports[chosen_index - 1].device


def _resolve_bootstrap_device_id(
    explicit_id: str | None,
    suggested_id: str,
    *,
    prompt_func: Callable[[str], str] = _stdin_prompt,
) -> str:
    """Either the ``--device-id`` flag's value or an interactive prompt.

    The prompt shows the suggestion in brackets and accepts a blank
    line to mean "use the suggestion".
    """
    if explicit_id:
        return explicit_id
    raw = prompt_func(f"  Device id [{suggested_id}]: ")
    return raw.strip() or suggested_id


def _cmd_bootstrap(  # noqa: C901, PLR0912 — wizard branches stay flat for readability
    args: argparse.Namespace,
    *,
    prompt_func: Callable[[str], str] = _stdin_prompt,
) -> int:
    """Onboard a board end-to-end: pick → probe → register → demo.

    Step 4 of the beginner-onramp workstream — the integration
    command that ties Steps 1-3 + 5 into a single user-visible
    flow.  A user with a freshly-plugged board runs
    ``chumicro-workspace bootstrap`` and walks through:

    1. Pick a port.  When exactly one is detected, it's used
       silently; otherwise the wizard prints a numbered list and
       prompts.  ``--port <path>`` skips the pick.
    2. Probe with runtime auto-inference (Step 3 of the
       workstream).  Failure prints the same diagnosis hints
       ``add-device`` does and exits 1.
    3. Display detected runtime + version + machine.  Firmware-
       support floor (Decision 0039) is checked; OLD / UNKNOWN /
       UNPARSEABLE statuses print a warning but don't abort.
    4. Pick a device id.  ``--device-id <id>`` skips the prompt.
       The default suggestion is derived from the probed machine
       string (e.g. ``"raspberry-pi-pico-w"``).
    5. Register the device in ``devices.yml`` — same write as
       ``add-device`` but no second probe.
    6. Optional ``--with-demo`` deploys the built-in demo
       payload (Step 5 of the workstream) so the user sees their
       board run code immediately.
    7. Print next-steps for the user (``new`` / ``deploy`` /
       ``repl``).

    Args:
        args: Parsed CLI args.  ``port``, ``device_id``, and
            ``with_demo`` are the wizard's three optional knobs.
        prompt_func: Indirection point for tests.  Defaults to
            ``_stdin_prompt``.
    """
    workspace = _resolve_workspace(args)

    # 1. Port pick.
    port = _resolve_bootstrap_port(args.port, prompt_func=prompt_func)
    if port is None:
        return 1

    # 2. Probe.
    print(f"bootstrap: probing {port} ...")
    inference = probe_with_runtime_inference(port)
    if inference.runtime is None or inference.info is None:
        from chumicro_deploy import Device  # noqa: PLC0415

        diagnosis = detect_board_state(
            Device(transport="micropython", address=port),
        )
        if inference.last_exception is not None:
            exception = inference.last_exception
            print(
                f"bootstrap: auto-detect failed "
                f"({type(exception).__name__}: {exception}).",
                file=sys.stderr,
            )
        else:
            print(
                "bootstrap: auto-detect failed — "
                "no runtime returned a probe marker.",
                file=sys.stderr,
            )
        for line in diagnosis.next_steps:
            print(f"  {line}", file=sys.stderr)
        return 1

    info = inference.info
    implementation = info.implementation
    print(f"  runtime: {implementation.name} {implementation.version}")
    if implementation.machine:
        print(f"  machine: {implementation.machine}")

    # 3. Firmware-support check.
    support = check_firmware_supported(implementation)
    if support.status is not FirmwareSupportStatus.SUPPORTED:
        print(
            f"  note: {implementation.name} firmware compatibility:",
            file=sys.stderr,
        )
        for line in explain_firmware_support(support):
            print(f"  {line}", file=sys.stderr)

    # 4. Device id pick.
    suggested_id = _suggest_device_id(implementation)
    device_id = _resolve_bootstrap_device_id(
        args.device_id, suggested_id, prompt_func=prompt_func,
    )

    # 5. Register.
    data = load_devices(workspace.devices_yaml)
    hardware: dict[str, str] = {}
    if info.uid:
        hardware["uid"] = info.uid
    if implementation.machine:
        hardware["machine"] = implementation.machine
    if info.board_id:
        hardware["board_id"] = info.board_id
    try:
        add_device(
            data,
            device_id=device_id,
            runtime=implementation.name,
            address=port,
            hardware=hardware or None,
            firmware_version=implementation.version or None,
        )
    except DeviceAlreadyExistsError:
        print(
            f"bootstrap: device id {device_id!r} already exists "
            f"in {workspace.devices_yaml}.  Pick a different id "
            "or run `add-device --force` to refresh the existing "
            "entry.",
            file=sys.stderr,
        )
        return 1
    dump_devices(data, workspace.devices_yaml)
    print(f"  registered {device_id} at {port}.")

    # 6. Optional demo.
    if args.with_demo:
        demo_args = argparse.Namespace(
            workspace_dir=args.workspace_dir,
            device_id=device_id,
            runtime=None,
        )
        demo_exit = _cmd_demo(demo_args)
        if demo_exit != 0:
            return demo_exit

    # 7. Summary.
    print()
    print("bootstrap: ready.  Next steps:")
    print(
        "  python run.py new <thing-name>      "
        "# create a new thing under things/",
    )
    print(
        "  python run.py deploy                "
        "# deploy your only thing (no name needed)",
    )
    print(
        "  python run.py repl                  "
        "# open the REPL on your board",
    )
    return 0


def _cmd_test(args: argparse.Namespace) -> int:
    """Run the workspace's pytest suite.

    Shells out to ``pytest`` so users get the standard pytest UX
    (``-k``, ``-x``, ``-v``, etc.) without re-implementing argument
    forwarding.  Extra args after ``--`` are passed through verbatim.
    """
    workspace = _resolve_workspace(args)
    completed = subprocess.run(  # noqa: S603 — args fully controlled
        [sys.executable, "-m", "pytest", *args.pytest_args],
        cwd=workspace.root,
        check=False,
    )
    return completed.returncode


def _cmd_lint(args: argparse.Namespace) -> int:
    """Run ``ruff check`` across the workspace.

    Picks up the workspace's ``[tool.ruff]`` config from
    ``pyproject.toml`` automatically — the canonical workspace
    template ships a ruff config matching the chumicro mono-repo's
    tone.  Extra args after ``--`` forward to ruff (e.g.
    ``--fix``, ``--select`` overrides).

    No-op (exit 0 with a hint) when ``ruff`` isn't installed —
    keeps the command discoverable in workspaces that haven't
    pulled the ``[dev]`` extra yet.
    """
    workspace = _resolve_workspace(args)
    try:
        import ruff  # noqa: F401, PLC0415  — availability probe
    except ImportError:
        print(
            "ruff is not installed in this venv.  Install the dev "
            "extras with:\n"
            "    .venv/bin/pip install -e .[dev]\n"
            "or add ruff to your workspace's pyproject.toml deps.",
        )
        return 0
    completed = subprocess.run(  # noqa: S603 — args fully controlled
        [sys.executable, "-m", "ruff", "check", *args.ruff_args, "."],
        cwd=workspace.root,
        check=False,
    )
    return completed.returncode


#: Default tail-window duration (seconds) when ``repl <thing>`` is
#: invoked without an explicit ``--tail SECONDS`` value.  Picked to
#: cover the common "deploy a heartbeat thing, watch a few cycles
#: print, exit clean" inner-loop pattern; users with long boot
#: sequences can override.
_DEFAULT_REPL_TAIL_SECONDS: float = 30.0


def _cmd_repl(args: argparse.Namespace) -> int:
    """Open an interactive REPL, tail output, or deploy-then-tail.

    Three modes:

    * ``repl`` — interactive REPL on the selected board.
    * ``repl --tail SECONDS`` — capture the next *SECONDS* of REPL
      output, exit cleanly.
    * ``repl <thing> [--tail SECONDS]`` — deploy *thing* to the
      board first, then tail.  Combines what used to be
      ``deploy <thing> && repl --tail`` into one command.  When
      ``--tail`` is omitted with a positional, defaults to
      :data:`_DEFAULT_REPL_TAIL_SECONDS`.

    *thing* accepts bare / slash / dotted forms — same shape as
    ``deploy``.  The deploy uses the workspace-runtime boot-shim
    layout (``thing_boot_source``); for flat-layout deploys, run
    ``deploy`` and ``repl --tail`` separately.
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    if args.thing is not None:
        resolved_name = _resolve_thing_name(workspace, args.thing)
        thing_dir = workspace.thing_dir(resolved_name)
        if not thing_dir.is_dir():
            raise SystemExit(f"error: thing {thing_dir} not found")
        from chumicro_deploy import Deployer  # noqa: PLC0415

        source = thing_boot_source(
            thing_dir,
            workspace=workspace,
            thing_name=resolved_name,
            entrypoint_filename=device.effective_entrypoint,
        )
        print(f"repl: deploying {resolved_name} ...")
        deploy_result = Deployer(device).deploy(source)
        if deploy_result.execute_output:
            print(deploy_result.execute_output, end="")
        if not deploy_result.success:
            if deploy_result.traceback:
                print(
                    f"\n--- traceback ---\n{deploy_result.traceback}",
                    file=sys.stderr,
                )
            return 1
        tail_seconds = (
            args.tail if args.tail is not None else _DEFAULT_REPL_TAIL_SECONDS
        )
        from chumicro_repl import tail  # noqa: PLC0415

        return int(tail(
            device,
            tail_seconds,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))

    if args.tail is not None:
        from chumicro_repl import tail  # noqa: PLC0415

        return int(tail(
            device,
            args.tail,
            fail_on_traceback=args.fail_on_traceback,
            output=sys.stdout,
        ))
    from chumicro_repl import interactive  # noqa: PLC0415

    return interactive(device)


def _cmd_install_firmware(args: argparse.Namespace) -> int:
    """Download + flash firmware onto the selected board.

    ``upgrade-firmware`` is registered as an alias of this command —
    flashing the same URL onto a board that already has firmware *is*
    an upgrade, so the implementation does not branch.

    ``--url`` is optional: when omitted, the URL is derived via
    :func:`chumicro_workspace.derive_firmware_url` from the device
    entry's ``hardware.firmware_source`` (custom), ``hardware.board_id``
    (CP S3 listing → latest stable), or ``hardware.machine`` (MP
    curated map).  Unresolvable cases surface a precise message + exit
    2 so the user can paste an explicit URL into ``--url`` (or the
    entry's ``hardware.firmware_source``).
    """
    workspace = _resolve_workspace(args)
    device = _resolve_device(workspace, args)

    if args.url is not None:
        firmware_url = args.url
    else:
        entry = _find_devices_yml_entry_for_args(workspace, args)
        if entry is None:
            print(
                "install-firmware: --url omitted and no device entry "
                "to derive from.  Pass --url explicitly or register "
                "the device with `add-device` first.",
                file=sys.stderr,
            )
            return 2
        try:
            firmware_url = derive_firmware_url(entry, allow_prerelease=args.allow_prerelease)
        except UnresolvableFirmwareError as exception:
            print(f"install-firmware: {exception}", file=sys.stderr)
            return 2
        print(f"install-firmware: resolved {firmware_url}")

    from chumicro_deploy import flash_firmware  # noqa: PLC0415

    flash_firmware(
        firmware_url,
        device,
        reflash_method=args.method,
        bootloader_drive_path=args.bootloader_drive_path,
        interactive=not args.non_interactive,
        erase_flash=args.erase,
        flash_offset=args.offset,
    )
    return 0


# ---------------------------------------------------------------------------
# Stubs — register the surface; implementation lands in a later slice
# ---------------------------------------------------------------------------


def _stub(slice_or_phase: str) -> int:
    """Emit a uniform "not implemented yet" message and return exit-code 2."""
    print(
        f"not implemented yet — landing in {slice_or_phase}.  "
        "See plans/workstreams/project-workspace.md.",
        file=sys.stderr,
    )
    return 2


def _cmd_add_device(args: argparse.Namespace) -> int:
    """Probe a board + register it in devices.yml.

    Builds a fresh entry by probing the supplied address: ``runtime``
    + ``hardware.uid`` + ``hardware.machine`` come from
    :func:`chumicro_deploy.probe_device`; ``address`` rides through
    as-is.  When ``--runtime`` is omitted, the runtime is inferred
    by trying every candidate transport in turn (Decision 0039 +
    Step 3 of the beginner-onramp workstream) — the user can plug a
    fresh board in and register it without knowing what firmware it
    runs.  Re-running with the same id triggers a re-probe and is
    blocked unless ``--force`` is passed (the typical second
    invocation is "I swapped boards on this id" — make the user
    confirm).
    """
    workspace = _resolve_workspace(args)
    from chumicro_deploy import Device, probe_device  # noqa: PLC0415

    if args.runtime is None:
        inference = probe_with_runtime_inference(args.address)
        if inference.runtime is None or inference.info is None:
            # Fall through to the existing diagnose-and-print-error
            # path with whichever transport candidate was last tried.
            probe_device_obj = Device(
                transport="micropython", address=args.address,
            )
            diagnosis = detect_board_state(probe_device_obj)
            if inference.last_exception is not None:
                exception = inference.last_exception
                print(
                    f"add-device: auto-detect failed "
                    f"({type(exception).__name__}: {exception}).",
                    file=sys.stderr,
                )
            else:
                print(
                    "add-device: auto-detect failed — "
                    "no runtime returned a probe marker.",
                    file=sys.stderr,
                )
            for line in diagnosis.next_steps:
                print(f"  {line}", file=sys.stderr)
            return 1
        info = inference.info
        print(
            f"add-device: auto-detected runtime = {inference.runtime}",
        )
    else:
        probe_device_obj = Device(transport=args.runtime, address=args.address)
        try:
            info = probe_device(probe_device_obj)
        except Exception as exception:  # noqa: BLE001 — onboarding diagnoses every failure
            diagnosis = detect_board_state(probe_device_obj)
            print(
                f"add-device: probe failed "
                f"({type(exception).__name__}: {exception}).",
                file=sys.stderr,
            )
            for line in diagnosis.next_steps:
                print(f"  {line}", file=sys.stderr)
            return 1
        if info.implementation is None:
            diagnosis = detect_board_state(probe_device_obj)
            if diagnosis.state is BoardState.UF2_BOOTLOADER:
                print(
                    "add-device: board is in UF2 bootloader, not REPL — "
                    "install firmware first.",
                    file=sys.stderr,
                )
            else:
                print(
                    "add-device: probe did not return implementation marker",
                    file=sys.stderr,
                )
            for line in diagnosis.next_steps:
                print(f"  {line}", file=sys.stderr)
            return 1

    firmware_version = info.implementation.version
    support = check_firmware_supported(info.implementation)

    data = load_devices(workspace.devices_yaml)
    hardware: dict[str, str] = {}
    if info.uid:
        hardware["uid"] = info.uid
    if info.implementation.machine:
        hardware["machine"] = info.implementation.machine
    if info.board_id:
        hardware["board_id"] = info.board_id

    try:
        add_device(
            data,
            device_id=args.id,
            runtime=info.implementation.name,
            address=args.address,
            hardware=hardware or None,
            description=args.description,
            firmware_version=firmware_version or None,
        )
    except DeviceAlreadyExistsError:
        if not args.force:
            print(
                f"add-device: {args.id!r} already exists; pass --force "
                "to re-probe and update the entry",
                file=sys.stderr,
            )
            return 1
        # Re-probe path: keep the existing entry's user-owned fields,
        # refresh the address silently, and update hardware-once leaves
        # under --force semantics so a board swap is reflected.
        update_device_address(data, args.id, args.address)
        if firmware_version:
            update_device_firmware_version(data, args.id, firmware_version)
        try:
            update_device_hardware(data, args.id, hardware, force=True)
        except HardwareOverwriteError as exception:
            print(f"add-device: {exception}", file=sys.stderr)
            return 1

    dump_devices(data, workspace.devices_yaml)
    print(f"add-device: registered {args.id} ({info.implementation.name})")
    if support.status is not FirmwareSupportStatus.SUPPORTED:
        print(
            f"add-device: warning — {info.implementation.name} "
            f"firmware compatibility:",
            file=sys.stderr,
        )
        for line in explain_firmware_support(support):
            print(f"  {line}", file=sys.stderr)
    return 0


def _cmd_rename(args: argparse.Namespace) -> int:
    """Rename a thing directory or a device id.

    Two modes (mutually exclusive): ``--thing OLD NEW`` moves the
    thing directory under ``things/`` (Slice 4 — both names accept
    bare / slash / dotted forms, intermediate namespace dirs are
    auto-created when the new path is in a fresh namespace);
    ``--device OLD NEW`` rewrites the devices.yml entry id + every
    reference to it under ``defaults:``.

    A thing rename does NOT touch already-deployed devices —
    re-deploy the thing under its new name to refresh ``/active.py``
    on each board.
    """
    workspace = _resolve_workspace(args)

    if (args.thing is None) == (args.device is None):
        print(
            "rename: pass exactly one of --thing OLD NEW or --device OLD NEW",
            file=sys.stderr,
        )
        return 2

    if args.thing is not None:
        old_input, new_input = args.thing
        _validate_thing_name(old_input)
        _validate_thing_name(new_input)
        # Old name accepts bare-name disambiguation against the live
        # tree (mirrors deploy / switch).  New name is just normalised
        # — it doesn't exist yet so disambiguation doesn't apply.
        resolved_old = _resolve_thing_name(workspace, old_input)
        resolved_new = new_input.replace(".", "/")
        old_path = workspace.thing_dir(resolved_old)
        new_path = workspace.thing_dir(resolved_new)
        if not old_path.is_dir():
            print(f"rename: thing {old_path} not found", file=sys.stderr)
            return 1
        if new_path.exists():
            print(f"rename: {new_path} already exists", file=sys.stderr)
            return 1
        created_namespaces = _ensure_namespace_parents(workspace, new_path)
        for namespace_dir in created_namespaces:
            print(
                f"rename: creating namespace "
                f"{namespace_dir.relative_to(workspace.root)}/",
            )
        old_path.rename(new_path)
        print(f"rename: {resolved_old} → {resolved_new}")
        return 0

    old_id, new_id = args.device
    data = load_devices(workspace.devices_yaml)
    try:
        rename_device(data, old_id, new_id)
    except DeviceNotFoundError:
        print(f"rename: device {old_id!r} not found in devices.yml", file=sys.stderr)
        return 1
    except DeviceAlreadyExistsError as exception:
        print(f"rename: {exception}", file=sys.stderr)
        return 1
    dump_devices(data, workspace.devices_yaml)
    print(f"rename: device {old_id} → {new_id}")
    return 0


def _cmd_sim(_args: argparse.Namespace) -> int:
    """Run a thing in CPython simulation."""
    return _stub("Phase 4a (sim runner — slice TBD after Slices 3-7)")


def _cmd_env(_args: argparse.Namespace) -> int:  # noqa: CHU001 — workstream-spec command name
    """List / show workspace environments."""
    return _stub("Phase 4a (environments — slice TBD after Slices 3-7)")


def _cmd_use(_args: argparse.Namespace) -> int:
    """Switch the active workspace environment."""
    return _stub("environments — not implemented yet")


def _cmd_sync(_args: argparse.Namespace) -> int:
    """Re-apply the workspace template (superseded by `update`)."""
    return _stub("superseded by `chumicro-workspace update` (Decision 0038)")


def _cmd_upgrade(_args: argparse.Namespace) -> int:
    """Pin to a newer workspace template version (superseded by `update --ref`)."""
    return _stub(
        "superseded by `chumicro-workspace update --ref <ref>` (Decision 0038)",
    )


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser with every command registered."""
    parser = argparse.ArgumentParser(
        prog="chumicro-workspace",
        description=(
            "Host-side dispatcher for ChuMicro project workspaces — "
            "deploy things, probe boards, open REPLs, and manage "
            "devices.yml from one CLI."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # ----- setup ---------------------------------------------------------
    setup_parser = subparsers.add_parser(
        "setup",
        help="Install dependencies and materialize template files.",
    )
    _add_workspace_arg(setup_parser)
    setup_parser.set_defaults(func=_cmd_setup)

    # ----- init ----------------------------------------------------------
    init_parser = subparsers.add_parser(
        "init",
        help="Clone the workspace template into a target directory.",
    )
    init_parser.add_argument(
        "target",
        type=Path,
        help="Workspace directory to create.",
    )
    init_parser.add_argument(
        "--from",
        dest="template_url",
        default=None,
        help="Template git URL (defaults to the canonical ChuMicro template).",
    )
    init_parser.add_argument(
        "--ref",
        dest="git_reference",
        default=None,
        help="Branch or tag to clone (defaults to the remote's HEAD).",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Clear the target before cloning if non-empty.",
    )
    init_parser.set_defaults(func=_cmd_init)

    # ----- update --------------------------------------------------------
    update_parser = subparsers.add_parser(
        "update",
        help=(
            "Re-flow tool-owned template files from upstream. "
            "User-owned files are skipped."
        ),
    )
    _add_workspace_arg(update_parser)
    update_parser.add_argument(
        "--from",
        dest="template_url",
        default=None,
        help="Template git URL (defaults to the canonical ChuMicro template).",
    )
    update_parser.add_argument(
        "--ref",
        dest="git_reference",
        default=None,
        help="Branch or tag to fetch (defaults to the remote's HEAD).",
    )
    update_parser.set_defaults(func=_cmd_update)

    # ----- new -----------------------------------------------------------
    new_parser = subparsers.add_parser(
        "new",
        help=(
            "Create things/<path>/ by copying a template or example tree.  "
            "Path may be nested (slash- or dotted-form)."
        ),
    )
    _add_workspace_arg(new_parser)
    new_parser.add_argument(
        "name",
        help=(
            "Name of the new thing (becomes things/<path>/).  Accepts "
            "bare ('bedroom_sensor'), slash ('upstairs/bedroom_sensor'), "
            "or dotted ('upstairs.bedroom_sensor') forms.  Intermediate "
            "namespace directories are auto-created."
        ),
    )
    new_parser.add_argument(
        "--from",
        dest="from_path",
        default=None,
        help=(
            "Copy from this directory (relative to the workspace root) "
            "instead of things/_template/.  Source must contain an "
            "app.py / code.py / main.py entry-point.  Useful for "
            "`new garage/heater --from examples/two_things/server`."
        ),
    )
    new_parser.set_defaults(func=_cmd_new)

    # ----- add-device ----------------------------------------------------
    add_device_parser = subparsers.add_parser(
        "add-device",
        help="Probe a board and register it in devices.yml.",
    )
    _add_workspace_arg(add_device_parser)
    add_device_parser.add_argument(
        "id",
        help="User-friendly device id (e.g. 'back-porch-mp').",
    )
    add_device_parser.add_argument(
        "--address",
        required=True,
        help="Serial port path of the connected board.",
    )
    add_device_parser.add_argument(
        "--runtime",
        choices=("circuitpython", "micropython"),
        default=None,
        help=(
            "Runtime to probe — picks the right Device facade for "
            "probe_device.  Optional: when omitted, the runtime is "
            "auto-detected by trying both transports against the "
            "given address (Step 3 of the beginner-onramp)."
        ),
    )
    add_device_parser.add_argument(
        "--description",
        default=None,
        help="Free-form note recorded under 'description:' (user-owned zone).",
    )
    add_device_parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Overwrite an existing entry with this id — refreshes the "
            "address and hardware-once fields from the live probe."
        ),
    )
    add_device_parser.set_defaults(func=_cmd_add_device)

    # ----- probe ---------------------------------------------------------
    probe_parser = subparsers.add_parser(
        "probe",
        help="Print the runtime identity reported by the selected board.",
    )
    _add_workspace_arg(probe_parser)
    _add_device_selector(probe_parser)
    probe_parser.set_defaults(func=_cmd_probe)

    # ----- discover ------------------------------------------------------
    discover_parser = subparsers.add_parser(
        "discover",
        help="List the serial ports the host currently sees.",
    )
    discover_parser.set_defaults(func=_cmd_discover)

    # ----- devices -------------------------------------------------------
    devices_parser = subparsers.add_parser(
        "devices",
        help="Print every entry in devices.yml.",
    )
    _add_workspace_arg(devices_parser)
    devices_parser.set_defaults(func=_cmd_devices)

    # ----- deploy --------------------------------------------------------
    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Deploy one or more things — app code + merged runtime config msgpack.",
    )
    _add_workspace_arg(deploy_parser)
    _add_device_selector(deploy_parser)
    deploy_parser.add_argument(
        "names",
        nargs="*",
        metavar="name",
        help=(
            "Name of the thing under things/ to deploy.  Optional when "
            "the workspace contains exactly one thing — that thing is "
            "deployed by default.  One positional per `deploy` call; "
            "multi-thing deploys are no longer supported."
        ),
    )
    deploy_parser.add_argument(
        "--entrypoint",
        default=None,
        help=(
            "Override the on-device entrypoint path.  Defaults to "
            "/code.py on CircuitPython and /main.py on MicroPython."
        ),
    )
    deploy_parser.add_argument(
        "--import-graph",
        action="store_true",
        help=(
            "AST-walk the entrypoint and ship only transitively-"
            "imported modules instead of the full thing directory.  "
            "Reads workspace.yml's library_sources: for overrides."
        ),
    )
    deploy_parser.add_argument(
        "--boot-shim",
        action="store_true",
        help=(
            "Ship the thing under /lib/things/<...>/<name>/ + write a "
            "fixed code.py shim + active.py + workspace_runtime "
            "payload (Decision 0029 §3).  app.py must export run()."
        ),
    )
    deploy_parser.set_defaults(func=_cmd_deploy)

    # ----- things --------------------------------------------------------
    things_parser = subparsers.add_parser(
        "things",
        help="List the things defined under the workspace's things/ tree.",
    )
    _add_workspace_arg(things_parser)
    things_parser.add_argument(
        "--flat",
        action="store_true",
        help=(
            "Print one slash-form path per line instead of the default "
            "tree view (handy for shell pipelines)."
        ),
    )
    things_parser.set_defaults(func=_cmd_things)

    # ----- status --------------------------------------------------------
    status_parser = subparsers.add_parser(
        "status",
        help=(
            "Print a one-line-per-check workspace health snapshot "
            "(workspace.yml validity, devices.yml count, secrets.yml "
            "placeholders, things tree summary)."
        ),
    )
    _add_workspace_arg(status_parser)
    status_parser.set_defaults(func=_cmd_status)

    # ----- demo ----------------------------------------------------------
    demo_parser = subparsers.add_parser(
        "demo",
        help=(
            "Deploy a built-in 'hello world' payload to the active "
            "device.  Cross-runtime safe; ~5 seconds to run."
        ),
    )
    _add_workspace_arg(demo_parser)
    _add_device_selector(demo_parser)
    demo_parser.set_defaults(func=_cmd_demo)

    # ----- bootstrap -----------------------------------------------------
    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help=(
            "End-to-end onboarding wizard: pick a port, auto-probe "
            "the runtime, register the device, optionally deploy "
            "the demo payload.  All prompts are skippable via "
            "flags for non-interactive runs."
        ),
    )
    _add_workspace_arg(bootstrap_parser)
    bootstrap_parser.add_argument(
        "--port",
        default=None,
        help=(
            "Skip the interactive port pick — use this serial port "
            "path verbatim (e.g. '/dev/cu.usbmodem1101')."
        ),
    )
    bootstrap_parser.add_argument(
        "--device-id",
        dest="device_id",
        default=None,
        help=(
            "Skip the interactive device-id prompt — register the "
            "board under this id."
        ),
    )
    bootstrap_parser.add_argument(
        "--with-demo",
        dest="with_demo",
        action="store_true",
        help=(
            "After registration, deploy the built-in demo payload "
            "(equivalent to running `demo` afterward)."
        ),
    )
    bootstrap_parser.set_defaults(func=_cmd_bootstrap)

    # ----- sim -----------------------------------------------------------
    sim_parser = subparsers.add_parser(
        "sim",
        help="Run a thing in CPython simulation (planned, not yet shipped).",
    )
    _add_workspace_arg(sim_parser)
    sim_parser.set_defaults(func=_cmd_sim)

    # ----- test ----------------------------------------------------------
    test_parser = subparsers.add_parser(
        "test",
        help="Run pytest in the workspace root.  Extra args pass through.",
    )
    _add_workspace_arg(test_parser)
    test_parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Args forwarded verbatim to pytest (place after `--`).",
    )
    test_parser.set_defaults(func=_cmd_test)

    # ----- lint ----------------------------------------------------------
    lint_parser = subparsers.add_parser(
        "lint",
        help="Run `ruff check` across the workspace.  Extra args pass through.",
    )
    _add_workspace_arg(lint_parser)
    lint_parser.add_argument(
        "ruff_args",
        nargs=argparse.REMAINDER,
        help="Args forwarded verbatim to ruff (place after `--`).",
    )
    lint_parser.set_defaults(func=_cmd_lint)

    # ----- repl ----------------------------------------------------------
    repl_parser = subparsers.add_parser(
        "repl",
        help=(
            "Interactive REPL on the selected board, or deploy a thing "
            "and tail its output in one command."
        ),
    )
    _add_workspace_arg(repl_parser)
    _add_device_selector(repl_parser)
    repl_parser.add_argument(
        "thing",
        nargs="?",
        default=None,
        help=(
            "Optional thing name (bare / slash / dotted).  When given, "
            "deploys the thing first then enters tail mode for "
            "--tail SECONDS (default 30)."
        ),
    )
    repl_parser.add_argument(
        "--tail",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Run in tail mode for SECONDS instead of the interactive "
            "TUI.  When a positional thing is given, defaults to 30s."
        ),
    )
    repl_parser.add_argument(
        "--no-fail-on-traceback",
        dest="fail_on_traceback",
        action="store_false",
        default=True,
        help="Tail mode only: do not exit non-zero on a detected traceback.",
    )
    repl_parser.set_defaults(func=_cmd_repl)

    # ----- env -----------------------------------------------------------
    env_parser = subparsers.add_parser(
        "env",
        help="List / show workspace environments (planned).",
    )
    _add_workspace_arg(env_parser)
    env_parser.set_defaults(func=_cmd_env)

    # ----- use -----------------------------------------------------------
    use_parser = subparsers.add_parser(
        "use",
        help="Switch the active workspace environment (planned).",
    )
    _add_workspace_arg(use_parser)
    use_parser.set_defaults(func=_cmd_use)

    # ----- rename --------------------------------------------------------
    rename_parser = subparsers.add_parser(
        "rename",
        help="Rename a thing directory or a device id.",
    )
    _add_workspace_arg(rename_parser)
    rename_target = rename_parser.add_mutually_exclusive_group(required=True)
    rename_target.add_argument(
        "--thing",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="Rename things/OLD/ to things/NEW/.",
    )
    rename_target.add_argument(
        "--device",
        nargs=2,
        metavar=("OLD", "NEW"),
        default=None,
        help="Rename a devices.yml entry id (also rewrites defaults: references).",
    )
    rename_parser.set_defaults(func=_cmd_rename)

    # ----- install-firmware ----------------------------------------------
    install_firmware_parser = subparsers.add_parser(
        "install-firmware",
        help="Download + flash firmware onto the selected board.",
    )
    _add_workspace_arg(install_firmware_parser)
    _add_device_selector(install_firmware_parser)
    _add_firmware_args(install_firmware_parser)
    install_firmware_parser.set_defaults(func=_cmd_install_firmware)

    # ----- upgrade-firmware ----------------------------------------------
    upgrade_firmware_parser = subparsers.add_parser(
        "upgrade-firmware",
        help="Alias of install-firmware — same flash flow.",
    )
    _add_workspace_arg(upgrade_firmware_parser)
    _add_device_selector(upgrade_firmware_parser)
    _add_firmware_args(upgrade_firmware_parser)
    upgrade_firmware_parser.set_defaults(func=_cmd_install_firmware)

    # ----- sync ----------------------------------------------------------
    sync_parser = subparsers.add_parser(
        "sync",
        help="Deprecated — superseded by `update`.",
    )
    _add_workspace_arg(sync_parser)
    sync_parser.set_defaults(func=_cmd_sync)

    # ----- upgrade -------------------------------------------------------
    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="Deprecated — superseded by `update --ref <ref>`.",
    )
    _add_workspace_arg(upgrade_parser)
    upgrade_parser.set_defaults(func=_cmd_upgrade)

    return parser


def _add_firmware_args(parser: argparse.ArgumentParser) -> None:
    """Attach the shared firmware-flash flags."""
    parser.add_argument(
        "--url",
        default=None,
        help=(
            "Firmware download URL.  When omitted, the URL is "
            "derived from the device entry's hardware fields (CP: "
            "S3-bucket lookup; MP: curated machine→BOARD map; or "
            "hardware.firmware_source override)."
        ),
    )
    parser.add_argument(
        "--allow-prerelease",
        action="store_true",
        help=(
            "CP-only: include pre-release versions (-rc.0, -beta.1) "
            "when deriving the latest URL.  Stable-only by default."
        ),
    )
    parser.add_argument(
        "--method",
        choices=("uf2", "esptool"),
        required=True,
        help="Flash backend: uf2 for RP2040/RP2350, esptool for ESP32 family.",
    )
    parser.add_argument(
        "--bootloader-drive",
        dest="bootloader_drive_path",
        type=Path,
        default=None,
        help="uf2 path only: explicit bootloader drive mount.",
    )
    parser.add_argument(
        "--erase",
        action="store_true",
        help="esptool path only: erase-flash before write-flash.",
    )
    parser.add_argument(
        "--offset",
        default="0x0",
        help="esptool path only: write-flash offset (default 0x0).",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Fail instead of prompting when bootloader entry needs help.",
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    """Parse *argv* and dispatch to the selected command.

    Returns the process exit code.  Stub commands return 2 so CI /
    scripts can distinguish "not implemented yet" from runtime errors.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
