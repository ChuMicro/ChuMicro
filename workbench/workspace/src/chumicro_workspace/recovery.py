"""App-level deploy-failure recovery hints.

When a project's own code fails on the device, the deploy command's
captured traceback is the only signal the user gets.  Raw tracebacks
are precise about *what* broke but offer no guidance on *why* — the
common workspace-shaped causes (missing required config key,
library not installed locally) all surface as terse stdlib errors
that don't mention the workspace context that produced them.

This module pattern-matches against the captured traceback and
returns one or more :class:`AppErrorHint` rows the CLI can display
under the traceback.  The hint table is intentionally small + easy
to extend — each row is a regex + label + format-string template.

Sibling to :mod:`chumicro_deploy.recovery` (which handles
*transport* failures — wedged macOS FSKit mounts, no-REPL boards,
etc.).  Different layer: ``chumicro-deploy``'s recovery is about
"why didn't the deploy land"; this module is about "the deploy
landed but the project crashed."

Phase 2d of the workspace-ecosystem workstream.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AppErrorHint:
    """One remediation hint for a pattern matched in a traceback.

    Attributes:
        pattern_label: Stable short identifier for the pattern.
            Useful for tests and structured logging.
        hint: User-facing remediation text.  The CLI prints these
            verbatim under the traceback, indented one level.
    """

    pattern_label: str
    hint: str


#: Pattern table: ``(regex, label, hint_template)`` tuples.  The
#: hint template is `.format()`-applied to the regex's match groups,
#: so a ``{0}`` placeholder picks up group ``\1``.  Templates without
#: placeholders ignore the groups silently.
#:
#: New patterns: append to the bottom (existing label semantics
#: stay stable for downstream tooling that keys on the label).
_HINT_TABLE: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"NameError: name '([^']+)' is not defined"),
        "name-error",
        (
            "did you forget to import {0!r}?  Verify the symbol's "
            "source module and add the matching `from ... import ...` "
            "to app.py."
        ),
    ),
    (
        re.compile(r"OSError:.*['\"]?/?runtime_config\.msgpack"),
        "ram-mode-config",
        (
            "RAM-mode deploys don't persist `/runtime_config.msgpack` "
            "— switch to flash mode for projects that read runtime "
            "config (set `defaults.deploy_mode: flash` in devices.yml "
            "or override per-device)."
        ),
    ),
    (
        re.compile(
            r"(?:ImportError|ModuleNotFoundError)[^\n]*"
            r"['\"]?(?:no module named\s+)?(chumicro_\w+)['\"]?",
            re.IGNORECASE,
        ),
        "missing-chumicro-lib",
        (
            "library `{0}` isn't installed in this venv — run "
            "`python run.py setup` to refresh deps, or add `{0}` to "
            "the workspace's pyproject.toml dependencies."
        ),
    ),
    (
        re.compile(r"KeyError:\s*'([^']+)'"),
        "missing-config-key",
        (
            "missing config key `{0}` — check projects/<project>/config.toml "
            "or workspace.yml's `defaults:` block (the gitignored workspace "
            "config carrying defaults + credentials).  Use "
            "`python run.py deploy <project> --dry-run` to inspect what "
            "the merged runtime config carries."
        ),
    ),
)


def detect_hints(traceback_text: str) -> list[AppErrorHint]:
    """Return remediation hints matching patterns in *traceback_text*.

    Order matches the table — earlier patterns fire first.  Multiple
    patterns can match the same traceback (e.g. an `ImportError`
    that's triggered by a `NameError`-shaped chain); each independent
    match becomes its own hint.

    Empty input or no match → empty list.  Callers that pass `None`
    should guard upstream — this function doesn't.
    """
    hints: list[AppErrorHint] = []
    if not traceback_text:
        return hints
    seen_labels: set[str] = set()
    for pattern, label, template in _HINT_TABLE:
        match = pattern.search(traceback_text)
        if match is None or label in seen_labels:
            continue
        seen_labels.add(label)
        try:
            hint_text = template.format(*match.groups())
        except (IndexError, KeyError):  # pragma: no cover — defensive
            hint_text = template
        hints.append(AppErrorHint(pattern_label=label, hint=hint_text))
    return hints


def format_hints(hints: list[AppErrorHint]) -> str:
    """Render *hints* as the block printed under a traceback.

    Empty list → empty string (caller should skip the section
    header entirely so an unmatched traceback doesn't get a
    confusing "--- hints ---" with nothing under it).
    """
    if not hints:
        return ""
    lines = ["--- hints ---"]
    for hint in hints:
        lines.append(f"  {hint.hint}")
    return "\n".join(lines)
