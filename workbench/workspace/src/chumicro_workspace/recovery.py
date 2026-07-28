"""App-level deploy-failure recovery hints.

Pattern-matches a captured Python traceback against known
workspace-shaped failure modes (NameError, missing chumicro
library, missing config key, RAM-mode runtime_config write) and
returns one or more :class:`AppErrorHint` rows for the CLI to
print under the traceback.

Raw Python tracebacks name the stdlib error but not the
workspace context behind it, so a missing config key surfaces
as a bare ``KeyError`` without saying which file should have
carried it.  Each pattern in :data:`_HINT_TABLE` translates a
generic error into a workspace-aware remediation pointer.
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
#: New patterns: append to the bottom.
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
            "RAM-mode deploys don't persist `/runtime_config.msgpack`.  "
            "Switch to flash mode for projects that read runtime "
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
            "library `{0}` isn't installed in this venv; run "
            "`python3 run.py setup` to refresh deps, or add `{0}` to "
            "the workspace's pyproject.toml dependencies."
        ),
    ),
    (
        re.compile(r"KeyError:\s*'([^']+)'"),
        "missing-config-key",
        (
            "missing config key `{0}`: check projects/<project>/project_config.toml "
            "or `secrets.toml` (the gitignored workspace-wide credentials + "
            "device defaults).  Use `python3 run.py deploy <project> --dry-run` "
            "to inspect what the merged runtime config carries."
        ),
    ),
)


def detect_hints(traceback_text: str) -> list[AppErrorHint]:
    """Return remediation hints matching patterns in *traceback_text*.

    Order matches the table, so earlier patterns fire first.  Multiple
    patterns can match the same traceback, and each independent
    match becomes its own hint.

    Empty input or no match returns an empty list.
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
        except (IndexError, KeyError):  # pragma: no cover - defensive
            hint_text = template
        hints.append(AppErrorHint(pattern_label=label, hint=hint_text))
    return hints


def format_hints(hints: list[AppErrorHint]) -> str:
    """Render *hints* as the block printed under a traceback.

    Returns an empty string for an empty list, so an unmatched
    traceback doesn't get a "--- hints ---" header with nothing
    under it.
    """
    if not hints:
        return ""
    lines = ["--- hints ---"]
    for hint in hints:
        lines.append(f"  {hint.hint}")
    return "\n".join(lines)
