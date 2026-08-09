"""Maintain ``pyrightconfig.json`` ``extraPaths`` for curated libraries.

``library add`` (and the ``browse`` apply tail) acquire a chumicro
library into ``libraries/<name>/`` with its sources under
``libraries/<name>/src/``.  Pyright only resolves ``from <name> import
...`` in project code when that source directory is on ``extraPaths``,
but the workspace template ships only ``"shared"``.  So each acquiring
command calls :func:`add_library_extra_paths` to register the new
source directories, and ``remove`` / ``forget`` call
:func:`remove_library_extra_paths` to drop them again.

``pyrightconfig.json`` is tracked workspace content, and the managed
entries are meant to be committed: an acquired ``libraries/<name>/``
tree is itself committable workspace content, each entry mirrors one
acquired tree, and a teammate cloning the workspace gets resolving
editor imports only when the two travel together.  The entries are
machine-independent (workspace-root-relative POSIX paths), so nothing
per-host leaks into git; dropping an acquired tree via ``remove`` /
``forget`` clears its entry again.

The file stays user-owned JSON: unrelated ``extraPaths`` entries (such
as ``"shared"``) and unrelated top-level keys are preserved, the order
of untouched entries is kept, and new entries are appended in sorted
order.  A missing file is created with just ``{"extraPaths": [...]}``.
Writes go through :func:`~chumicro_workspace.atomic_write.atomic_write_text`
so a crash never leaves a half-written config.  A file that exists but
cannot be parsed as a JSON object with a list ``extraPaths`` raises
:class:`InvalidPyrightConfigError` so the caller can coach and skip
rather than crash the acquisition.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from chumicro_workspace.atomic_write import atomic_write_text

#: Name of the workspace-root pyright config the helpers maintain.
PYRIGHT_CONFIG_FILENAME = "pyrightconfig.json"


class InvalidPyrightConfigError(RuntimeError):
    """``pyrightconfig.json`` exists but is not a usable JSON object.

    Raised when the file is not valid JSON, its top-level value is not
    an object, or its ``extraPaths`` value is not a list.  Callers catch
    this to warn-and-skip instead of crashing the library acquisition.
    """


def library_source_path(name: str) -> str:
    """Return the workspace-relative source directory for a curated library.

    Args:
        name: Import name of the curated library, e.g. ``chumicro_wifi``.

    Returns:
        The POSIX-style, workspace-root-relative path pyright needs on
        ``extraPaths`` to resolve the library, e.g.
        ``libraries/chumicro_wifi/src``.
    """
    return f"libraries/{name}/src"


def add_library_extra_paths(
    workspace_root: Path, names: Iterable[str],
) -> list[str]:
    """Ensure ``extraPaths`` lists each library's source directory.

    Reads (or starts) ``pyrightconfig.json`` at *workspace_root*, appends
    any missing library source paths in sorted order, and writes the
    file back only when something changed.  Existing entries keep their
    order and unrelated top-level keys are left untouched.

    Args:
        workspace_root: Workspace root holding ``pyrightconfig.json``.
        names: Import names of the acquired libraries.

    Returns:
        The entries newly added, sorted.  Empty when every entry was
        already present (an idempotent no-op that writes nothing).

    Raises:
        InvalidPyrightConfigError: The file exists but is not a JSON
            object with a list ``extraPaths``.
    """
    config_path = workspace_root / PYRIGHT_CONFIG_FILENAME
    document = _load_document(config_path)
    entries = _extra_paths(document)
    present = set(entries)
    added = sorted({
        library_source_path(name)
        for name in names
        if library_source_path(name) not in present
    })
    if not added:
        return []
    document["extraPaths"] = [*entries, *added]
    _write_document(config_path, document)
    return added


def remove_library_extra_paths(
    workspace_root: Path, names: Iterable[str],
) -> list[str]:
    """Drop each library's source directory from ``extraPaths``.

    Reads ``pyrightconfig.json`` at *workspace_root* and removes the
    matching source paths, writing back only when something changed.
    Every other entry (such as ``"shared"``) and every unrelated
    top-level key is preserved.  A missing file is a no-op.

    Args:
        workspace_root: Workspace root holding ``pyrightconfig.json``.
        names: Import names of the libraries being uninstalled.

    Returns:
        The entries removed, in their original file order.  Empty when
        none were present (an idempotent no-op that writes nothing).

    Raises:
        InvalidPyrightConfigError: The file exists but is not a JSON
            object with a list ``extraPaths``.
    """
    config_path = workspace_root / PYRIGHT_CONFIG_FILENAME
    document = _load_document(config_path)
    entries = _extra_paths(document)
    dropped = {library_source_path(name) for name in names}
    removed = [entry for entry in entries if entry in dropped]
    if not removed:
        return []
    document["extraPaths"] = [entry for entry in entries if entry not in dropped]
    _write_document(config_path, document)
    return removed


def _load_document(config_path: Path) -> dict[str, object]:
    """Parse ``pyrightconfig.json``; return an empty mapping when absent.

    Args:
        config_path: Path to the workspace's ``pyrightconfig.json``.

    Returns:
        The parsed JSON object, or ``{}`` when the file does not exist.

    Raises:
        InvalidPyrightConfigError: The file exists but is not valid JSON
            or its top-level value is not an object.
    """
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    try:
        document = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise InvalidPyrightConfigError(str(error)) from error
    if not isinstance(document, dict):
        raise InvalidPyrightConfigError("top-level value is not an object")
    return document


def _extra_paths(document: dict[str, object]) -> list[object]:
    """Return the document's ``extraPaths`` list (empty when absent).

    Args:
        document: A parsed ``pyrightconfig.json`` object.

    Returns:
        The current ``extraPaths`` list, or ``[]`` when the key is absent.

    Raises:
        InvalidPyrightConfigError: ``extraPaths`` is present but not a list.
    """
    entries = document.get("extraPaths", [])
    if not isinstance(entries, list):
        raise InvalidPyrightConfigError("'extraPaths' is not a list")
    return entries


def _write_document(config_path: Path, document: dict[str, object]) -> None:
    """Atomically write *document* as 2-space-indented JSON with a newline.

    Args:
        config_path: Path to the workspace's ``pyrightconfig.json``.
        document: The JSON object to serialize.
    """
    atomic_write_text(config_path, json.dumps(document, indent=2) + "\n")
