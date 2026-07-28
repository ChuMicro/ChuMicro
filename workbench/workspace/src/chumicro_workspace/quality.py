"""Workspace quality knobs: `lint`, `coverage`.

Two sources, merged per key:

* ``quality.toml`` at the workspace root: the committed policy.
  Travels with the workspace's git history, so a shared repo carries
  its own gates.  TOML mirror of the block below, without the
  ``quality:`` wrapper:

  .. code-block:: toml

      coverage_threshold = 85    # top-level keys go BEFORE any [table]

      [lint]
      enabled = true
      tools = ["ruff", "chumicro-checks"]
      select = ["E", "F", "I"]

* the ``quality:`` block on ``workspace.yml``: the per-machine
  override (the file is gitignored).  Any key set here wins over
  the same key in ``quality.toml``:

  .. code-block:: yaml

      quality:
        lint:
          enabled: true
          tools: ["ruff", "chumicro-checks"]
          select: ["E", "F", "I"]
        coverage_threshold: 85

Reads both, validates each file's shape separately (so an error
names the file that carries it), merges, and returns a typed
:class:`QualityConfig`.  Validation only.  Lint and coverage are
run elsewhere.

* ``lint.enabled = false`` turns ``python3 run.py lint`` into a
  no-op with a hint (still discoverable; just doesn't run anything).
* ``lint.tools`` selects which tools to run.  Default runs
  both ``ruff`` and ``chumicro-checks``; drop one to disable that
  tool without disabling the whole phase.  Empty list short-circuits
  to the same hint as ``enabled = false``.
* ``lint.select`` is forwarded to ruff as ``--select <comma list>``
  before any user-supplied passthrough args (so user `--` overrides
  win).
* ``coverage_threshold`` is forwarded to pytest as
  ``--cov-fail-under=<n>``.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from chumicro_workspace.loaders import WorkspaceConfigError

#: Committed quality-policy file, resolved next to ``workspace.yml``.
QUALITY_TOML_NAME = "quality.toml"

#: Tools the lint phase knows how to run.  ``tools`` entries outside
#: this set raise :class:`WorkspaceConfigError` at config-load time so
#: typos surface up front rather than silently no-op'ing.
KNOWN_LINT_TOOLS: frozenset[str] = frozenset({"ruff", "chumicro-checks"})


def _default_lint_tools() -> list[str]:
    """Default ``tools`` list: both registered tools, fixed order."""
    return ["ruff", "chumicro-checks"]


@dataclass(frozen=True)
class LintConfig:
    """Lint-related knobs from ``workspace.yml``'s ``quality.lint``.

    Attributes:
        enabled: When False, ``python3 run.py lint`` is a no-op.
            Defaults to True so a missing block doesn't disable
            linting silently.
        tools: Which lint tools to run.  Defaults to running both
            ``ruff`` and ``chumicro-checks``; drop one to disable
            that tool without disabling the whole phase.  An empty
            list behaves like ``enabled = false``.
        select: Optional list of ruff rule codes (``["E", "F", "I"]``).
            ``None`` means "use whatever's in pyproject.toml's
            ``[tool.ruff.lint]`` block."
    """

    enabled: bool = True
    tools: list[str] = field(default_factory=_default_lint_tools)
    select: list[str] | None = None


@dataclass(frozen=True)
class QualityConfig:
    """Combined workspace quality config.

    Attributes:
        lint: Lint sub-config.  Always present; defaults preserved
            when the YAML block is absent.
        coverage_threshold: Optional ``--cov-fail-under`` value;
            ``None`` means "don't enforce a gate from workspace.yml"
            (pyproject.toml's ``[tool.coverage.report] fail_under``
            still applies).
    """

    lint: LintConfig = field(default_factory=LintConfig)
    coverage_threshold: int | None = None


def _read_yaml_dict(path: Path) -> dict[str, Any]:
    """Read a YAML file's top-level mapping; raise on malformed shape."""
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        loaded = YAML(typ="safe").load(handle)
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise WorkspaceConfigError(
            f"{path}: top-level must be a mapping, "
            f"got {type(loaded).__name__}",
        )
    return loaded


def _coerce_lint(raw: Any, path: Path) -> LintConfig:
    """Build a :class:`LintConfig` from the raw ``quality.lint`` dict."""
    if raw is None:
        return LintConfig()
    if not isinstance(raw, dict):
        raise WorkspaceConfigError(
            f"{path}: 'quality.lint' must be a mapping, "
            f"got {type(raw).__name__}",
        )
    enabled_raw = raw.get("enabled", True)
    if not isinstance(enabled_raw, bool):
        raise WorkspaceConfigError(
            f"{path}: 'quality.lint.enabled' must be a bool, "
            f"got {type(enabled_raw).__name__}",
        )
    if "tools" in raw:
        tools_raw = raw["tools"]
        if not isinstance(tools_raw, list) or not all(
            isinstance(item, str) for item in tools_raw
        ):
            raise WorkspaceConfigError(
                f"{path}: 'quality.lint.tools' must be a list of strings",
            )
        unknown = [item for item in tools_raw if item not in KNOWN_LINT_TOOLS]
        if unknown:
            known_list = ", ".join(sorted(KNOWN_LINT_TOOLS))
            raise WorkspaceConfigError(
                f"{path}: 'quality.lint.tools' has unknown entries "
                f"{unknown!r}; known tools are: {known_list}",
            )
        tools_value = list(tools_raw)
    else:
        tools_value = _default_lint_tools()
    select_raw = raw.get("select")
    if select_raw is not None:
        if not isinstance(select_raw, list) or not all(
            isinstance(item, str) for item in select_raw
        ):
            raise WorkspaceConfigError(
                f"{path}: 'quality.lint.select' must be a list of strings",
            )
        select_value: list[str] | None = list(select_raw)
    else:
        select_value = None
    return LintConfig(enabled=enabled_raw, tools=tools_value, select=select_value)


def _coerce_coverage_threshold(raw_quality: dict[str, Any], path: Path) -> int | None:
    """Validate and return ``coverage_threshold`` from a raw quality dict."""
    coverage_threshold_raw = raw_quality.get("coverage_threshold")
    if coverage_threshold_raw is None:
        return None
    if isinstance(coverage_threshold_raw, bool) or not isinstance(
        coverage_threshold_raw, int,
    ):
        # bool is a subclass of int, so reject it explicitly so
        # `coverage_threshold: true` doesn't silently become 1.
        raise WorkspaceConfigError(
            f"{path}: 'quality.coverage_threshold' must be "
            f"an integer, got {type(coverage_threshold_raw).__name__}",
        )
    return coverage_threshold_raw


def _coerce_quality(raw_quality: dict[str, Any], path: Path) -> QualityConfig:
    """Build a :class:`QualityConfig` from a raw quality dict."""
    return QualityConfig(
        lint=_coerce_lint(raw_quality.get("lint"), path),
        coverage_threshold=_coerce_coverage_threshold(raw_quality, path),
    )


def _read_quality_toml(path: Path) -> dict[str, Any]:
    """Read a ``quality.toml``'s top-level table; raise on malformed shape."""
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except tomllib.TOMLDecodeError as decode_error:
        raise WorkspaceConfigError(f"{path}: {decode_error}") from decode_error


def _merge_quality(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Overlay *overlay*'s set keys onto *base*, one level deep for ``lint``."""
    merged = dict(base)
    for key, value in overlay.items():
        if key == "lint" and isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def load_quality_config(workspace_yaml: Path) -> QualityConfig:
    """Load + validate the workspace quality config.

    Two sources merge, per key: the committed ``quality.toml`` next to
    *workspace_yaml* carries the policy that travels with the repo,
    and ``workspace.yml``'s ``quality:`` block carries per-machine
    overrides that win over it.  When neither exists, the defaults
    apply (lint enabled, no coverage gate from these files;
    ``pyproject.toml``'s ``fail_under`` still holds the floor).

    Each source validates separately, so a shape violation raises
    :class:`WorkspaceConfigError` naming the file that carries the bad
    value rather than a vague tool exit code later.
    """
    toml_path = workspace_yaml.parent / QUALITY_TOML_NAME
    toml_raw = _read_quality_toml(toml_path)
    if toml_raw:
        _coerce_quality(toml_raw, toml_path)  # validate with the right path

    document = _read_yaml_dict(workspace_yaml)
    yaml_raw = document.get("quality")
    if yaml_raw is None:
        yaml_raw = {}
    elif not isinstance(yaml_raw, dict):
        raise WorkspaceConfigError(
            f"{workspace_yaml}: 'quality' must be a mapping, "
            f"got {type(yaml_raw).__name__}",
        )
    if yaml_raw:
        _coerce_quality(yaml_raw, workspace_yaml)  # validate with the right path

    return _coerce_quality(_merge_quality(toml_raw, yaml_raw), workspace_yaml)
