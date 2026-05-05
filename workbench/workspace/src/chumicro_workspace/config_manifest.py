"""Read + aggregate + validate library config manifests.

Each ChuMicro library that consumes ``runtime_config.msgpack``
declares its required / optional keys in its ``pyproject.toml``::

    [tool.chumicro.config.sections.wifi]
    required = ["ssid", "password"]
    optional = ["hostname", "connect_timeout_ms"]

Section names are inferred from the keys of
``tool.chumicro.config.sections`` — one
``[tool.chumicro.config.sections.<name>]`` table per section.  An
empty table is valid and means "this library reads ``<name>`` but
doesn't pin keys yet" (forward-compat).

This module reads those manifests, unions them across the libraries
imported by a project, and validates a merged-and-resolved config
dict against the union — turning a class of "config mismatch lands
on device, fails at boot, prints a cryptic ``MissingConfigKey``"
errors into precise deploy-time failures.

Public surface:

* :class:`SectionManifest` — one library's declaration for one section.
* :class:`ConfigManifest` — the per-library top-level shape.
* :class:`ConfigManifestError` — raised when a config dict is missing
  a required key (or has a section with the wrong type).
* :func:`read_manifest` — parse one library's ``pyproject.toml``.
* :func:`aggregate_manifests` — union the section requirements
  across multiple libraries.  When two libraries declare the same
  section, ``required`` keys union (any library's "must have"
  remains "must have") and ``optional`` keys union too.  A key
  declared optional by one library and required by another is
  required overall.
* :func:`validate_runtime_config` — check a config dict against an
  aggregated manifest; raise on missing required.

Three-line example::

    from chumicro_workspace.config_manifest import (
        aggregate_manifests, read_manifest, validate_runtime_config,
    )

    manifests = [read_manifest(library_root) for library_root in roots]
    union = aggregate_manifests(m for m in manifests if m is not None)
    validate_runtime_config(merged_config_dict, union)

Libraries without a manifest (``read_manifest`` returns ``None``)
contribute nothing to the union — they don't read runtime config,
so there's nothing to validate against.  Forward-compat: a config
can carry sections no library currently imports without raising.
"""

from __future__ import annotations

import tomllib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SectionManifest:
    """One library's declaration for one ``runtime_config`` section.

    Attributes:
        name: The section key in the merged config dict — typically
            the library's basename without the ``chumicro-`` prefix
            (e.g. ``chumicro-wifi`` reads from section ``wifi``).
        required: Keys that must be present in this section.  Missing
            any of them at deploy time raises :class:`ConfigManifestError`.
        optional: Keys the library reads but tolerates missing —
            ``load_section``'s factory uses its declared default when
            absent.  Listed here so doc-generation tooling can render
            the full surface, and so the union-aggregator can spot
            "this library considers it optional but a sibling
            library considers it required".
        declared_by: Path to the ``pyproject.toml`` that declared
            this manifest.  Used by error messages so users can
            point at the right library when the union surfaces a
            requirement.  Empty string when synthesized (e.g. by
            tests).
    """

    name: str
    required: frozenset[str]
    optional: frozenset[str]
    declared_by: str = ""


@dataclass(frozen=True)
class ConfigManifest:
    """All ``runtime_config`` sections one library declares.

    Empty ``sections`` is valid — a library can opt into the
    manifest format (e.g. for forward-compat with tooling) without
    declaring any required keys yet.
    """

    library_name: str
    sections: tuple[SectionManifest, ...]


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
        ConfigManifestError: ``pyproject.toml`` is malformed,
            ``sections`` references a name with no
            ``[tool.chumicro.config.sections.<name>]`` block, or a
            section's ``required`` / ``optional`` value isn't a list
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
    sections_table = config_table.get("sections", {})
    if not isinstance(sections_table, dict):
        raise ConfigManifestError(
            f"{pyproject_path}: [tool.chumicro.config].sections must be a "
            f"sub-table (declare each section as "
            f"[tool.chumicro.config.sections.<name>]), got "
            f"{type(sections_table).__name__}",
        )

    section_manifests = tuple(
        _parse_section(name, sub_table, pyproject_path)
        for name, sub_table in sections_table.items()
    )
    return ConfigManifest(
        library_name=library_name,
        sections=section_manifests,
    )


def _parse_section(
    name: str,
    table: Mapping[str, object],
    pyproject_path: Path,
) -> SectionManifest:
    """Parse one ``[tool.chumicro.config.sections.<name>]`` table."""
    if not isinstance(table, dict):
        raise ConfigManifestError(
            f"{pyproject_path}: [tool.chumicro.config.sections.{name}] must "
            f"be a table, got {type(table).__name__}",
        )
    return SectionManifest(
        name=name,
        required=_parse_key_list(
            table.get("required", []), name, "required", pyproject_path,
        ),
        optional=_parse_key_list(
            table.get("optional", []), name, "optional", pyproject_path,
        ),
        declared_by=str(pyproject_path),
    )


def _parse_key_list(
    raw: object,
    section_name: str,
    field_name: str,
    pyproject_path: Path,
) -> frozenset[str]:
    if not isinstance(raw, list):
        raise ConfigManifestError(
            f"{pyproject_path}: [tool.chumicro.config.sections."
            f"{section_name}].{field_name} must be a list, "
            f"got {type(raw).__name__}",
        )
    if not all(isinstance(item, str) for item in raw):
        raise ConfigManifestError(
            f"{pyproject_path}: [tool.chumicro.config.sections."
            f"{section_name}].{field_name} must contain only strings",
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
        # Two layouts to recognise:
        #   1. ``libraries/<name>/src/`` — pyproject.toml at parent.
        #   2. A bare directory that itself owns a pyproject.toml
        #      (rare but valid for one-off library-source overrides).
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
    manifests: Iterable[ConfigManifest],
) -> dict[str, SectionManifest]:
    """Union the section requirements across multiple libraries.

    When two libraries declare the same section name, the result
    section's ``required`` is the union of both — any library's
    "must have" keeps the key required overall.  ``optional`` is
    the union too, minus any keys that became required.  The
    aggregated section's ``declared_by`` is a comma-joined list of
    every library that contributed.

    Args:
        manifests: Iterable of per-library manifests.  ``None``
            entries are silently dropped (callers can pass
            :func:`read_manifest`'s output directly without
            filtering).

    Returns:
        Dict keyed by section name.  Empty dict when no library
        declares any section.
    """
    aggregated: dict[str, SectionManifest] = {}
    for manifest in manifests:
        if manifest is None:
            continue
        for section in manifest.sections:
            existing = aggregated.get(section.name)
            if existing is None:
                aggregated[section.name] = section
                continue
            new_required = existing.required | section.required
            # Optional keys that are required by either library
            # are no longer "optional" overall — drop them from
            # the optional set so validation is consistent.
            new_optional = (existing.optional | section.optional) - new_required
            sources = ", ".join(
                source for source in (existing.declared_by, section.declared_by)
                if source
            )
            aggregated[section.name] = SectionManifest(
                name=section.name,
                required=new_required,
                optional=new_optional,
                declared_by=sources,
            )
    return aggregated


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def validate_runtime_config(
    config: Mapping[str, object],
    manifest: Mapping[str, SectionManifest],
) -> None:
    """Check that ``config`` satisfies every section in ``manifest``.

    Validation rules:

    * Each section in ``manifest`` must be present as a top-level
      key in ``config``.
    * Each section's value must be a mapping.
    * Every key in ``manifest[<section>].required`` must be present
      in ``config[<section>]``.

    Forward-compat:

    * Sections in ``config`` not in ``manifest`` are ignored —
      apps can carry app-specific config alongside library config.
    * Keys in a section that aren't in ``required`` or ``optional``
      are ignored — same forward-compat as
      :func:`chumicro_config.load_section`.

    Args:
        config: The merged-and-resolved runtime config dict that
            would be written to ``runtime_config.msgpack``.
        manifest: Aggregated section manifests, typically from
            :func:`aggregate_manifests`.

    Raises:
        ConfigManifestError: A required section is missing, has the
            wrong type, or is missing a required key.  The message
            names every offending section + key in one multi-line
            string so deploy-time errors don't ping-pong the user.
    """
    problems: list[str] = []
    for section_name, section_manifest in manifest.items():
        section_value = config.get(section_name)
        if section_value is None:
            problems.append(
                f"  [{section_name}] section missing — required keys: "
                f"{', '.join(sorted(section_manifest.required))} "
                f"(declared by: {section_manifest.declared_by})",
            )
            continue
        if not isinstance(section_value, Mapping):
            problems.append(
                f"  [{section_name}] section must be a table, got "
                f"{type(section_value).__name__} "
                f"(declared by: {section_manifest.declared_by})",
            )
            continue
        missing_required = sorted(
            key for key in section_manifest.required
            if key not in section_value
        )
        if missing_required:
            problems.append(
                f"  [{section_name}] missing required keys: "
                f"{', '.join(missing_required)} "
                f"(declared by: {section_manifest.declared_by})",
            )
    if problems:
        raise ConfigManifestError(
            "Runtime config does not satisfy the union manifest of "
            "imported libraries:\n" + "\n".join(problems),
        )
