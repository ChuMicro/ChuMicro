# Decision 0113: Comment/docstring-only changes are not release-relevant

Status: `accepted`
Date: `2026-07-18`
Summary: A source change limited to comments and docstrings (including attribute docstrings) is not release-relevant; check-version compares docstring-stripped ASTs and requires no VERSION bump.
Related: Decision [0002](0002-per-library-version-files.md) (per-library VERSION enforcement), [0021](0021-docstring-type-policy.md) (docstring policy).

## Context

`check-version` (Decision 0002) requires a VERSION bump whenever a publishable package's `src/` or `pyproject.toml` changes. It keyed purely on the changed file's path, so a repo-wide docstring or comment cleanup tripped the gate for every library it touched, even though such a pass ships no behavior change. Forcing a patch bump (and a release) per library for a comment edit is churn the gate exists to prevent, not to cause. A docstring pass that trues up the API reference is exactly the shape Decision 0021 asks for, and it should not gate a release on its own.

## Decision

A change to a `src/*.py` file whose diff is limited to comments and docstrings does not require a VERSION bump. `check-version` decides this structurally, not textually:

- It parses the file at the diff base and at the working tree, removes every bare string-literal statement from both ASTs (module, class, and function docstrings, plus PEP 258 attribute docstrings that follow a constant assignment), and compares the two `ast.dump` outputs. Comments never reach the AST, so a comment-only edit already compares equal; stripping bare strings extends that to docstrings.
- A bare string-literal statement is a runtime no-op, so removing it is behavior-preserving: two files equal after the strip differ only in comments and docstrings.
- The exemption is scoped to `.py` files under `src/`. `pyproject.toml` and non-`.py` `src/` payloads (data files) are never exempt, and a syntax error in either version falls back to "release-relevant" so the gate stays conservative.

A string literal that is not a docstring stays release-relevant. A change to a raised exception's message, a logged line, or any other shipped string is a behavior change and still demands a bump.

## Rejected

- **Exempting all string-literal changes.** A user-facing exception message or log line is shipped output; changing its text is a behavior change a consumer can observe. Only bare docstring/attribute-docstring strings are no-ops.
- **A textual diff heuristic** (e.g. "every changed line starts with `#` or lives inside a triple-quoted block"). Brittle against reflowed docstrings, string concatenation, and comments that share a line with code. The AST comparison is exact.
- **Dropping the gate to comment-density tooling.** The bump gate and the docstring-style checks answer different questions; this narrows the bump gate, it does not delegate it.

## Consequences

- A pure docstring/comment cleanup across many libraries no longer forces a bump-and-release for each; only libraries with a real code or shipped-string change do.
- `check-version` now reads file contents at the diff base (`git show`) and the working tree, where before it only inspected paths. The read is confined to `src/*.py` files that changed.
- The distinction is testable in isolation: `_code_is_equivalent` is unit-tested against docstring, attribute-docstring, comment, real-code, and shipped-string edits.
