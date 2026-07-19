"""Read and write the ``libraries:`` table in ``workspace.yml``.

Each row records a curated chumicro library installed in the
workspace: which channel it tracks (``stable`` or
``experimental``), the snapshot version it's pinned to, and an
optional ``declined: true`` flag set when the user declined a
transitive prompt.

Schema::

    libraries:
      chumicro_mqtt:
        channel: stable
        version: "0.10.2"
      chumicro_sockets:
        channel: experimental
        version: "0.4.1.dev3"
        declined: true            # declined at transitive prompt

``version`` is always a quoted string so YAML reads ``0.10.0`` as
text rather than as a float.  The ``HEAD`` sentinel marks a
``--floating`` entry that re-resolves to the channel's latest on
every op.  ``declined`` is written only when true.  A missing
``libraries:`` key reads as ``{}``; the clean-workspace case is
normal, not an error.

Sibling of ``library_sources:`` in the same file:
``library_sources:`` answers "where is the code on disk?" for
the deploy walker; this table answers "where did each curated
library come from, and at what version?".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML

from chumicro_workspace.loaders import WorkspaceConfigError
from chumicro_workspace.managed_block import sync_managed_block

CURATED_LIBRARIES_MARKER = (
    "managed by chumicro-workspace library — edit via the library subcommands"
)

#: The two PyPI channels a curated library can track.
VALID_CHANNELS = ("stable", "experimental")

#: Channel a fresh workspace acquires from when the user does not pass
#: ``--channel``.  ``stable`` since the 2026-07-19 launch: the stable
#: channel carries every library at its current version, so a fresh
#: clone gets release-quality packages by default and opts into
#: ``experimental`` per library when it wants pre-release snapshots.
DEFAULT_CHANNEL = "stable"

#: ``version`` value marking a ``--floating`` entry (always-latest).
HEAD = "HEAD"


@dataclass
class CuratedLibrary:
    """One row of the ``libraries:`` table."""

    name: str
    channel: str
    version: str
    declined: bool = False


def read_curated_libraries(workspace_yaml: Path) -> dict[str, CuratedLibrary]:
    """Parse the ``libraries:`` table out of *workspace_yaml*.

    Returns ``{import_name: CuratedLibrary}``.  An absent file or
    absent ``libraries:`` key returns ``{}`` (the clean-workspace
    case is normal, not an error).

    Raises:
        WorkspaceConfigError: When ``libraries:`` exists but isn't a
            mapping, an entry isn't a mapping, ``channel`` is missing
            or not one of :data:`VALID_CHANNELS`, ``version`` is
            missing or not a string, or ``declined`` isn't a bool.
    """
    if not workspace_yaml.is_file():
        return {}
    with workspace_yaml.open("r", encoding="utf-8") as handle:
        loaded = YAML(typ="safe").load(handle)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise WorkspaceConfigError(
            f"{workspace_yaml}: top-level must be a mapping, "
            f"got {type(loaded).__name__}",
        )
    raw = loaded.get("libraries")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise WorkspaceConfigError(
            f"{workspace_yaml}: 'libraries' must be a mapping, "
            f"got {type(raw).__name__}",
        )

    result: dict[str, CuratedLibrary] = {}
    for name, entry in raw.items():
        location = f"{workspace_yaml}: 'libraries.{name}'"
        if not isinstance(entry, dict):
            raise WorkspaceConfigError(
                f"{location} must be a mapping, got {type(entry).__name__}",
            )
        channel = entry.get("channel")
        if channel not in VALID_CHANNELS:
            raise WorkspaceConfigError(
                f"{location}.channel must be one of "
                f"{', '.join(VALID_CHANNELS)}, got {channel!r}",
            )
        version = entry.get("version")
        if not isinstance(version, str):
            raise WorkspaceConfigError(
                f"{location}.version must be a string, "
                f"got {type(version).__name__}",
            )
        declined = entry.get("declined", False)
        if not isinstance(declined, bool):
            raise WorkspaceConfigError(
                f"{location}.declined must be a bool, "
                f"got {type(declined).__name__}",
            )
        result[name] = CuratedLibrary(name, channel, version, declined)
    return result


def render_curated_child_lines(
    libraries: dict[str, CuratedLibrary],
) -> list[str]:
    """Render the indented YAML lines under ``libraries:``.

    Keys sorted alphabetically so the block is diff-stable across runs.
    """
    lines: list[str] = []
    for name in sorted(libraries):
        library = libraries[name]
        lines.append(f"  {name}:")
        lines.append(f"    channel: {library.channel}")
        lines.append(f'    version: "{library.version}"')
        if library.declined:
            lines.append("    declined: true")
    return lines


def write_curated_libraries(
    workspace_yaml: Path, libraries: dict[str, CuratedLibrary],
) -> bool:
    """Write or replace the managed ``libraries:`` block.

    Returns ``True`` when the file changed, ``False`` on a re-run
    that produces the same content.  Rewrites the whole block; the
    caller holds the full desired state.
    """
    return sync_managed_block(
        workspace_yaml,
        "libraries",
        CURATED_LIBRARIES_MARKER,
        render_curated_child_lines(libraries),
    )
