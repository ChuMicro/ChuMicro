"""Read + aggregate + validate library config manifests.

Each ChuMicro library that consumes ``runtime_config.msgpack``
declares its required / optional flat dotted keys in its
``pyproject.toml``::

    [tool.chumicro.config]
    required_keys = ["wifi.ssid", "wifi.password"]
    optional_keys = ["wifi.hostname", "wifi.connect_timeout_ms"]

The keys live in the same vocabulary the runtime accessor uses
(``config["wifi.ssid"]``) so the validator's failure message names
the exact key the library code will request.

This module reads those manifests, unions them across the libraries
imported by a project, and validates a merged-and-resolved **flat**
config dict against the union — turning a class of "config mismatch
lands on device, fails at boot, prints a cryptic ``MissingConfigKey``"
errors into precise deploy-time failures.

Public surface:

* :class:`ConfigManifest` — one library's required / optional key sets.
* :class:`ConfigManifestError` — raised when a config dict is missing
  a required key.
* :func:`read_manifest` — parse one library's ``pyproject.toml``.
* :func:`aggregate_manifests` — union the required + optional sets
  across multiple libraries.  A key declared optional by one library
  and required by another is required overall.
* :func:`validate_runtime_config` — check a flat config dict against
  an aggregated manifest; raise on missing required.

Three-line example::

    from chumicro_workspace.config_manifest import (
        aggregate_manifests, read_manifest, validate_runtime_config,
    )

    manifests = [read_manifest(library_root) for library_root in roots]
    union = aggregate_manifests(m for m in manifests if m is not None)
    validate_runtime_config(flat_merged_config_dict, union)

Libraries without a manifest (``read_manifest`` returns ``None``)
contribute nothing to the union — they don't read runtime config,
so there's nothing to validate against.  Forward-compat: a config
can carry keys no library currently requires without raising.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ConfigManifest:
    """One library's flat-key declaration for ``runtime_config``.

    Attributes:
        library_name: The library's PyPI name (``chumicro-wifi``,
            etc.) — derived from ``[project].name`` in
            ``pyproject.toml``, falling back to the library directory
            name.
        required_keys: Flat dotted keys that must be present in the
            merged runtime config.  Missing any of them at deploy
            time raises :class:`ConfigManifestError`.
        optional_keys: Flat dotted keys the library reads but
            tolerates missing — ``load_section``'s factory uses its
            declared default when absent.  Listed here so doc
            tooling can render the full surface, and so the
            aggregator can spot "optional in lib A, required in lib B".
        declared_by: Path(s) to the ``pyproject.toml`` that declared
            this manifest.  After :func:`aggregate_manifests` joins
            multiple libraries, this becomes a comma-separated list
            of every contributor.  Used by error messages.
    """

    library_name: str
    required_keys: frozenset[str] = field(default_factory=frozenset)
    optional_keys: frozenset[str] = field(default_factory=frozenset)
    declared_by: str = ""


class ConfigManifestError(Exception):
    """Raised when a config dict fails validation against a manifest.

    Subclasses :class:`Exception` directly (not :class:`ValueError`)
    so deploy-time error reporting can catch it with a single
    ``except`` clause and route to the user-facing recovery hint
    layer (`chumicro_workspace.recovery`).
    """


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------


def read_manifest(library_root: Path) -> ConfigManifest | None:
    """Read a library's ``[tool.chumicro.config]`` block.

    Args:
        library_root: Directory containing a ``pyproject.toml``.
            Typically a path under ``libraries/<name>/`` in the
            mono-repo, or under ``libraries/<name>/`` in a workspace
            built from the workspace-template.

    Returns:
        :class:`ConfigManifest` when the library declares a manifest,
        ``None`` when the library has no ``[tool.chumicro.config]``
        block (the common case — most libraries don't read runtime
        config).

    Raises:
        ConfigManifestError: ``pyproject.toml`` is malformed or the
            ``required_keys`` / ``optional_keys`` value isn't a list
            of strings.
        FileNotFoundError: ``library_root / "pyproject.toml"`` does
            not exist.
    """
    pyproject_path = library_root / "pyproject.toml"
    with pyproject_path.open("rb") as handle:
        pyproject = tomllib.load(handle)

    config_table = (
        pyproject.get("tool", {}).get("chumicro", {}).get("config")
    )
    if config_table is None:
        return None

    if not isinstance(config_table, dict):
        raise ConfigManifestError(
            f"{pyproject_path}: [tool.chumicro.config] must be a table, "
            f"got {type(config_table).__name__}",
        )

    library_name = pyproject.get("project", {}).get("name", library_root.name)
    return ConfigManifest(
        library_name=library_name,
        required_keys=_parse_key_list(
            config_table.get("required_keys", []),
            "required_keys",
            pyproject_path,
        ),
        optional_keys=_parse_key_list(
            config_table.get("optional_keys", []),
            "optional_keys",
            pyproject_path,
        ),
        declared_by=str(pyproject_path),
    )


def _parse_key_list(
    raw: object,
    field_name: str,
    pyproject_path: Path,
) -> frozenset[str]:
    if not isinstance(raw, list):
        raise ConfigManifestError(
            f"{pyproject_path}: [tool.chumicro.config].{field_name} "
            f"must be a list, got {type(raw).__name__}",
        )
    if not all(isinstance(item, str) for item in raw):
        raise ConfigManifestError(
            f"{pyproject_path}: [tool.chumicro.config].{field_name} "
            f"must contain only strings",
        )
    return frozenset(raw)


# ---------------------------------------------------------------------------
# Helpers — derive library roots from import-graph search paths
# ---------------------------------------------------------------------------


def find_library_roots(
    search_paths: Iterable[Path],
) -> tuple[Path, ...]:
    """Return the directories under *search_paths* that own a ``pyproject.toml``.

    The import graph's search paths are typically directories like
    ``libraries/<name>/src/`` (the importable module layout) — the
    pyproject sits one level up at ``libraries/<name>/pyproject.toml``.
    Other search-path entries (``shared/``, ``packages/``,
    ``library_sources:`` overrides pointing at arbitrary directories)
    may or may not have a pyproject; this helper silently filters
    them out, returning only paths where one exists.

    Returned in the same order as the input.  Duplicates removed
    (when two search-path entries resolve to the same library root,
    e.g. an override and the default scan both finding
    ``libraries/wifi/``).

    Args:
        search_paths: Directories the import graph searches when
            resolving imports.  Typically built via
            :func:`chumicro_workspace.build_search_paths`.

    Returns:
        Tuple of directories that contain a ``pyproject.toml``.
        Each such directory can be passed to :func:`read_manifest`.
    """
    seen: set[Path] = set()
    roots: list[Path] = []
    for search_path in search_paths:
        candidates = [search_path.parent, search_path]
        for candidate in candidates:
            if (candidate / "pyproject.toml").is_file():
                resolved = candidate.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    roots.append(candidate)
                break
    return tuple(roots)


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def aggregate_manifests(
    manifests: Iterable[ConfigManifest | None],
) -> ConfigManifest | None:
    """Union the required + optional key sets across multiple libraries.

    A key declared **optional** by one library and **required** by
    another is required overall — the strictest declaration wins.
    The aggregated ``declared_by`` is a comma-joined list of every
    library that contributed.

    Args:
        manifests: Iterable of per-library manifests.  ``None``
            entries are silently dropped (callers can pass
            :func:`read_manifest`'s output directly without
            filtering).

    Returns:
        Aggregated :class:`ConfigManifest`, or ``None`` when every
        input was ``None`` / no library declares any keys.
    """
    aggregated_required: set[str] = set()
    aggregated_optional: set[str] = set()
    sources: list[str] = []
    saw_any = False
    for manifest in manifests:
        if manifest is None:
            continue
        saw_any = True
        aggregated_required |= manifest.required_keys
        aggregated_optional |= manifest.optional_keys
        if manifest.declared_by:
            sources.append(manifest.declared_by)
    if not saw_any:
        return None
    # Required wins: an "optional" key in one library doesn't override
    # a "required" declaration from another.
    aggregated_optional -= aggregated_required
    return ConfigManifest(
        library_name="<aggregated>",
        required_keys=frozenset(aggregated_required),
        optional_keys=frozenset(aggregated_optional),
        declared_by=", ".join(sources),
    )


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def validate_runtime_config(
    config: Mapping[str, object],
    manifest: ConfigManifest | None,
) -> None:
    """Check that ``config`` satisfies every required key in ``manifest``.

    Validation rules:

    * Every key in ``manifest.required_keys`` must be present as a
      top-level key in the flat *config* dict.
    * Optional keys carry no constraint — present or absent, any
      value is accepted.
    * Keys in *config* not declared by any library are ignored —
      apps can carry app-specific config alongside library config.

    Args:
        config: The merged-and-flattened runtime config dict that
            would be written to ``runtime_config.msgpack``.  Keys
            are flat dotted strings.
        manifest: Aggregated manifest, typically from
            :func:`aggregate_manifests`.  ``None`` (no library
            declares any keys) skips validation.

    Raises:
        ConfigManifestError: One or more required keys are missing
            from *config*.  The message names every offending key
            in one multi-line string so deploy-time errors don't
            ping-pong the user.
    """
    if manifest is None or not manifest.required_keys:
        return
    missing = sorted(key for key in manifest.required_keys if key not in config)
    if not missing:
        return
    declared_by = manifest.declared_by or "<unknown>"
    bullets = "\n".join(f"  - {key}" for key in missing)
    raise ConfigManifestError(
        "Runtime config is missing keys required by imported libraries:\n"
        f"{bullets}\n"
        f"(declared by: {declared_by})",
    )
