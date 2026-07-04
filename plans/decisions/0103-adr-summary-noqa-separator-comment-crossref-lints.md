# Decision 0103: Mechanize the ADR summary, noqa separator, and comment cross-reference contracts

Status: `accepted`
Date: `2026-07-04`
Summary: Three lints mechanize prose contracts: CHU029 requires a non-empty ADR `Summary:` (<=200 chars), CHU031 pins the noqa separator to space-hyphen-space, CHU032 flags pointer phrases in comments.
Related: Decision [0074](0074-drift-mechanization-as-project-policy.md) (lintable drift must be mechanized), Decision [0079](0079-prose-drift-mechanization.md) (the prose-drift engines these three extend), Decision [0060](0060-chu-rules-home.md) (`chumicro-checks` rule home), [`plans/decisions/README.md`](README.md) (the `Summary:` contract CHU029 enforces), [`AGENTS.md`](../../AGENTS.md) ("Code comments", the rule CHU032 enforces).

## Context

Decision 0079 built the two prose-drift engines and codes CHU020 and CHU024–028, but three later contracts stayed review-only. Decision 0074 binds the response: a contract whose violation is deterministically detectable does not get to rely on an agent keeping prose in lockstep. This records the three post-0079 codes; 0079 owns the engine taxonomy they sit in.

## Decision

- **CHU029 — every ADR carries a machine-extractable `Summary:`.** The SessionStart hook surfaces each ADR's `Summary:` so an agent landing in a session sees what was *decided*, not just the filename slug; a missing, empty, or runaway field silently hollows that surface. The rule requires a `Summary:` line in the frontmatter window, non-empty, at most 200 characters — the cap the hook's output budget was sized for across the corpus. It mechanizes the template contract in `plans/decisions/README.md`. Scope is `<repo>/plans/decisions`; a silent no-op in a downstream workspace.
- **CHU031 — one separator for suppression explanations.** A `# noqa: CODE` or `# pragma: no cover` that carries a trailing explanation joins it with space-hyphen-space; em-dash, en-dash, and double-hyphen are the drift class flagged. One convention across the publishable trees keeps suppression comments grep-able and reading identically in every package. The parenthetical form and bare directives are left alone. This is the AGENTS.md writing-tone em-dash guidance mechanized for the one inline surface where the target is a closed set.
- **CHU032 — comments stand alone for a cold reader.** The AGENTS.md "Code comments" non-negotiable forbids "see `X`'s docstring", "documents the rationale", "follows the pattern in X" — a consumer who installed off PyPI has the shipped source, not the sibling file the pointer names. CHU032 mechanizes exactly that closed set of pointer phrases. It deliberately does not flag a bare dependency mention or a fake naming its real type (those state an architectural fact, not a "go read another file"); the judgment half — is this comment self-contained? — stays with `/audit-comments` and reviewer.
- **One record, three rules.** The three share one principle (Decision 0074's "a lintable prose contract gets a deterministic CHU behind a `# noqa` escape") and one home (Decision 0079's taxonomy). Three separate ADRs would restate that shared principle three times — the cross-ADR duplication CHU028 exists to catch.

## Rejected

- **Trusting review to hold each contract** — Decision 0074 forbids it once the class is lintable.
- **An unbounded ADR `Summary:`** — blows the session hook's fixed output budget; hence the 200-character cap rather than no cap.
- **Flagging every cross-file mention in CHU032** — fires on hundreds of legitimate dependency lines; the broad framing is semantic and stays with `/audit-comments`, the same line 0079 drew for CHU021/022.
- **A per-code AGENTS.md entry or a fourth status** — the rule docstrings are the live index (Decision 0060); the principles already live in the README and AGENTS.md, one home each.

## Consequences

- `chumicro-checks` carries CHU029 (a single-purpose ADR walker) plus CHU031 and CHU032 (closed-set pattern matchers), each `# noqa`-escapable.
- Every new ADR's `Summary:` is now a gate, not a convention — including this one.
- These lints never touch a board: `chumicro-checks` is CPython-only (Decision 0032) and runs in preflight and CI.
- A new drifted-and-shipped prose contract is, by Decision 0074, the next such candidate; "fix the prose" stays incomplete while the class is a closed set that recurs.
