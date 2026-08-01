# Walking MEDIUM and LOW findings

> Shared convention for audit-* skills.  Not a user-invokable skill — `.github/skills/_shared/` is reserved for cross-skill references like this one.  Linked from `audit-comments` (and, as retrofits land, the rest of the audit-* family).  Read in full when implementing a walk in your skill.

An audit-* skill produces tiered findings.  HIGH (mechanical, no per-finding judgment) batches as one cohesive commit.  MEDIUM and LOW need per-finding user judgment — but a free-text punch-list makes the user type judgment from scratch on every finding, and the auditor too often describes what's wrong without proposing what to do instead.

The walk fixes both at once.  Surface each MEDIUM or LOW finding one at a time via `AskUserQuestion`, with 2-4 concrete options sized to the finding.  `(Recommended)` marks the option that follows from the skill's stated guidance.  The user clicks (or picks "Other" to free-text); the auditor applies; the walk moves to the next finding.

## Per-finding script

1. Show `file:line` and the current state.
2. Show why the finding fired — which dimension / category, what defect.
3. For a REWRITE-shaped finding, show the proposed replacement text inline.  For other finding shapes, show the proposed action.
4. Call `AskUserQuestion` with 2-4 options.  The tool auto-injects an "Other" choice for free-text; don't add one manually.
5. Apply the user's choice (or wait for the "Other" text).  Commit when the unit of work is coherent.
6. Move to the next finding.

## Option templates

Start from these per finding shape; adjust per the skill's tier semantics and finding categories.

| Finding shape | Lead option (Recommended) | Other options |
|---|---|---|
| Subtractive (TRIM, DELETE-clause) | Cut / drop as proposed | Keep — load-bearing why is …; Skip / defer |
| Replacement (REWRITE) | Apply proposed replacement | Less-invasive option (trim only); Skip / defer |
| Confidence check (`keep?` / KEEP-check) | Keep as-is | Cut the flagged clause; Skip / defer |
| Refactor / shape | File as `## Next` pointer; Accept the proposed split; Skip / defer | (varies — adapt to skill) |

`(Recommended)` is the auditor's lean.  Skip the tag when LOW findings have no clear default — keep is still first but doesn't get the marker.

## Wording the ask

These rules cover every `AskUserQuestion` in this repo, walks included.  A `PreToolUse` hook (`ask_gate.py` in this directory, wired in `.claude/settings.json`) enforces the mechanical floor: it bounces a thin ask back with a per-defect failure list and the floor's exact thresholds, and the asking agent rewrites the same ask and re-fires.  The gate is mechanical; the rewrite stays the model's.

- The question text stands alone.  Open with one or two plain sentences naming the concrete thing being decided (the file, the finding, the fact) and what hangs on the choice, then ask.  The user decides from this text plus what is already on their screen, never from session memory — an ask written in lens shorthand or ledger-stub register reads as gibberish at the gate.
- Labels stay short; the widget truncates long ones.  The substance lives in each option's description: a full sentence on what picking it does and when it is the right pick, never the label restated.
- Spell facts as sentences.  Fragment joiners (em-dash, ` -- `, `→`, `·`) are blocked in questions, labels, and descriptions, except inside quoted spans — quoting prose that itself carries an em-dash is fine.
- Candidate text under comparison (a rewrite, a command, a description line) goes in per-option `preview` fields on a single-select question, not compressed into descriptions.
- A gate that outgrows the widget — more than a few facts per option, side-by-side text comparison, or anything the user would want to sit with — renders the shared decision page (`webui/render_picker.py` at the repo root) instead, even for two items.

## Choosing the surface

Route by the decision's shape, never by habit, and never force the nearest template:

- **Many items, one call each** (findings, checklist, triage) — the decision page: one card per item, facets, per-card notes.
- **Candidate texts that differ by one named variable against a shared baseline** — the `columns` pick_ui: the baseline rides in the context box, and the summary names the axis the choice is judged on. Candidates that differ in several ways at once are NOT a pick-one comparison; give each its own card and verdict instead (forcing "which wins" onto apples-and-oranges is the recorded failure shape).
- **The real answer is sentences** — `prose` fields: a prompted paragraph box whose text rides the blob as its own line. Use them whenever a radio row would flatten what the user actually needs to say.
- **The real answer is short and structured** — `fields` on the card: `text` (one line, seedable), `multi` checkboxes, a `scale` with both ends labeled, a `menu` for long option lists, and `allow_other` on a radio row for a write-in seat; `required: true` gates Submit until answered. Each rides the blob as its own kind-named line.
- **The user needs to see or take an artifact** — `media` on the card: image galleries with a lightbox, a before/after `compare` slider, audio/video players (the hub serves Range, so they scrub), and `file` download cards for anything else. Everything shown is also downloadable; a pure exhibit is an informational card carrying only media.
- **The user hands a file back** (a screenshot they took, a log) — an `upload` field: drag or browse, the hub stores it under the surface's state and the blob carries its absolute path; copy the file out promptly, resolved surfaces are eventually pruned.
- **Status the user watches across turns** — a hub `status` surface: post once, `update` in place each turn; the same card refreshes in the same tab.
- **None of these fit** — design the page. `kit.page(title, body)` inherits the shell, palette, affordance, and submit path, so a bespoke surface is a body fragment, not a new stack.

The renderer enforces a content floor (the ask gate's mirror, `floor_failures` in `render_picker.py`): decision pages carry a brief naming what is decided and what happens with the answer; every decision card a summary a cold reader can act on; bare-letter option sets must have their axis defined; radio options need full-sentence `option_help`; prose prompts are real questions. A failing spec prints `FLOOR` lines and exits 2 — fix the spec; `floor_waived` is for the rare page the floor genuinely cannot fit, never a shortcut.

Serving goes through the surface hub (`webui/hub.py`): one server per repo, one browser tab, every question and report a surface posted onto it. `serve_picker.py` does this by default and blocks until the answer lands (exit 0 answered, 3 withdrawn, 4 expired). Never `open` the URL yourself and never set `PICKER_NO_OPEN` — the hub opens the browser only when no tab is connected and pushes into the open shell otherwise. When the conversation moves past a pending question, withdraw it (`python3 -m webui.hub withdraw <id>`, the id from the `ASKED` line) or re-serve with `--supersede`; an abandoned pending surface is a bug, not a leftover.

## When not to walk

- **HIGH findings** batch — DELETEs, mechanical TRIMs, mechanical REWRITEs are word-choice-free.  No per-finding pause; one cohesive commit.
- **DEFER findings** (the `shape` tag or its equivalent in your skill) get filed as `## Next` entries pointing at the appropriate sibling skill, not walked.  The user doesn't need to judge them inline.
- **Counts above ~15 in one pass**: ask first.  Walk all, walk a sample, or surface as a free-text punch-list.  Walking 30 prompts in a row trades one cognitive cost for another.

## Verifier integration (when a skill dispatches a verifier subagent)

Some audit-* skills (e.g. `audit-comments` Pass 2) dispatch a verifier subagent that reads the proposed output blind to the original, producing its own tiered findings.  When both auditor findings and verifier findings exist, the walk surfaces both per finding:

- **Agree**: walk with the agreed-tier lead option.
- **Verifier upgrades a finding the auditor classified lower**: surface the verifier's reasoning in the AskUserQuestion question text; lead with the verifier-preferred action.
- **Verifier clears a finding the auditor flagged**: drop to LOW or surface as "verifier disagrees" with the auditor's proposed action still leading.
- **Verifier surfaces a finding the auditor missed**: walk it like any auditor finding, tag the question text with "(verifier-surfaced)".

The walk doesn't resolve the disagreement automatically — the user does, via the option list.  Hiding the disagreement defeats the purpose of running the verifier in the first place.

## Anti-patterns

- **Don't surface MEDIUM or LOW findings as a free-text punch-list when walking is available.**  Per-finding `AskUserQuestion` turns each judgment into a click + the tool's "Other" free-text fallback.
- **Don't add an "Other" option manually.**  The tool auto-injects it for free-text input.
- **Don't hide verifier findings in the walk.**  When a verifier disagrees with the auditor, the user needs to see the disagreement to break the tie.
- **Don't pre-batch MEDIUM into commits before the walk completes.**  Each `AskUserQuestion` is the gate before that finding's edit lands; batching commits ahead of time defeats the per-finding reversibility the walk relies on.
