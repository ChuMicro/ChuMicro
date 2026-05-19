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
this shape and there is a user memory (`feedback_the_one_x_aitic`) on
it. It bit twice this pass (`circuitpython_transport.py:967`,
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

## Recommended sequencing

Original recommendation was "#2 now (mechanical), #1 + #3 via
new-decision." The verified `.scratch/`/`template_zones.py` finding
revises that: **all three route through `new-decision`** (or a single
decision covering the set, given the open-questions overlap). #2 is
still first to land — its design space is smallest once the
`.scratch/` narrowing and the legitimate-data exemptions are decided.

## Pointers

- AGENTS.md "Code comments" + "Writing tone" non-negotiables (the
  prose this mechanizes).
- [Decision 0074](../decisions/0074-drift-mechanization-as-project-policy.md)
  — lintable drift must be linted; the rule that makes this in-charter.
- `plans/open-questions.md` "Mechanize the comments document
  current-code why" — prior art, reconcile #1/#3 with it.
- CHU006 self-reference precedents: chu006.py:164-194 (predicate) and
  chu006.py:177-178 (inline `# noqa: CHU006`).
- User memory `feedback_the_one_x_aitic` (the #3 tic).

## Status

Opened 2026-05-18, parked. Surfaced from deploy-path-unification
Commit 2c's comment cleanup (the unmechanized-rule contrast: CHU006
self-caught its 2c violation; the unlinted gaps reached human review).
Nothing implemented. Pick up via the routing above.
