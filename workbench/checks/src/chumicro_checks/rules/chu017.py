"""CHU017 — coverage-claim honesty.

The project's coverage gate is a *CPython-reachable, post-`# pragma:
no cover`* figure with **no device-execution signal** — explicitly
**not** "N % of shipped code".  An adversarial doc sweep found docs
citing the number as a whole-codebase guarantee anyway.  Prose
lockstep didn't catch it; this rule does.

It flags an **affirmative** coverage-percentage claim whose scope is
one of a closed set of codebase-extent overclaims (``shipped code``,
``the codebase``, ``all code``, ``every line``, ``fully covered``,
…) that the measurement does not support.

The false-positive guard is the exemption: a sentence that also
carries a negator (``not`` / ``never`` / ``rather than`` / ``n't``)
or an honest-scope qualifier (``CPython-reachable``,
``post-exclusion``, ``post-pragma``, ``device-execution``,
``reachable``, ``aggregate``) is the *corrected* or *meta* statement
of the contract, not drift — those are not flagged.  This is what
keeps the rule off the very ADR / AGENTS text that states the honest
scope.

Scope: ``AGENTS.md``, ``docs/``, ``plans/decisions/`` — where the
coverage contract and its claims live.  The churny ``plans/next-up``
ledger and workstreams are out of scope.  Absent → silent no-op.

Suppression: ``<!-- noqa: CHU017 -->`` on the offending line.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU017"

#: A 2–3 digit percentage.
_PERCENT = re.compile(r"\b\d{2,3}\s*%")

#: Codebase-extent scope phrases the CPython-reachable figure does
#: not support.  Closed set — affirmative overclaims only.
_OVERCLAIM = re.compile(
    r"shipped code"
    r"|the codebase|entire codebase|whole codebase"
    r"|all (?:the )?code\b"
    r"|production code|device code|on-device code"
    r"|every line\b"
    r"|fully covered|full(?:ly)? code coverage|complete coverage",
    re.IGNORECASE,
)

#: Sentence carries the honest scope, a negation, or is the meta
#: statement of the rule itself → not drift.
_EXEMPT = re.compile(
    r"\bnot\b|\bnever\b|rather than|n't\b|\bno\b"
    r"|CPython-reachable|post-exclusion|post-pragma|post-`# pragma"
    r"|device-execution|\breachable\b|\baggregate\b"
    r"|must carry|or be wrong|forbids|this scope",
    re.IGNORECASE,
)

#: Sentence terminators (markdown prose).
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n{2,}")


def _scan_relpaths(repo_root: Path) -> list[Path]:
    roots: list[Path] = []
    agents = repo_root / "AGENTS.md"
    if agents.is_file():
        roots.append(agents)
    for relative in ("docs", "plans/decisions"):
        candidate = repo_root / relative
        if candidate.is_dir():
            roots.append(candidate)
    return roots


def _line_of_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _check_file(filepath: Path) -> list[Finding]:
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if "%" not in text:
        return []
    source_lines = text.splitlines()
    findings: list[Finding] = []
    cursor = 0
    for sentence in _SENTENCE_SPLIT.split(text):
        start = text.find(sentence, cursor)
        if start == -1:
            start = cursor
        cursor = start + len(sentence)
        if not _PERCENT.search(sentence):
            continue
        overclaim = _OVERCLAIM.search(sentence)
        if overclaim is None:
            continue
        if _EXEMPT.search(sentence):
            continue
        line = _line_of_offset(text, start + overclaim.start())
        if line - 1 < len(source_lines) and line_suppresses(
            source_lines[line - 1], _RULE_CODE,
        ):
            continue
        findings.append(
            Finding(
                path=filepath,
                line=line,
                code=_RULE_CODE,
                message=(
                    f"coverage figure cited as {overclaim.group(0)!r} — the "
                    f"gate is a CPython-reachable, post-pragma figure with "
                    f"no device-execution signal; state that scope or drop "
                    f"the whole-codebase framing"
                ),
            )
        )
    return findings


class CHU017_CoverageClaimHonesty(Rule):
    code = _RULE_CODE
    description = (
        "coverage % must not be cited as a whole-codebase guarantee"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        findings: list[Finding] = []
        for root in _scan_relpaths(repo_root):
            for filepath in iter_text_files(root, suffixes=(".md",)):
                findings.extend(_check_file(filepath))
        return findings


CHU017 = CHU017_CoverageClaimHonesty()
