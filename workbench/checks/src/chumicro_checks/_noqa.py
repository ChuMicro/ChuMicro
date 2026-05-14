"""``noqa`` directive parsing — shared between every rule that supports
per-line suppression.

Two suppression syntaxes are recognized:

* ``# noqa: CHU0NN`` — Python, TOML, INI, anywhere a ``#`` line comment
  is valid.
* ``<!-- noqa: CHU0NN -->`` — Markdown.

Both forms accept a comma-separated list of codes (``# noqa: CHU006,
CHU012``) and a bare form (``# noqa``) that suppresses every code.
"""

from __future__ import annotations

import re

_NOQA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"#\s*noqa(?::\s*([A-Z0-9, ]+))?"),
    re.compile(r"<!--\s*noqa(?::\s*([A-Z0-9, ]+))?\s*-->"),
)


def line_suppresses(line: str, code: str) -> bool:
    """Return True when *line* carries a noqa directive that mutes *code*.

    A bare ``# noqa`` (no codes) suppresses every rule on the line.
    A ``# noqa: CHU006, CHU012`` suppresses each listed code.
    """
    for pattern in _NOQA_PATTERNS:
        match = pattern.search(line)
        if match is None:
            continue
        codes = match.group(1)
        if codes is None or codes.strip() == "":
            return True
        if code in {token.strip() for token in codes.split(",")}:
            return True
    return False


def strip_noqa(line: str) -> str:
    """Return *line* with every noqa directive removed.

    Useful when a rule's pattern would itself match a CHU code embedded
    in a noqa marker (CHU006's "no CHU codes in prose" rule needs the
    marker stripped before searching, otherwise ``# noqa: CHU006`` would
    self-flag).
    """
    for pattern in _NOQA_PATTERNS:
        line = pattern.sub("", line)
    return line
