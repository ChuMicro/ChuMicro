"""Workspace quality knobs — `lint`, `coverage`, `agent_strictness`.

Phase 5 of the workspace-ecosystem workstream.  Decision 0029
specified a ``quality:`` block on ``workspace.yml`` carrying
three pass-through knobs:

.. code-block:: yaml

    quality:
      lint:
        enabled: true
        select: ["E", "F", "I"]
      coverage_threshold: 85
      agent_strictness: relaxed   # or "strict"

This module reads the block, validates the shape, and surfaces a
typed :class:`QualityConfig` the CLI consults.  Pure file read +
shape validation; no execution side effects.

* ``lint.enabled = false`` → ``python run.py lint`` becomes a
  no-op with a hint (still discoverable; just doesn't run ruff).
* ``lint.select`` → forwarded to ruff as ``--select <comma list>``
  before any user-supplied passthrough args (so user `--` overrides
  win).
* ``coverage_threshold`` → forwarded to pytest as
  ``--cov-fail-under=<n>``.
* ``agent_strictness`` — accepted into the dataclass but not yet
  consumed.  The plan calls for AST-level checks
  (no naked `except:`, no global state in things) which need their
  own design pass; surfacing it here lets users set the field
  without rejection.

Defaults match a "permissive workspace" stance: lint enabled, no
explicit select (use ruff's pyproject.toml config), no coverage
gate, agent_strictness=relaxed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from chumicro_workspace.loaders import WorkspaceConfigError

#: Permitted values for ``agent_strictness``.  Keeps a typo from
#: silently flipping behaviour — the loader rejects unknown values.
_AGENT_STRICTNESS_VALUES: frozenset[str] = frozenset({"relaxed", "strict"})


@dataclass(frozen=True)
class LintConfig:
    """Lint-related knobs from ``workspace.yml``'s ``quality.lint``.

    Attributes:
        enabled: When False, ``python run.py lint`` is a no-op.
            Defaults to True so a missing block doesn't disable
            linting silently.
        select: Optional list of ruff rule codes (``["E", "F", "I"]``).
            ``None`` means "use whatever's in pyproject.toml's
            ``[tool.ruff.lint]`` block."
    """

    enabled: bool = True
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
        agent_strictness: ``"relaxed"`` or ``"strict"``.  Accepted but
            not yet consumed — the AST checks the plan calls for need
            their own design pass.
    """

    lint: LintConfig = field(default_factory=LintConfig)
    coverage_threshold: int | None = None
    agent_strictness: str = "relaxed"


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
    return LintConfig(enabled=enabled_raw, select=select_value)


def load_quality_config(workspace_yaml: Path) -> QualityConfig:
    """Load + validate the ``quality:`` block from a ``workspace.yml``.

    Missing file or missing ``quality`` block → returns
    :class:`QualityConfig` with library-default values (lint
    enabled, no coverage gate, ``relaxed`` strictness).  This makes
    Phase 5 a no-op for workspaces that haven't opted in.

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

    agent_strictness = raw_quality.get("agent_strictness", "relaxed")
    if not isinstance(agent_strictness, str):
        raise WorkspaceConfigError(
            f"{workspace_yaml}: 'quality.agent_strictness' must be a string",
        )
    if agent_strictness not in _AGENT_STRICTNESS_VALUES:
        permitted = ", ".join(sorted(_AGENT_STRICTNESS_VALUES))
        raise WorkspaceConfigError(
            f"{workspace_yaml}: 'quality.agent_strictness' must be one of "
            f"{permitted}; got {agent_strictness!r}",
        )

    return QualityConfig(
        lint=lint,
        coverage_threshold=coverage_threshold,
        agent_strictness=agent_strictness,
    )
