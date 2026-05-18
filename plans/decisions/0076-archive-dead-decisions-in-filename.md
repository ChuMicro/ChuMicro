# Decision 0076: A dead decision announces itself in its filename

Status: `accepted`
Date: `2026-05-18`
Related: Decision 0074 (lintable drift must be mechanized — CHU019 enforces this), `plans/decisions/README.md` (the supersession / edit-in-place rules this extends), `plans/workstreams/adr-corpus-hygiene.md` (the audit that surfaced it).

## Context

Session start scans the decision corpus by `ls plans/decisions/` —
the filename *is* the index. At 75 records, dead decisions (replaced
or spent) sit in that index indistinguishable from live ones. A reader
narrowing to a candidate `head`s or reads it before discovering it no
longer describes the repo. The cost is paid every session, by every
reader, forever, and grows with the corpus.

`superseded` already exists as a status, but status lives *inside* the
file — a flat `ls` doesn't show it, so it doesn't prune the index.
Spent bootstrap decisions (e.g. 0004, whose every deferred seam has
shipped) aren't `superseded` by any specific ADR at all; they are
simply no longer load-bearing, and the four-status enum has no value
for that — correctly, because "spent" is not a decision *state*.

## Decision

**A decision record that no longer describes current repo state must
announce that in its filename, so the index reader skips it without
opening it.** The invariant is reader-cost, not a particular token.

Two dead classes, two filename markers, inserted immediately after the
number prefix so the number — and therefore the index order and the
`new-decision` next-number recipe — is untouched:

- **Replaced** → `Status: superseded`, a `Superseded by:` line, body
  frozen (existing README rule), and filename
  `NNNN-SUPERSEDED-BY-MMMM-<slug>.md`. The marker names the successor,
  so the reader learns *what to read instead* from the `ls` alone.
- **Spent / inert** → `Status:` stays `accepted` (no fifth status; the
  decision was still validly made), plus an `Archived: inert — <why>`
  header field and filename `NNNN-INERT-<slug>.md`.

A reader scanning the index sees the lifecycle in the filename and
skips dead records without a file open. The topic slug is retained
after the marker, so the index still carries the topic.

This is orthogonal to status: archiving is a *location signal in the
name*, not a decision-state. Inert records stay `accepted`; superseded
records keep the status they already had.

**Rejected:**

- *Move dead ADRs to `plans/decisions/archive/`.* Breaks every
  relative cross-link in both directions, and silently breaks the
  `new-decision` next-number recipe (`ls … | tail -1`) so numbers get
  reused. The filename marker keeps the `NNNN-` prefix in place and
  costs only the inbound *filename* links to the renamed file (audit
  blast radius across the whole repo: one).
- *Status field only, no filename change.* Leaves the flat `ls` index
  exactly as noisy — it does not satisfy the requirement that the
  index reader skip dead records *without opening them*.
- *A fifth status (`archived` / `inert`).* The README is emphatic the
  enum is four values; "spent" is not a state a decision is *in*. An
  orthogonal header field plus the name marker carries it without
  corrupting the enum.

## Consequences

- Session-start step 3 (AGENTS.md) and `decisions/README.md` instruct
  the reader to skip a `SUPERSEDED-BY` / `INERT` filename unless
  tracing history.
- The `new-decision` skill gains the rename step for when an ADR is
  superseded or goes inert, and a note that the next-number recipe is
  unaffected (prefix preserved).
- **CHU019** mechanizes the contract per Decision 0074: status,
  marker, and header field must agree, and number prefixes stay unique
  — a renamed-but-not-restatused ADR (or the inverse) is a lint
  failure, not a thing a future reader has to notice.
- Filenames lengthen for dead records. Intended: the loudness in `ls`
  is the feature.
- First batch applied with this decision: 0035 (superseded by 0036),
  0004 (inert), 0006 / 0008 (already superseded, marker added). 0005
  is a flagged inert candidate pending sign-off (see the workstream).
