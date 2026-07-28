"""CHU012: no dated narration or workstream-phase pointers in code.

Code comments document the *why* of current code, nothing else.
Dated incidents, removed-code framing, and workstream-phase pointers
belong in the commit message, the ADR body, or the workstream file.
All reachable via ``git log`` and ``plans/``.

The walker covers every ``.py`` and ``.md`` file under ``libraries/``,
``workbench/``, ``support/``, and ``scripts/``.  ``plans/`` is
journal-shaped by intent and excluded.

Self-scope: the rule walks paths under the repo root.  In a tree
without any of those top-level directories (a downstream user
workspace), it returns no findings, a silent no-op.
"""

from __future__ import annotations

import re
from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._noqa import line_suppresses, strip_noqa
from chumicro_checks._rule import Rule
from chumicro_checks._walker import iter_text_files

_RULE_CODE = "CHU012"

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"\b(?:Surfaced|Discovered|Observed|Captured|Caught|shipped|landed) "
            r"\d{4}-\d{2}-\d{2}\b",
        ),
        "dated incident: move to commit message or workstream file",
    ),
    (
        re.compile(r"\bverified (?:live|on hardware) \d{4}-\d{2}-\d{2}\b", re.IGNORECASE),
        "dated verification: move to commit message or workstream file",
    ),
    (
        re.compile(
            r"\b(?:live-tested|bench-tested) on [^\n]{1,40}\d{4}-\d{2}-\d{2}\b",
            re.IGNORECASE,
        ),
        "dated verification: move to commit message or workstream file",
    ),
    (
        re.compile(r"\b(?:Phase|Step|Slice)\s+\d+[a-z]?\b[^\n]{0,80}\bworkstream\b"),
        "workstream-phase pointer: move to commit message or workstream file",
    ),
    (
        re.compile(r"\bworkstream\s+Phase\s+\d+[a-z]?\b"),
        "workstream-phase pointer: move to commit message or workstream file",
    ),
    (
        # Slice N: workstream-only jargon in this codebase (no
        # procedural meaning), so match every numbered occurrence.
        re.compile(r"\bSlice\s+\d+[a-z]?\b"),
        "workstream-phase pointer: move to commit message or workstream file",
    ),
    (
        # Phase|Step N when NOT followed by a colon. Procedural
        # numbered steps ("# Step 1: put the board in bootloader mode")
        # use the colon and stay clean.
        re.compile(r"\b(?:Phase|Step)\s+\d+[a-z]?\b(?!\s*:)"),
        "workstream-phase pointer: move to commit message or workstream file",
    ),
    (
        # Item N: multi-item workstream shape. No procedural usage
        # exists in this codebase.
        re.compile(r"\bItem\s+\d+[a-z]?\b"),
        "workstream-phase pointer: move to commit message or workstream file",
    ),
    (
        # F-numbered finding within ~80 chars of an ISO date.
        re.compile(r"\bF\d+\b[^\n]{0,80}\b\d{4}-\d{2}-\d{2}\b"),
        "dated verification finding: move to commit message or workstream file",
    ),
    (
        re.compile(r"\bverification\s+finding\s+#?\d+(?:,\s*\d{4}-\d{2}-\d{2})?\b"),
        "dated verification finding: move to commit message or workstream file",
    ),
    (
        re.compile(r"\b\d{4}-\d{2}-\d{2}\s+verification\s+(?:pass|finding)\b"),
        "dated verification pass: move to commit message or workstream file",
    ),
    (
        re.compile(r"\bRegression for \d{4}-\d{2}-\d{2}\b"),
        "dated incident: move to commit message or workstream file",
    ),
    (
        # Verb-less dated-incident phrasings like "the 2026-05-09
        # audit". The verb-prefixed patterns above don't match these
        # because there is no leading verb to anchor on.
        re.compile(
            r"\bthe \d{4}-\d{2}-\d{2}\s+"
            r"(?:audit|sweep|incident|pass|investigation|review|finding)\b",
        ),
        "dated incident: move to commit message or workstream file",
    ),
    (
        re.compile(r"\bin the [a-z]+-[a-z]+(?:\s+[a-z]+){0,2}\s+(?:pass|audit|sweep|bake)\b"),
        "workstream-phase pointer: move to commit message or workstream file",
    ),
    (
        re.compile(r"\b(?:Earlier versions|Previously,?\s+th(?:is|e)|We used to|Used to be)\b"),
        "removed-code framing: move to commit message or workstream file",
    ),
    (
        # "X retained only until Y lands|landed": roadmap framing
        # for a thing kept around pending future work.
        re.compile(r"\bretained (?:only )?until\b[^\n]{0,80}\b(?:lands?|landed)\b"),
        "dateless landed-history framing: move to commit message or workstream file",
    ),
    (
        # "before X landed": past-tense framing of a prior incident.
        re.compile(r"\bbefore [^\n]{1,80}\blanded\b"),
        "dateless landed-history framing: move to commit message or workstream file",
    ),
    (
        # "deferred until ...": future-work / roadmap framing.
        re.compile(r"\bdeferred until\b"),
        "deferred-work framing: move to commit message or workstream file",
    ),
    (
        # "until we have a|an X": roadmap framing for a future capability.
        re.compile(r"\buntil we have (?:a|an)\b"),
        "deferred-work framing: move to commit message or workstream file",
    ),
)

_SCANNED_SUFFIXES = (".py", ".md")

#: The lint's own source + tests carry the forbidden patterns as regex
#: literals and fixture strings.  Paths are repo-root-relative.
_SELF_EXEMPT_RELPATHS: frozenset[Path] = frozenset({
    Path("workbench/checks/src/chumicro_checks/rules/chu012.py"),
    Path("workbench/checks/tests/test_chu012.py"),
})

_SCAN_TOP_LEVELS = ("libraries", "workbench", "support", "scripts")


def _is_self_exempt(filepath: Path, repo_root: Path) -> bool:
    try:
        relative = filepath.relative_to(repo_root)
    except ValueError:
        return False
    return relative in _SELF_EXEMPT_RELPATHS


def _scan_roots(repo_root: Path) -> list[Path]:
    """Return the directory roots to scan recursively under *repo_root*.

    Covers both the chumicro mono-repo's per-package layout
    (``libraries/<pkg>/`` + ``workbench/<pkg>/``) and the
    workspace-template's top-level user-content trees
    (``packages/``, ``projects/``, ``shared/``, ``examples/``,
    root ``tests/``).  Trees that don't exist in the current repo
    are silently skipped.
    """
    roots: list[Path] = []
    for parent_name in ("libraries", "workbench"):
        parent_dir = repo_root / parent_name
        if not parent_dir.is_dir():
            continue
        for package_dir in sorted(parent_dir.iterdir()):
            if package_dir.is_dir():
                roots.append(package_dir)
    for top_level in (
        # Mono-repo top-levels.
        "support", "scripts",
        # Template / workspace top-levels.
        "packages", "projects", "shared", "examples", "tests",
    ):
        top_dir = repo_root / top_level
        if top_dir.is_dir():
            roots.append(top_dir)
    return roots


def _check_file(filepath: Path, repo_root: Path) -> list[Finding]:
    if _is_self_exempt(filepath, repo_root):
        return []
    try:
        text = filepath.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []

    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line_suppresses(line, _RULE_CODE):
            continue
        scrubbed = strip_noqa(line)
        for pattern, message in _PATTERNS:
            if pattern.search(scrubbed):
                findings.append(
                    Finding(
                        path=filepath,
                        line=line_number,
                        code=_RULE_CODE,
                        message=message,
                    )
                )
                break
    return findings


class CHU012_DatedNarration(Rule):
    code = _RULE_CODE
    description = (
        "no dated narration / workstream-phase pointers in code comments"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        roots = _scan_roots(repo_root)
        if not roots:
            return []
        findings: list[Finding] = []
        for root in roots:
            for filepath in iter_text_files(root, suffixes=_SCANNED_SUFFIXES):
                findings.extend(_check_file(filepath, repo_root))
        return findings


CHU012 = CHU012_DatedNarration()
