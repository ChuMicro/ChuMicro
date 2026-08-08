# CHU prose/isolation lint gaps

Parked analysis, not started. Three CHU-rule changes that close gaps
through which dateless history, mono-repo pointers, and a banned prose
tic currently pass a green lint. Surfaced while cleaning the deploy
package during deploy-path-unification Commit 2c, where all three
escaped preflight and reached human review.

**Do not implement from this file without the routing below.** #2 is
*not* the judgment-free mechanical add it first looked like (see the
verified correction). #1 and #3 widen behavior with false-positive
tradeoffs and route through `new-decision`.

## Source anchors (verified this pass, not relayed on trust)

- `workbench/checks/src/chumicro_checks/rules/chu006.py` — `_PATTERNS`
  is a `tuple[(re.compile(...), message, predicate)]` (line ~155).
  Predicates available: `everywhere`, `_outside_chumicro_checks`,
  `_outside_chumicro_workspace`, `_outside_runpy_owners`,
  `_under_subdir`. Self-reference is handled two ways already: the
  `plans/…` patterns use the `_outside_chumicro_checks` predicate; the
  bare-`run.py` pattern uses inline `# noqa: CHU006` on the pattern
  lines (chu006.py:177-178). Tests: `workbench/checks/tests/test_chu006.py`.
- `workbench/checks/src/chumicro_checks/rules/chu012.py` — `_PATTERNS`
  is `tuple[(re.Pattern, str)]` (line 29). Every dated-incident
  pattern requires `\d{4}-\d{2}-\d{2}`; removed-code framing (line 97)
  is verb-anchored: `\b(?:Earlier versions|Previously,?\s+th(?:is|e)|We
  used to|Used to be)\b`. Line 93 (`\bin the [a-z]+-[a-z]+…(?:pass|
  audit|sweep|bake)\b`) is an existing *dateless* pattern — precedent
  that a dateless rule can live in CHU012. Tests:
  `workbench/checks/tests/test_chu012.py`.

## Two-engine consolidation (added 2026-05-19)

#1–#4 below, plus the CHU020 closed-AI-tic item (next-up) and the
open-questions "dedup + date/SHA-token" rules, are not six independent
lints. They reduce to **two reusable deterministic engines**, plus two
newly-surfaced problem domains (#5, #6) and one anti-decision. Build
the engines once and feed them different inputs — that is itself the
"pattern shared by 3+ consumers → hoist it" shape; the alternative is
N parallel rule implementations, the cost 0074 exists to bound. None
of this is AI/ML — it is grep- and hash-class plumbing, deliberately
dumb (the 0074 thesis: the dumb mechanical rule held in 2c, the
judgment rule did not).

**Engine A — normalized-block dedup.** Tokenize comment/docstring (or
ADR-paragraph) blocks → normalize case/whitespace/punctuation → hash
blocks ≥ ~N tokens → flag a fingerprint recurring ≥3 sites/package or
≥2 cross-package (≥2 ADR files for the ADR consumer). Min-token floor
+ allowlist (license headers, `# noqa`, pragmas). No semantic
understanding — pure shape match, which is exactly why it is sound for
"pasted in 3 places" (the 2c mkfs failure) and useless for "is this
comment good" (that stays `/audit-comments` judgment).
  - Consumer 1 — `src/` comments/docstrings: the open-questions
    "cross-site duplicate block" rule, its highest-value half. Already
    analysed there; lift, do not re-derive.
  - Consumer 2 — `plans/decisions/*.md`: the 0038§3↔0075
    partial-supersession bloat (a corrected principle stated in full
    in two ADRs) is the same fingerprint-collision shape over ADR
    bodies. **Proposed, not yet verified** — picker-up must confirm
    cross-ADR prose dedup has acceptable precision (ADRs share
    template headings; the floor + allowlist must exclude scaffolding,
    and the 2026-05-19 de-bloat may already have cleaned every
    instance, making this a regression guard — still worth it). This
    is the mechanizable half of #5; the keep/merge/which-home call
    stays judgment (the networking-charter cluster was correctly *not*
    merged).

**Engine B — closed-set token/phrase match.** Deterministic
substring/regex over an *enumerated, closed* list, `# noqa`-escapable,
with the CHU006 quoted/ban-discussion exemption. This is what CHU006
already *is*; #2, #3, CHU020, the open-questions date/SHA/Decision-NNNN
token rule, and #5's ADR-section-marker list are all the same matcher
with different word lists. Build one closed-set matcher, feed it the
lists — not one rule per list. The per-list FP tradeoffs and
allowlists already recorded under #2/#3/CHU020 do not change;
consolidation is about *one implementation*, not relaxed precision.

Residue that does NOT mechanize (explicit per 0074's own logic, not by
omission): freeform postmortem narration (#1's "not cleanly lintable"
half), "narrating change vs explaining current why" (open-questions
rejects a regex), the keep/merge call on Engine-A hits, and the whole
core of #6. These stay review-time / `/audit-comments` / `/audit-skill`
judgment by design.

## #1 — CHU012 gap: dateless landed-history framing (highest value)

CHU012 already owns this family ("no dated narration or
workstream-phase pointers") but its removed-code/incident patterns are
date- or verb-anchored, so dateless history accumulates green. Real
examples cleaned out of the deploy package this pass:

- "the legacy additive shape, retained only until the clean-slate
  default lands"
- "now that the sentinel above blocks it" / "before the sentinel
  landed" / "before this reaping landed"
- "was bench-tested as racing on Pi Pico W MP" (no date → CHU012's
  `bench-tested` pattern, which requires a trailing date, misses it)
- "sweep-wide cascade", "1 s also worked but had no margin",
  "empirically the slowest … we've observed"

**Docstrings are in scope, not just inline comments.** Worked
example: `workbench/workspace/src/chumicro_workspace/cli/health.py`
`_cmd_doctor`'s pre-trim docstring carried "Per-device reachability
probes … are *deferred until* we have a hardware-cheap probe
primitive" — dateless deferred-work narration in a *docstring*,
passing lint today. The rule must scan docstrings (ast docstring
node) as well as `#` comments.

**Lintable subset:** the `X now that … / retained only until … /
before … landed|lands` shape **plus the `deferred until … / until we
have <capability>` roadmap shape** — tight deterministic regexes;
`\blanded\b` / `\bdeferred until\b` in genuine mechanism prose is
rare, so false-positive risk is low.
**Not cleanly lintable:** freeform postmortem narration ("sweep-wide
cascade", "no margin", "we've observed") — phrase-blocklisting that is
whack-a-mole; stays review-time judgment. Honest scope: add the
landed-history pattern to CHU012; do not attempt the freeform half.

Routing: `new-decision` — widens CHU012 behavior with a (small) FP
tradeoff worth recording.

## #2 — CHU006 gap: AGENTS.md / .scratch/ not patterned

`chu006.py._PATTERNS` matches `Decision NNNN`, `plans/*.md`,
`scripts/run.py`, bare `run.py`, "chumicro mono-repo", `CHU\d{3}` —
but **not** `AGENTS(\.notes)?\.md` / `CONTRIBUTING.md`, and **not**
`.scratch/`. That is why a shipped-tree `AGENTS.md` pointer
(`scaffold.py`) and a `.scratch/`-path pointer
(`mqtt/README.md:105` → `.scratch/run_mqtt_perf.py`, a dead pointer
for any consumer) sat under a passing lint.

**Verified correction to the original "zero legitimate use" framing —
the picker-up must not skip this:**

- `.scratch/` is **not** false-positive-free.
  `workbench/workspace/src/chumicro_workspace/example_source.py:31,32,82,158`
  uses `<secrets_toml>.parent/.scratch/…` as a *legitimate runtime
  artifact directory* under the user's own config — not a mono-repo
  dead pointer. A naïve `\.scratch/` pattern flags it wrongly. The
  pattern must be narrowed (e.g. only repo-relative `.scratch/`
  pointers, not `<path>.parent/.scratch/`) or those lines need
  `# noqa: CHU006`, or a predicate. The genuine leak to catch is the
  README-style "see `.scratch/foo.py`" pointer
  (`libraries/mqtt/README.md:105`).
- `AGENTS.md` / `CONTRIBUTING.md` as *data*: `chu008.py:14,54,55` and
  `chu017.py:23,73` are under `workbench/checks/` → exempt via the
  existing `_outside_chumicro_checks` predicate. But
  `template_zones.py:7,42,43` is under `workbench/workspace/` (NOT
  checks-exempt) and legitimately enumerates tool-owned template
  filenames including `AGENTS.md`/`CONTRIBUTING.md`. That needs a
  predicate or `# noqa: CHU006` on the data lines.

So #2 is a pure-addition *shape* (two rows into `_PATTERNS`, reuse the
walker/predicates/noqa) but carries real tuning: pick predicates,
narrow `.scratch/`, add noqa to the legitimate-data lines, and decide
whether `scaffold.py`'s `AGENTS.md` pointer is a source fix or a
reword. Closest of the three to mechanical, still not judgment-free.

Routing: `new-decision` (downgraded from "mechanical now" by the FP
finding above) — or at minimum a recorded scoping decision before
landing, because `.scratch/` narrowing is a real design choice.

## #3 — new rule: the "the (one|single|sole) X that/which/is" tic

No CHU rule covers prose AI-tics, yet AGENTS.md "Writing tone" bans
this shape and it has been flagged as a recurring tic to watch for. It bit twice this pass (`circuitpython_transport.py:967`,
`workbench/workspace/src/chumicro_workspace/cli/deploy.py:512`).
Deterministic regex, but real false positives: "the single source of
truth" (established term, `macos_fskit.py:59`), "the one belonging
to" (mechanism prose, `circuitpython_transport.py:700`). Lintable
only with a curated allow-list + `# noqa` escape.

Overlap to reconcile: `plans/open-questions.md` already carries
"Mechanize the comments document current-code why, not history" —
sharpened this pass to a dedup rule + a date/SHA-token rule, with the
freeform prose-sniffer explicitly rejected as judgment-bound. #1's
landed-history regex and #3's tic regex are cousins of that entry's
"reject the fuzzy sniffer, keep the tight lexical contract" position.
Whoever picks this up should fold the three views into one decision,
not three competing ones — the open-questions entry is the prior art.

Routing: `new-decision`, with the FP allow-list tradeoff recorded; not
a free add.

## #4 — absolute inline-comment cap per method body (asked; plausibly viable)

Two framings were discussed; keep them distinct — the picker-up must
not implement the weak one:

**Rejected framing — comment:code *ratio*.** Flag when comment lines
exceed code lines by some factor. Same noisy-proxy failure as #3's
rejected freeform half: even inline-only it *inverts* — a 3-line
hardware-quirk workaround legitimately carrying 15 lines of "why" is
exactly what AGENTS.md endorses, so the ratio fires hardest where
density is correct and trains blind suppression. Do not build the
ratio.

**Length is not the discriminator, and "docstring ⇒ exempt" is
wrong.** An earlier draft of this section claimed a long docstring on
a short method is categorically correct public-API doc and docstrings
should be wholesale-excluded. That was an overcorrection, disproved
by `_cmd_doctor` (`cli/health.py`): a thin private dispatcher whose
*pre-trim* docstring re-documented its callees and narrated deferred
work — bloat, not contract. But the in-repo *trimmed* form is a tight
6-line contract docstring on the same 4-line body and is correct — so
raw length does not discriminate either. The lintable component of
docstring bloat is the **#1 history/roadmap content applied to
docstrings** (deferred-work, "until X lands"); the non-lintable
component (re-documenting callees / restating what belongs on the
called functions) is `audit-library` judgment, not a deterministic
gate. Neither is a length rule.

**Recommended framing — absolute inline-comment-line cap inside a
`FunctionDef` body, regardless of code length, `# noqa`-escapable.**
This is a different and stronger rule: a body carrying more than N
inline `#` lines is over-narrated whatever its code size (the 4-line
case is the most flagrant instance of the one defect, not a separate
rule). The escape is the project's own philosophy, not a loophole —
AGENTS.md already requires every `# noqa` carry a one-line why, so a
legitimately comment-dense function (a real hardware/runtime quirk)
carries an explicit, auditable `# noqa: CHUNNN — <why>`. The rule
converts implicit over-commenting into a forced, reviewed decision at
the threshold — genuine mechanization, the inverse of the ratio's
"fires where density is correct."

Detection is deterministic: `ast` gives each `FunctionDef`'s body
span and its docstring node (exclude it); `tokenize.COMMENT` tokens
intersected with the body span give the inline-comment count. Count
only comments inside the function body, not module/class level.

Named risk (not a blocker): **the threshold N must be measured, not
guessed.** Calibrate against the actual inline-comment-per-body
distribution across `libraries/` + `workbench/` — too low → every
gnarly function noqa's (suppression fatigue, the failure that hollows
a rule); too high → catches nothing. The deploy transport already has
legitimate long ordering/wedge-risk comment runs ("Order is
load-bearing…"); those are the calibration set.

Routing: `new-decision` like #1/#3, with an explicit "measure the
distribution before fixing N" step recorded as part of the decision.
Pairs naturally with the cross-site dedup rule (the other half of the
real 2c defect was *duplication*, not just per-body volume).

**Best-built variant — a conjunctive structural predicate — and why
it is a #1 prefilter, not a standalone rule.** Proposed shape: flag a
function when `docstring+comments ≥ 3× code` AND no `Args:`/`Returns:`
block AND not a Protocol / `@property` / `@abstractmethod` body. The
`Args:`/`Returns:`/protocol carve-outs are real precision — they
exempt the *structured-contract* legitimate class by construction.
But "exempts the legitimate long docs by construction" is disproved
by the *parameterless-mechanism-why* class, verified:
`circuitpython_transport.py:_disable_autoreload_before_drive_writes`
— 3-line body, ~13-line docstring (≈4.3×), only `self`, `-> None`,
not protocol/property/abstract → **all three conjuncts fire**, yet
the docstring is the canonically correct load-bearing ordering/wedge
"why" AGENTS.md endorses, with zero history/roadmap content. It is
**structurally identical** to `_cmd_doctor`-before (thin body, long
prose docstring, no Args/Returns, not protocol/property/abstract);
the only difference is *content* (callee-restatement + deferred-work
vs current-mechanism-why), which the structural conjuncts cannot see.
This shape is common across the quirk-dense transport layer — the
code that most legitimately needs it.

Conclusion: the structural predicate cannot be the defect signal
(structure does not discriminate bloat from correct dense-why). Its
correct role is a **high-precision prefilter that raises #1's
confidence and priority**: `volume ≥3× AND no Args/Returns AND not
protocol/property/abstract AND contains a #1 history/roadmap marker`.
Drop the last conjunct and it flags `_disable_autoreload`. So #4 is
not an independent rule — it is a precision/priority gate layered on
#1's content patterns. Record it inside #1's decision as an optional
prioritization filter, not as its own rule.

## #5 — ADR-authoring discipline (new 2026-05-19)

Commit-evidence of repeat non-adherence: the 2026-05-19 ADR de-bloat
(`165c9331`) existed *because* the in-place-edit / one-invariant-one-
home rules were violated (0038§3↔0075 stated in full twice; 0079
minted to restate a corrected rule), and `59ee9f36` had to *add*
"read the decisions README before any ADR work" as a forcing function.

Mechanizable halves:
- **Banned ADR section markers — Engine B list.** Closed set of
  history-banner shapes the in-place-edit rule forbids: `## Update (`,
  `Amended by`, `This was revised`, `## Changelog`, a `SUPERSEDED-BY`
  marker used *in addition to* (not instead of) an in-place edit.
  Scope `plans/decisions/*.md`. **Proposed, not yet verified** —
  picker-up greps `plans/decisions/` first to confirm the set is real
  and low-FP (the de-bloat may have cleaned every instance → this
  becomes a regression guard, still worth it).
- **Superseded-pointer integrity — small structural check.** Every
  ADR carrying `SUPERSEDED-BY-NNNN` names an existing target; no
  dangling pointer; no ADR both `accepted` and superseded. Near-zero
  FP.
- **Cross-ADR principle duplication — Engine A consumer 2** (above).

Not mechanizable: "genuine reasoning *shift* (new ADR) vs correction
of *wrong* reasoning (in-place edit)" — the core judgment the README
and AGENTS.md ADR hard-rules govern. Stays review-time; `new-decision`
is the process control, not a lint.

Routing: folded into the single decision covering the set — do **not**
mint a separate ADR for #5, that would itself be the #5 violation.

## #6 — AGENTS.md self-editing meta-rule (new 2026-05-19)

Commit-evidence: a five-commit oscillation — `53313cf6` trim →
`7f19a109` split-to-`AGENTS.notes.md` → `9f120743` restore + delete
the notes file → `9158c85b` re-audit → `165c9331` de-bloat. The
violated rule (argument-stopping *why* stays inline; size is not the
success metric; no second not-auto-loaded governance file) is now an
AGENTS.md hard rule but recurrence-untested.

Mechanizable sliver only:
- **Orphan-governance-file check.** Fail if a governance-doc-shaped
  file (`AGENTS.notes.md`, `RULES.md`, `*GUIDELINES*.md`) exists and
  is referenced by AGENTS.md but is *not* auto-loaded via CLAUDE.md's
  `@`-include chain. The deterministic core of "no second governance
  file agents never open." File-existence + CLAUDE.md include-graph
  walk; near-zero FP. **Proposed** — verify the CLAUDE.md `@`-include
  mechanism is greppable before committing.

Explicit ANTI-decision (record so it is not re-proposed):
- **Do NOT add an AGENTS.md size/line ceiling lint.** A max-KB or
  max-line gate mechanically re-incentivizes the exact compression the
  reversal forbids — a lint that *rewards* the violated behavior and
  punishes restoring argument-stopping rationale. The one case where
  mechanization is worse than the prose rule. The most a gate may do
  is a **non-blocking large-net-deletion review prompt** on AGENTS.md
  (a speed-bump forcing explicit human sign-off on big cuts), never
  pass/fail. 0074's "lintable drift must be linted" does not apply:
  the drift is *removal of load-bearing content*, not lintable without
  judging whether the content was load-bearing.

Core of #6 (is this *why* argument-stopping; is this cut a
compression-too-far) is irreducibly review-time. The sliver above is
the only lint; the rest is the `9f120743` hard-rule + reviewer
vigilance. A recorded "we will not build X, because" is 0074-
consistent: 0074 requires *lintable* drift be linted, not that every
rule be linted.

Routing: same single decision; the anti-decision is part of the
record.

## #7 — forward-reference `the` tic (new 2026-05-19)

Surfaced by two `/audit-comments` pilots on `workbench/deploy` (the
first pilot's whole-package pass + the submodule (a) pass on
transports/probe/device).  Sibling of #3's definition tic: same
Engine B (closed-set match), different modifier list, different
position constraint, different FP profile.

**The pattern.**  `the (next|first|only|new|sole) <generic-noun>` in
docstring-initial or comment-initial position with no prior referent in
the surrounding scope.  Pretends definite reference without an anchor;
should be `a/an` (category), `any` (universal), or no article.
Examples lifted from the actual rewrites the pilots produced (each one
caught by the reviewer, not by the auditor's first draft):

- *"the next port grab"* (settle comment — no defined next port grab)
- *"the new payload"* (clean=True/False comment)
- *"the next `stage()` call"* (soft_reset paragraph)
- *"the first file change"* (autoreload docstring — hypothetical first one)
- *"the next host `write()`"* (autoreload docstring)
- *"the only option"* (DiskArbitrationAgent bullet)

Each fails the per-noun forward-reference test (AGENTS.md → Writing
tone, judgment guidance for the general case): *is there a unique
singular instance of X already established in scope?*  For these, no.
For the legitimate keeps (*"the open raw-REPL session"* after
`_enter_raw_repl` ran; *"the runtime"* / *"the freshly-formatted
volume"* inside `wipe_filesystem`'s method body), yes — surrounding
context establishes the referent.

**Lintable subset — closed modifier × closed noun + position constraint.**

- **Modifiers:** `next|first|only|new|sole` (small, stable).
- **Nouns:** `call|write|file|file change|iteration|port|port grab|command|
  session|payload|deploy|request|line|step|stage|message|byte|chunk|
  response|option|instance` — pilot-derived *starter* list.  **Extend
  as more pilots surface concrete failures; do not pre-guess.**  The
  pilots ARE the calibration set.
- **Position:** sentence-initial inside a docstring or `#` comment.
  Mid-sentence occurrences (*"…and the next call sees X"*) carry too
  high an FP rate (idioms like *"the first time"*, *"the only LED"*)
  and stay with audit-pass judgment.

**FP allowlist via `# noqa: CHU0NN — <why>`** (per AGENTS.md noqa
rule):

- *"the next test"* inside a test docstring describing a sequence.
- *"the only LED"* / *"the only board"* / *"the only port"* when the
  noun is uniquely identified by surrounding state.
- *"the first call"* in a state machine describing a specific
  first-transition.

Each escape carries the one-line *why* AGENTS.md requires.

Routing: folded into the single `new-decision` covering the set —
recorded as a peer closed-set list to #3 (`the (one|single|sole) X`
definition tic).  Both feed Engine B with different modifier+noun
lists and different position constraints; do NOT pre-merge into one
mega-pattern — the two FP profiles diverge enough that calibration
stays per-list.

Not mechanizable: the per-noun semantic test (*"does the surrounding
context establish a referent for X?"*) for the general case.  Stays
with `/audit-comments` + AGENTS.md Writing tone, the sibling of the
change-narration sniffer `open-questions.md` rejected.

## Recommended sequencing

Original recommendation was "#2 now (mechanical), #1 + #3 via
new-decision." The verified `.scratch/`/`template_zones.py` finding
revises that: **all three route through `new-decision`** (or a single
decision covering the set, given the open-questions overlap). #2 is
still first to land — its design space is smallest once the
`.scratch/` narrowing and the legitimate-data exemptions are decided.

**Revised by the 2026-05-19 two-engine broadening:** one decision now
covers #1–#7 + both engines + the #6 anti-decision (the open-questions
overlap already pointed here; #5/#6 reinforce single-decision). Build
order by risk: **Engine B first** — it already exists as CHU006;
extending it with lists lands #2 / #3 / CHU020 / the date-SHA-token
half together at lowest risk, and #1's landed-history regex + #4's
prefilter ride on the same matcher/AST. **Engine A second** (`src/`
dedup, then the ADR consumer once its precision is verified). **Small
structural checks last** (#5 superseded-pointer, #6 orphan-governance).
**#7 follows #3** once that calibrates — same engine, peer closed-set;
do not pre-merge the two `the`-shape lists since their FP profiles
diverge.  Record the #6 anti-decision up front so an AGENTS.md size
gate is never built while the rest is in flight.

## Pointers

- AGENTS.md "Code comments" + "Writing tone" non-negotiables (the
  prose this mechanizes).
- [Decision 0074](../../decisions/0074-drift-mechanization-as-project-policy.md)
  — lintable drift must be linted; the rule that makes this in-charter.
- `plans/open-questions.md` "Mechanize the comments document
  current-code why" — prior art, reconcile #1/#3 with it.
- CHU006 self-reference precedents: chu006.py:164-194 (predicate) and
  chu006.py:177-178 (inline `# noqa: CHU006`).
- The "the (one|single|sole) X" AI-tic (the #3 tic).
- `.github/skills/audit-comments/SKILL.md` + AGENTS.md → Writing tone
  "degraded prose is rewritten, not trimmed again" single home (added
  2026-05-19) — the *judgment* counterpart this lint set's residue
  routes to; the two were designed as one split (mechanize the lexical
  half, audit the semantic half).
- Commit-evidence anchors for #5/#6: `165c9331` (ADR de-bloat),
  `59ee9f36` (README-read forcing function), the #6 five-commit
  oscillation (`53313cf6` `7f19a109` `9f120743` `9158c85b` `165c9331`).

## Status

Opened 2026-05-18, parked. Surfaced from deploy-path-unification
Commit 2c's comment cleanup (the unmechanized-rule contrast: CHU006
self-caught its 2c violation; the unlinted gaps reached human review).
**Broadened 2026-05-19** — two-engine consolidation + #5 (ADR-
authoring) + #6 (AGENTS.md self-editing meta-rule, incl. the no-size-
gate anti-decision) + #7 (forward-reference `the` tic, sibling
closed-set to #3, calibrated from two `/audit-comments` pilots on
`workbench/deploy`), from the evidence pass that accompanied the
`/audit-comments` skill + AGENTS.md Writing-tone single-home session.

**Design decided 2026-05-19 — [Decision 0079](../../decisions/0079-prose-drift-mechanization.md)
is now the durable design record.** This file stays as the deeper
analysis reference (per-rule FP profiles, source anchors, the
verified-then-stale-by-`61f31c26` `.scratch/` narrowing story, the
structural-conjunct prefilter analysis for #4, the rejected ratio
framing, the open-questions / CHU020 fold-in reasoning). Implementation
tracked in [`plans/next-up.md`](../../next-up.md) under
"CHU prose/isolation lint mechanization — implement Decision 0079."
Nothing implemented yet; build order in the ADR.
