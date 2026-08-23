---
paths:
  - "**/*.py"
---

# Comments and docstrings

- Open by naming the concrete thing: the actual function, method, class, or value. Never an abstract stand-in like "the adapter" or "the algorithm". Then state in plain words what it does or returns, for a reader who has not read the code. The non-obvious why comes after that.
- A test docstring describes what the asserts check, not what the test name aspires to. `so`, `because`, and `therefore` require causation visible in the test body; independent checks join with `and`.
- Never name a private helper's callers. A helper does not know who calls it.
- Every comment stands alone for a cold reader of its own file. No "see `module`'s docstring", no ":mod:`other` documents the rationale", no "follows the pattern in X", no sibling-library or upstream-repo name (`CHU032`). A PyPI consumer has the shipped source, not the file you pointed at.
- Never duplicate rationale across modules. Rationale that fits more than one module is project policy: put it in AGENTS.md or an ADR and delete every copy (`CHU027`).
- A comment documents the why of current code. No history, no dated incidents, no removed-code explanations, no workstream pointers. History belongs in the commit message; durable rationale belongs in an ADR.
- Never record an audit finding in a comment. Per-change justification, before/after numbers, and sweep narrative go in the commit body.
- When prose and code disagree, the code wins; fix the prose. The exception is prose encoding intent the code lost (a regressed feature, a claim never implemented): stop and ask which side is correct.
- A degraded comment is deleted and rewritten from a fresh read of the code, never trimmed again.
- Device deploys strip docstrings and comments from every staged `.py` ([Decision 0090](../../plans/decisions/0090-deploy-strips-docstrings-and-comments.md)). Compare against the repo source, and never rely on `__doc__` in library code.
