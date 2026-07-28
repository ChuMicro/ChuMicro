"""``noqa`` directive parsing, shared between every rule that supports
per-line suppression.

Two suppression syntaxes are recognized:

* ``# noqa: CHU0NN``: Python, TOML, INI, anywhere a ``#`` line comment
  is valid.
* ``<!-- noqa: CHU0NN -->``: Markdown.

Both forms accept a comma-separated list of codes (``# noqa: CHU006,
CHU012``) and a bare form (``# noqa``) that suppresses every code.

The ``noqa`` token must stand alone: after it (or after its code
list) comes whitespace, a second ``#`` comment, or end of line.  Prose
that merely starts with ``noqa`` is not a directive and suppresses
nothing: ``# noqa-tracking``, a ```` `# noqa` `` `` mention in Markdown,
and ``.noqa`` in a path all read as ordinary text.
"""

from __future__ import annotations

import re

_NOQA_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"#\s*noqa(?::\s*([A-Z0-9, ]+))?(?=[\s:#]|$)"),
    re.compile(r"<!--\s*noqa\b(?::\s*([A-Z0-9, ]+))?\s*-->"),
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


def has_noqa(line: str) -> bool:
    """Return True when *line* carries any noqa directive, code-listed or bare.

    A rule whose carve-out exempts every suppression line (a
    suppression explanation legitimately names its duplicate's home)
    skips the line outright instead of asking whether its own code is
    listed.
    """
    return any(pattern.search(line) is not None for pattern in _NOQA_PATTERNS)


def strip_noqa(line: str) -> str:
    """Return *line* with every noqa directive removed.

    Useful when a rule's own match pattern would itself match content
    inside a noqa marker. Strip the marker before searching so a line
    carrying ``# noqa: CHU0NN`` doesn't self-flag against a rule that
    scans for CHU codes in prose.
    """
    for pattern in _NOQA_PATTERNS:
        line = pattern.sub("", line)
    return line
