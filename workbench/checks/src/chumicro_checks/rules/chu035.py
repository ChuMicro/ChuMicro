"""CHU035: example helpers.py copies stay byte-identical to the template.

Every network-using library ships a copy of ``examples/helpers.py``
(wifi-up, runtime-config load, inline msgpack decode, ticks math).  The
copies must not drift from each other: a fix to the CYW43 whitelist or
the msgpack decoder has to land in all of them, and a comment-audit pass
on one copy silently forks it from the rest.

The canonical body lives at ``scripts/templates/examples_helpers.py``.
The new-library scaffold emits that file into a fresh library, and this
rule fails preflight the moment any managed copy stops matching it
byte-for-byte, naming the file that diverged.

Managed copies:

- Each existing ``libraries/<name>/examples/helpers.py``.  A library
  without one is fine: not every library ships wifi examples, and the
  file's own docstring tells non-network libraries to delete it.
- The scaffold payload
  ``workbench/workspace/src/chumicro_workspace/_payloads/library_template/helpers.py.template``,
  which the scaffold writes verbatim.  Guarding it keeps a freshly
  scaffolded library from emitting a stale copy.

Self-scope: the rule reads ``scripts/templates/examples_helpers.py``
under *repo_root*.  Absent (a downstream workspace that vendored the
libraries but not the template), it returns no findings, a silent no-op.

Suppression: none per-line.  A copy either matches the template or it
does not; resync it rather than annotating the divergence.
"""

from __future__ import annotations

from pathlib import Path

from chumicro_checks._finding import Finding
from chumicro_checks._rule import Rule

_RULE_CODE = "CHU035"

_TEMPLATE_RELPATH = Path("scripts") / "templates" / "examples_helpers.py"
_PAYLOAD_RELPATH = (
    Path("workbench") / "workspace" / "src" / "chumicro_workspace"
    / "_payloads" / "library_template" / "helpers.py.template"
)


def _managed_copies(repo_root: Path) -> list[Path]:
    """Return every example-helper copy the template governs, in sorted order.

    The list is each existing ``libraries/<name>/examples/helpers.py``
    plus the scaffold payload template when present.  Missing files are
    skipped so a library without wifi examples produces no finding.
    """
    copies: list[Path] = []
    libraries_dir = repo_root / "libraries"
    if libraries_dir.is_dir():
        for library_dir in sorted(libraries_dir.iterdir()):
            helper_path = library_dir / "examples" / "helpers.py"
            if helper_path.is_file():
                copies.append(helper_path)
    payload_path = repo_root / _PAYLOAD_RELPATH
    if payload_path.is_file():
        copies.append(payload_path)
    return copies


def _display_path(filepath: Path, repo_root: Path) -> str:
    """Return *filepath* rendered relative to *repo_root* for the message.

    Every path this rule builds is rooted at *repo_root* (the template,
    the payload, each ``libraries/<name>/examples/helpers.py``), so the
    relative form always resolves.
    """
    return str(filepath.relative_to(repo_root))


class CHU035_ExampleHelperDrift(Rule):
    code = _RULE_CODE
    description = (
        "example helpers.py copies must stay byte-identical to "
        "scripts/templates/examples_helpers.py"
    )

    def check(self, repo_root: Path) -> list[Finding]:
        template_path = repo_root / _TEMPLATE_RELPATH
        if not template_path.is_file():
            return []
        try:
            reference_bytes = template_path.read_bytes()
        except OSError:
            return []

        template_display = _display_path(template_path, repo_root)
        findings: list[Finding] = []
        for copy_path in _managed_copies(repo_root):
            try:
                copy_bytes = copy_path.read_bytes()
            except OSError:
                continue
            if copy_bytes != reference_bytes:
                findings.append(
                    Finding(
                        path=copy_path,
                        line=1,
                        code=_RULE_CODE,
                        message=(
                            f"{_display_path(copy_path, repo_root)} diverges "
                            f"from the canonical example helper "
                            f"{template_display}; resync it byte-for-byte "
                            f"(every copy must match the template the "
                            f"scaffold emits)"
                        ),
                    ),
                )
        return findings


CHU035 = CHU035_ExampleHelperDrift()
