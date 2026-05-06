"""``chumicro-dev.toml`` integration — sibling chumicro-checkout setup.

When a ``chumicro-dev.toml`` file sits next to ``workspace.yml``, the
workspace is in **dev mode** — chumicro libraries the project imports
come from a sibling Git checkout instead of the published PyPI /
circup / mip channels.  The template's ``run.py`` already pip-installs
the host packages from that checkout (so ``chumicro-deploy``,
``chumicro-workspace`` etc. live-edit from disk), but the on-device
side — the libraries the *board* runs (``chumicro_kvstore``,
``chumicro_wifi``, etc.) — needs a parallel wiring: the deploy-time
import-graph walker has to know to resolve ``import chumicro_<name>``
against the sibling checkout's ``libraries/<name>/src/`` instead of
``packages/`` (which is empty in dev mode) or the user's own
``shared/``.  The ``library_sources:`` block in ``workspace.yml``
maps importable names to host search paths,
and :func:`chumicro_workspace.import_graph.read_library_sources`
plumbs them into :class:`chumicro_deploy.ImportGraphSource`.

This module owns the host-side **setup-time** machinery that keeps
that block in sync with the dev-mode checkout:

* :func:`read_chumicro_dev_path` parses the toml and resolves
  ``chumicro_path`` against the workspace root.
* :func:`discover_chumicro_libraries` walks
  ``<chumicro_path>/libraries/`` and returns an
  ``{import_name: src_path}`` mapping suitable for ``library_sources:``.
* :func:`sync_library_sources` writes / replaces a managed block in
  ``workspace.yml``.  Idempotent — re-running ``setup`` after pulling
  new chumicro libraries refreshes the block to match the new set,
  without disturbing other top-level keys (``defaults:`` etc.) or
  their comments.

The CLI wires this into ``setup`` so the user gets the right
``library_sources`` automatically every time they bootstrap a dev-mode
workspace.  Gap 3(a) of the workspace-template
dev-and-regular-mode-gaps audit.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

#: Filename consulted in the workspace root.  Same name the template's
#: ``run.py`` reads — keeps the user's mental model "one toml controls
#: dev mode."
CHUMICRO_DEV_FILENAME = "chumicro-dev.toml"

#: Comment written immediately above the managed ``library_sources:``
#: key.  The marker is descriptive only — there's no parse-side check
#: that a user-edited block is "ours" (workspace.yml is user-owned;
#: the comment exists to make the provenance obvious to a human
#: opening the file).
MANAGED_MARKER = (
    "managed by chumicro-workspace setup — chumicro-dev.toml mode"
)

#: Match a top-level ``library_sources:`` block plus its indented
#: children, optionally preceded by our managed-marker comment line.
#:
#: ``(?m)^`` anchors at line starts so we don't catch
#: ``library_sources:`` references inside comments or nested under
#: another key.  The ``(?:# {marker}\n)?`` prefix is optional — when
#: the file has the marker (re-runs in dev mode), the match starts
#: at the marker line and the whole block (marker + key + children)
#: gets replaced atomically; when the file has a bare
#: ``library_sources:`` (legacy / non-dev-mode user content), the
#: match starts at the key line and just the bare block gets
#: replaced.  Either way, ``re.search`` returns the longer match
#: at the earliest line.
#:
#: Used for string-level surgery in :func:`sync_library_sources` —
#: see that function's docstring for why we don't round-trip
#: through ruamel.
_LIB_SOURCES_BLOCK_RE = re.compile(
    r"(?m)^"
    r"(?:\# " + re.escape(MANAGED_MARKER) + r"\n)?"
    r"library_sources:[ \t]*\n"
    r"(?:[ \t]+[^\n]*\n)*",
)


def read_chumicro_dev_path(workspace_root: Path) -> Path | None:
    """Resolve the sibling chumicro path declared in ``chumicro-dev.toml``.

    Returns the absolute path the toml's ``chumicro_path`` value
    points at, or ``None`` when the file is missing or the key is
    unset.  Relative paths resolve against *workspace_root* (so a
    typical ``chumicro_path = "../chumicro"`` resolves to the
    expected sibling-directory layout).

    Args:
        workspace_root: Workspace root directory (where
            ``workspace.yml`` and ``chumicro-dev.toml`` live).
    """
    dev_file = workspace_root / CHUMICRO_DEV_FILENAME
    if not dev_file.is_file():
        return None
    data = tomllib.loads(dev_file.read_text(encoding="utf-8"))
    raw_path = data.get("chumicro_path")
    if not raw_path:
        return None
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (workspace_root / candidate).resolve()
    return candidate


def discover_chumicro_libraries(chumicro_path: Path) -> dict[str, Path]:
    """Walk ``<chumicro_path>/libraries/`` and return ``{import_name: src_path}``.

    Each entry maps the package's importable name (``chumicro_<libname>``)
    to the directory whose children are importable under that name —
    ``<chumicro_path>/libraries/<libname>/src/``.

    Skips library directories that don't expose a recognizable src
    tree (missing ``src/chumicro_<libname>/__init__.py``) so an
    in-progress scaffold under ``libraries/`` doesn't wedge the sync.
    Hidden / dotfile dirs are skipped too.

    Returns ``{}`` when the ``libraries/`` directory itself is missing
    — caller decides whether that's a warning or an error.

    Args:
        chumicro_path: Resolved sibling chumicro repository root.
    """
    libraries_dir = chumicro_path / "libraries"
    if not libraries_dir.is_dir():
        return {}
    result: dict[str, Path] = {}
    for library_dir in sorted(libraries_dir.iterdir()):
        if not library_dir.is_dir():
            continue
        if library_dir.name.startswith("."):
            continue
        src_dir = library_dir / "src"
        if not src_dir.is_dir():
            continue
        package_dir = src_dir / f"chumicro_{library_dir.name}"
        if not package_dir.is_dir():
            continue
        if not (package_dir / "__init__.py").is_file():
            continue
        result[f"chumicro_{library_dir.name}"] = src_dir
    return result


def _relative_to_or_absolute(path: Path, anchor: Path) -> str:
    """Return *path* relative to *anchor* when possible, else absolute.

    Used to keep the written ``library_sources:`` block readable —
    a sibling chumicro checkout produces ``../chumicro/libraries/<name>/src``
    instead of a long absolute path that varies per developer.
    """
    resolved = path.resolve()
    anchor_resolved = anchor.resolve()
    try:
        return str(resolved.relative_to(anchor_resolved))
    except ValueError:
        # Path is not under anchor — try walk-up form.
        # On POSIX, os.path.relpath gives ``../chumicro/...`` which
        # is what we want for a sibling checkout.
        import os  # noqa: PLC0415
        return os.path.relpath(resolved, anchor_resolved)


def sync_library_sources(
    workspace_yaml: Path, libraries: dict[str, Path],
) -> bool:
    """Write or replace the managed ``library_sources:`` block in *workspace_yaml*.

    Returns ``True`` when the file was modified, ``False`` when the
    existing block already matched the desired state (idempotent
    re-run).

    Implementation note — string-level surgery, parser-independent:

    The previous implementation round-tripped the entire
    ``workspace.yml`` through ruamel-rt, which dropped the file's
    leading comment header on the first sync against an
    all-comments-no-keys starter (ruamel attaches comments to keys;
    a leading header with no key under it has nothing to anchor to).
    This rewrite instead locates the existing managed block (the
    optional marker comment + ``library_sources:`` key + indented
    children) via a single regex against the raw bytes, replaces it
    byte-identically, and leaves every other byte of the file
    untouched — comments, blank lines, quoting, indentation
    choices.

    The managed block REPLACES any existing top-level
    ``library_sources:``, with or without our marker comment — the
    contract is "dev mode owns this key when ``chumicro-dev.toml``
    is present."  Decoupled from ruamel; tightly coupled to YAML's
    indent-based block syntax.  A future migration to TOML would
    need a different block-finder (the regex pattern is YAML-shaped).

    Paths in *libraries* are written relative to the workspace root
    when possible (sibling-checkout case produces
    ``../chumicro/libraries/<name>/src``); otherwise the absolute
    resolved path is used.  Keys are sorted alphabetically so the
    block is diff-stable across runs.

    Args:
        workspace_yaml: Path to ``workspace.yml`` (created if missing).
        libraries: ``{import_name: host_path}`` mapping — typically
            from :func:`discover_chumicro_libraries`.
    """
    workspace_dir = workspace_yaml.parent

    new_block_lines = [
        f"# {MANAGED_MARKER}",
        "library_sources:",
    ]
    for name in sorted(libraries):
        rel_path = _relative_to_or_absolute(libraries[name], workspace_dir)
        new_block_lines.append(f"  {name}: {rel_path}")
    new_block = "\n".join(new_block_lines) + "\n"

    existing_text = (
        workspace_yaml.read_text(encoding="utf-8")
        if workspace_yaml.is_file()
        else ""
    )

    match = _LIB_SOURCES_BLOCK_RE.search(existing_text)
    if match is not None:
        # The regex already absorbs the optional marker line above
        # ``library_sources:`` — match.start() is the start of the
        # marker when present, the start of ``library_sources:``
        # otherwise.  Atomic replacement either way.
        if match.group(0) == new_block:
            return False
        new_text = (
            existing_text[:match.start()]
            + new_block
            + existing_text[match.end():]
        )
    else:
        # No existing block — append.  Add a separating blank line
        # before the new block when the existing tail isn't already
        # a blank line (so re-runs against an empty file produce
        # ``new_block`` alone, but re-runs against a populated file
        # leave a visible separator from the previous content).
        prefix = existing_text
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix and not prefix.endswith("\n\n"):
            prefix += "\n"
        new_text = prefix + new_block

    workspace_yaml.parent.mkdir(parents=True, exist_ok=True)
    workspace_yaml.write_text(new_text, encoding="utf-8")
    return True
