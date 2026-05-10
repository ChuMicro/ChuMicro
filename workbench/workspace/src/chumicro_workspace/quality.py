"""Workspace quality knobs — `lint`, `coverage`.

Reads the ``quality:`` block on ``workspace.yml`` carrying these
pass-through knobs:

.. code-block:: yaml

    quality:
      lint:
        enabled: true
        tools: ["ruff", "chumicro-checks"]
        select: ["E", "F", "I"]
      coverage_threshold: 85

This module reads the block, validates the shape, and surfaces a
typed :class:`QualityConfig` the CLI consults.  Pure file read +
shape validation; no execution side effects.

* ``lint.enabled = false`` → ``python run.py lint`` becomes a
  no-op with a hint (still discoverable; just doesn't run anything).
* ``lint.tools`` → list selecting which tools to run.  Default runs
  both ``ruff`` and ``chumicro-checks``; drop one to disable that
  tool without disabling the whole phase.  Empty list short-circuits
  to the same hint as ``enabled = false``.
* ``lint.select`` → forwarded to ruff as ``--select <comma list>``
  before any user-supplied passthrough args (so user `--` overrides
  win).
* ``coverage_threshold`` → forwarded to pytest as
  ``--cov-fail-under=<n>``.

Defaults match a "permissive workspace" stance: lint enabled, both
tools active, no explicit select (use ruff's pyproject.toml config),
no coverage gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from chumicro_workspace.loaders import WorkspaceConfigError

#: Tools the lint phase knows how to run.  ``tools`` entries outside
#: this set raise :class:`WorkspaceConfigError` at config-load time so
#: typos surface up front rather than silently no-op'ing.
KNOWN_LINT_TOOLS: frozenset[str] = frozenset({"ruff", "chumicro-checks"})


def _default_lint_tools() -> list[str]:
    """Default ``tools`` list — both registered tools, fixed order."""
    return ["ruff", "chumicro-checks"]


@dataclass(frozen=True)
class LintConfig:
    """Lint-related knobs from ``workspace.yml``'s ``quality.lint``.

    Attributes:
        enabled: When False, ``python run.py lint`` is a no-op.
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


def load_quality_config(workspace_yaml: Path) -> QualityConfig:
    """Load + validate the ``quality:`` block from a ``workspace.yml``.

    Missing file or missing ``quality`` block → returns
    :class:`QualityConfig` with library-default values (lint
    enabled, no coverage gate).  Workspaces that haven't opted
    in get the no-op behaviour.

    Raises :class:`WorkspaceConfigError` on shape violations so the
    user sees the precise field that's wrong rather than a vague
    ``ruff` exit code later.
    """
    document = _read_yaml_dict(workspace_yaml)
    raw_quality = document.get("quality")
    if raw_quality is None:
        return QualityConfig()
    if not isinstance(raw_quality, dict):
        raise WorkspaceConfigError(
            f"{workspace_yaml}: 'quality' must be a mapping, "
            f"got {type(raw_quality).__name__}",
        )

    lint = _coerce_lint(raw_quality.get("lint"), workspace_yaml)

    coverage_threshold_raw = raw_quality.get("coverage_threshold")
    if coverage_threshold_raw is None:
        coverage_threshold: int | None = None
    elif isinstance(coverage_threshold_raw, bool) or not isinstance(
        coverage_threshold_raw, int,
    ):
        # bool is a subclass of int — reject it explicitly so
        # `coverage_threshold: true` doesn't silently become 1.
        raise WorkspaceConfigError(
            f"{workspace_yaml}: 'quality.coverage_threshold' must be "
            f"an integer, got {type(coverage_threshold_raw).__name__}",
        )
    else:
        coverage_threshold = coverage_threshold_raw

    return QualityConfig(
        lint=lint,
        coverage_threshold=coverage_threshold,
    )
