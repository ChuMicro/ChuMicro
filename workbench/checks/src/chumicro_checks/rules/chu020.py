"""CHU020 — closed AI-tic phrase set in user-facing prose.

The AGENTS.md "Writing tone" non-negotiable enumerates a small set of
phrases that drop information without adding any.  The five adjectives
(``comprehensive``, ``robust``, ``seamlessly``, ``cutting-edge``,
``best-in-class``) and three sentence-opener filler phrases (``It is
worth noting that``, ``It should be noted that``, ``Let's dive into``,
``Let's explore``, ``In this section, we will``) recur in agent-
generated prose; lint catches them where prose lockstep does not.

The exemption is paired-delimiter quotation: a phrase that sits between
matching backticks, single quotes, double quotes, or any one of those
delimiters paired with a bold/italic wrapper (the AGENTS.md "Writing
tone" ban list itself uses ``**"X"**``) is data, not assertion.  That
keeps the rule off the very documentation that names what it bans.

``Note that`` is intentionally NOT in the matcher.  ``\\bNote that\\b``
fires on legitimate technical prose (``Note that the API requires a
trailing slash``); the FP rate makes a noqa-heavy rule that hollows
itself out.  The AGENTS.md prose rule covers it; lint stays narrow.

Scope: ``AGENTS.md``, ``docs/``, and ``plans/decisions/`` — same as
CHU017.  The churny ``plans/next-up`` ledger, workstreams, and library
READMEs are out of scope (drift-prone journal prose, not contract).

Suppression: ``<!-- noqa: CHU020 -->`` on the offending line.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU020"

_ADJECTIVES = re.compile(
    r"\b(?:comprehensive|robust|seamlessly|cutting-edge|best-in-class)\b",
    re.IGNORECASE,
)
_SENTENCE_OPENERS = re.compile(
    r"\b(?:It is worth noting that|It should be noted that|"
    r"Let's dive into|Let's explore|In this section, we will)\b",
    re.IGNORECASE,
)

_QUOTE_DELIMS = ("`", "'", '"')


def _is_paired_quoted(line: str, match_start: int, match_end: int) -> bool:
    """True when the match sits between paired quote / backtick delimiters.

    Counts each delimiter occurring before the match; an odd count means
    we're inside an open pair.  Also requires the same delimiter to
    appear again somewhere after the match so we know a close is coming.
    """
    for delim in _QUOTE_DELIMS:
        before = line[:match_start].count(delim)
        after = delim in line[match_end:]
        if before % 2 == 1 and after:
            return True
    return False


def _scan_roots(repo_root: Path) -> list[Path]:
    roots: list[Path] = []
    agents = repo_root / "AGENTS.md"
    if agents.is_file():
        roots.append(agents)
    for relative in ("docs", "plans/decisions"):
        candidate = repo_root / relative
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def _check_file(filepath: Path) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_suppresses(line, _RULE_CODE):
            continue
        for pattern, message in (
            (_ADJECTIVES, "AI-tic adjective — name what the thing covers / survives instead"),
            (_SENTENCE_OPENERS, "AI-tic sentence opener — just say the thing"),
        ):
            for match in pattern.finditer(line):
                if _is_paired_quoted(line, match.start(), match.end()):
                    continue
                findings.append(
                    Finding(
                        path=filepath,
                        line=line_number,
                        code=_RULE_CODE,
                        message=f"{message} (`{match.group(0)}`)",
                    )
                )
    return findings


class CHU020_AiTicPhrases(Rule):
    code = _RULE_CODE
    description = (
        "closed AI-tic phrase set — drop unfounded adjectives and "
        "sentence-opener filler from user-facing prose"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for root in _scan_roots(repo_root):
            for filepath in iter_text_files(root, suffixes=(".md",)):
                findings.extend(_check_file(filepath))
        return findings


CHU020 = CHU020_AiTicPhrases()
