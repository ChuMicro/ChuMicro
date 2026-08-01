---
description: Audits an existing skill on disk against Anthropic's documented skill-authoring rules — size and token budgets, progressive disclosure, rule salience, frontmatter routing — and the skill's own stated goal. Use when a skill's flow feels off, contradicts itself, or routes wrong — or before relying on it for important work. Examples: "audit the audit-docs skill", "/audit-skill audit-library", "is the audit-library skill achieving its goal?".
allowed-tools: Read, Write, Edit, Grep, Bash(ls *), Bash(cp *), Bash(mkdir *), Bash(date *), Bash(python3 *), Bash(open *), AskUserQuestion, Agent, Workflow, Monitor
argument-hint: "<slug-or-path>"
arguments:
  - target
when_to_use: |
  Use when an existing skill routes the wrong messages, when its body
  contradicts its frontmatter, when its tool list is over-broad or skips
  AskUserQuestion at user-input forks, or when a fresh cold read would
  surface drift the author normalized after weeks on the file. Also fires
  on "validate X against spec" / "check X for issues" phrasings. Do NOT
  use to author a new skill — that's /new-skill. Do NOT use for prose
  docs (/audit-docs) or code comments (/audit-comments) — this skill
  audits SKILL.md files and the persona/workflow files they dispatch.
---

# Audit Skill

One Workflow run fans out seven lenses over a SKILL.md and everything it ships:
six blind — loader routing, cold-walk, craft, orchestration, surprise, ideas — plus an
outward research lens that web-searches prior art and live Claude Code docs. Each returns
schema-validated findings with evidence. The director merges them into a ledger; a second
Workflow — the speaker — rewrites every user-facing line for a cold reader, plain by default
or in a registry voice picked up front. Only the fixes the user picks by number get applied.

## When to use this skill

- A skill's directives feel confusing or contradictory on a cold read.
- A skill's goal is hard to derive from its SKILL.md top-to-bottom.
- Before relying on a skill for important or repeated work; after significant edits, to check what drift landed.

**Don't use for:** authoring a new skill (`/new-skill`), prose docs (`/audit-docs`),
code comments (`/audit-comments`). Step 1 detects these misroutes and redirects.

## Invocation

| Form | Behavior |
|---|---|
| `/audit-skill <slug>` | Resolves to `.claude/skills/<slug>/SKILL.md` or `.github/skills/<slug>/SKILL.md`, then audits |
| `/audit-skill <path>` | Audits the SKILL.md at the explicit path |
| `/audit-skill` (no arg) | Asks which skill via `AskUserQuestion` populated from the tree's slug list |

## The question rule

Every question this skill asks must be decidable from the question itself plus the
report the user just read. A finding's number, quoted evidence, consequence, and exact
proposed change appear **before** any ask about it. Approval through a bare label —
trusting the asker instead of seeing the defect — is the failure mode this skill audits
for, and how a prior version of it failed in production.

Findings are approved **by number in plain chat** (`apply 1, 3, 5` · `discuss 2` ·
`edit 4: <wording>`), never one widget per finding. `AskUserQuestion` is reserved for the
genuine forks: the Step 1 redirect, the Step 1b voice pick, the Step 6 mode pick. A picked
voice phrases the report and the gates; it never changes what an option does or states a
fact outside the ledger.

## Definition of done

1. A real SKILL.md resolved (or redirected cleanly), and a voice picked (plain default).
2. Lens findings merged into `ledger.json`, spoken, and delivered as one numbered
   evidence-first report, written to a file and opened; harness-claims verified.
   Routing probes ran only if the user asked.
3. A mode picked (apply-by-number / re-author / report-only) and the picked numbers ran to completion.
4. In re-author mode, a backup at `.scratch/skills-backup/skills/<slug>-<UTC>/` before the seed printed.

## Process

### 1. Resolve the target

`ls` the explicit path, or check both `.claude/skills/<slug>/SKILL.md` and
`.github/skills/<slug>/SKILL.md` (some projects symlink one to the other).
When neither resolves, fire a redirect `AskUserQuestion` whose options carry `preview`
fields showing the destination invocation (`/audit-docs <target>`, `/audit-comments <target>`,
`/new-skill <slug>`, or "It's a SKILL.md — I'll give a different path").
On a non-skill pick, print the previewed invocation and exit.

**Success criteria:** an absolute SKILL.md path printed, or the redirect invocation printed and the skill exited.

### 1b. Voice gate

The report and every gate after it speak in a voice; the scans never do.

- Read `.github/skills/_shared/voices/voices.json` and print a compact numbered menu in chat:
  one voice per line in registry order, `1. plain` first marked **(default, voiceless — reads cleanest)**.
- Fire one `AskUserQuestion`. In the no-arg form the which-skill question rides first and the
  voice question second; with a resolved target the voice question is the call's only question.
- The voice question: header `Voice`, two options — *"Plain (default, recommended)"* and
  *"Numbered voice — type the menu number under Other"*. A bare number under Other maps to the menu.
- For a named voice, hold its persona line and load its register excerpt:
  `python3 .github/skills/_shared/voices/voice_sample.py <key>` prints the real-prose sample
  (excerpt only, never attribution); empty output is fine — the voice runs persona-only.

**Success criteria:** menu printed, pick echoed, one voice key (+ persona and sample when named) held for Step 5b.

### 2. Inventory

```bash
ls <skill-dir>/*.md <skill-dir>/*.js <skill-dir>/trigger-evals.json <skill-dir>/scripts/ 2>/dev/null
grep -nE 'subagent_type:|\.claude/agents/' <skill-dir>/SKILL.md
grep -E '^description:.*Examples:' <skill-dir>/SKILL.md
for f in <skill-dir>/SKILL.md <each reference file>; do
  awk -v f="$f" '{ if (length($0) > longest) longest = length($0); chars += length($0) + 1 }
    END { printf "%s  lines=%d  est_tokens=%d  longest_line=%d\n", f, NR, int(chars / 4), longest }' "$f"
done
bang=$(printf '!\x60'); fence=$(printf '\x60\x60\x60!')
grep -rnE -e "(^|[[:space:]])$bang" -e "^$fence" <skill-dir>/ || true
ls .github/skills/_shared/
```

Capture:

- Every file the audit covers — SKILL.md, reference files, bundled scripts, workflow files,
  persona files — from the greps plus a read of any dispatch or companion table in the body
  (a persona cited by bare slug matches no fixed pattern).
- The sizing table. chars/4 is the binding token estimate (word counts under-count dense
  markdown); `longest_line` catches a body that meets the 500-line target by packing rules
  into very long lines. The table rides into the Step 4 args as `sizing`; a measured number
  outranks any lens estimate.
- Bang-pattern hits. Any hit is a dynamic-context trigger that fires the loader's preprocessor
  the moment the skill loads — an IMPORTANT director finding unless the skill clearly intends the injection.
- A `_shared/` glance. A bundled script re-implementing a shared asset (picker, probe runner,
  voice registry) is a director finding the fenced lenses cannot see.
- The three trigger messages from the description's `Examples:` block, salvaging from
  `when_to_use` when absent. Both empty is a CRITICAL finding on its own — report it and
  continue; the loader lens still judges the description text.

**Success criteria:** an inventory block naming every covered file, the sizing table,
and the trigger messages or the CRITICAL no-triggers note.

### 3. Director pre-draft

From your own fresh top-to-bottom read, hold two things in chat: (a) a 2–3 sentence statement
of the skill's goal; (b) 3–6 predicted findings — the baseline for the Step 5 missing-content
comparison; what you expected that no lens surfaced becomes a director follow-up.
State your bias when you have one (you edited the target recently, you wrote it).

**Success criteria:** goal draft + predictions in chat before any lens output arrives.

### 4. Launch the lenses

Call `Workflow` with `scriptPath: .github/skills/_shared/audit_wf.js` (shared —
`/new-skill` runs the same lenses over its drafts) and
`args: {skillPath, referenceFiles, personaFiles, scriptFiles, triggerMessages, sizing}` —
absolute paths, empty arrays where the inventory found none, `sizing` as one string.
Seven agents fan out — the six blind lenses plus research — each restricted to the files
its prompt names. The schema forces tier, evidence, consequence, and proposed fix on every finding.

Routing probes (`run_trigger_evals.py`) are **off by default**: each row is a fresh `claude -p`,
and that spend has not earned its findings. Run them only when the user explicitly asks;
the loader lens's judged routing is the default signal.

The Workflow runs in the background and notifies on completion; tell the user it's running
and the rough duration (a few minutes).

**Success criteria:** one Workflow call launched; seven lens objects collected; probes only on explicit ask.

### 5. Merge

- **Tiers:**
  - CRITICAL — goal not derivable; frontmatter routes nothing; Done-when missing;
    a tool-event procedure misfiled as a skill.
  - IMPORTANT — non-discriminating or missing Success criteria; the body over either budget
    (500 lines / ~5,000 tokens ≈ 20,000 chars) or inside the line target only through long
    lines; a load-bearing rule past the ~5,000-token compaction prefix; a dynamic-context
    trigger in a shipped file; a bundled script re-implementing a `_shared/` asset; undisclosed
    side effects; a missing AskUserQuestion at a real fork; a question-rule violation;
    lens-table↔persona drift; hedging/moralizing in directives.
  - MINOR — single tic words, voodoo constants, cosmetic drift, name-style misses.
  - AMBIGUOUS — the lens itself stated two readings.
- **Precedence:** lens findings outrank director observations; a measured number (sizing,
  any probe table) outranks both on its fact.
- **Harness claims:** any finding with `harness_claim: true` gets verified before it lands —
  dispatch `claude-code-guide` with the specific claim; require a doc URL. Confirmed → the
  finding stands with the URL. Contradicted → the audited skill is fine and the stale lens
  rule (in `_shared/audit_wf.js`) becomes the finding. A claim already verified this session needs no re-dispatch.
- **Director comparison:** predictions no lens touched become director follow-ups, labeled as yours.
- Ideas are not findings: the ideas and research menus join the report separately numbered,
  each with its lens's `recommended_action`.
- **Write the ledger:** `mkdir -p` the report dir (`<report-dir> = .scratch/skill-audits/<slug>-<UTC>/`)
  and write the merged result to `<report-dir>/ledger.json` — a full picker spec in raw lens
  wording, which never reaches the user.
  - One card per item: id = report number, title, tier badge, `source` naming the lens,
    the lens's summary / why / fix untouched, `evidence` verbatim.
  - A replacement-text fix emits a `diff` ({location, old, new} — old from the evidence quote);
    an instruction-style fix keeps the fix row.
  - Order by tier; `facets: {"tier", "lens"}` with per-value `help` lines — one narrowable list, no tabs.
  - Options `apply / discuss / skip`; CRITICAL and IMPORTANT pre-select `apply`;
    MINOR, AMBIGUOUS, and ideas pre-select `skip`.

**Success criteria:** one merged numbered list in `<report-dir>/ledger.json`,
every entry carrying evidence, consequence, and proposed fix.

### 5b. Speak the ledger

Lens wording is author shorthand — gibberish to a cold reader. Nothing user-facing ships
in that register, the plain voice included.

- Call `Workflow` with `scriptPath: .github/skills/_shared/speak_wf.js` and
  `args: {ledgerPath, ids, voice, persona, sample}` — every ledger id; persona = the registry
  line (empty for plain); sample = the Step 1b excerpt text, injected inline (never a path).
- The speaker reframes and never re-grounds: per item it returns a rewritten title, summary,
  why, and fix built only from that entry's facts, each card readable alone by a cold reader;
  replacement text and commands pass through character-for-character. It also returns the page
  `intro_html`, the `option_help` legend, and the Step 6 mode-gate wording.
- Save the return to `<report-dir>/spoken.json`; `python3 .github/skills/_shared/splice_spoken.py <report-dir>`
  writes `spec.json`. An empty speaker string never overwrites a fact; an id reported
  `unrendered` keeps ledger wording with a `warning` naming that.

**Success criteria:** speaker strings spliced over every item id (or warnings on stragglers);
no raw lens wording in anything the user will read.

### 6. Report, then one fork

Render the report per [Output format](#output-format), write it to
`.scratch/skill-audits/<slug>-<UTC>.md` (`date -u +%Y%m%dT%H%M%SZ`), `open` it, and print it in chat.

**Decision page — whenever at least one finding or idea is open.** The page spec is already
on disk at `<report-dir>/spec.json`:

```bash
python3 webui/render_picker.py <report-dir>/spec.json
python3 webui/serve_picker.py <report-dir>   # run_in_background; posts to the surface hub
```

The hub owns the one browser tab: it opens the browser only when no tab is connected and
pushes the new surface into the open shell otherwise — never `open` the URL yourself and
never set `PICKER_NO_OPEN`. If the conversation moves past the question, withdraw it
(`python3 -m webui.hub withdraw <id>`, the id from the `ASKED` line) or re-serve with
`--supersede` instead of stacking a second round.

Watch the server's stdout with `Monitor` — a browser submit prints `SELECTION RECEIVED -> <path>`;
the blob uses the same selection language as typed chat (`<id> = <choice>` lines, `note <id>:`
riders). Echo the received vector into chat before acting. The page never replaces chat.

Then fire **one** `AskUserQuestion` — header `Mode`:

- "Apply by number" — pick in the served page or type the numbers; each applied visibly.
- "Route to re-author" — shown only at ≥2 CRITICAL findings or a CRITICAL goal-derivability finding.
- "Report only — no action."

Question and option text carry the speaker's gate wording; the three semantics are fixed.

**Success criteria:** report written and opened, page served when items are open, mode picked.
No filesystem change on the audited skill yet.

### 7. Apply by number

Selections arrive as typed chat (`apply 1, 3, 5` · `discuss 2` · `edit 4: <wording>` ·
`skip the rest`) or as the picker blob — same semantics; a note on an applied number is the
user's wording adjustment.

For each applied number: re-read the touched region (earlier fixes shift line numbers),
apply via `Edit`, honor any per-number note. An idea anchored in goal-bearing prose
(description, opening paragraph, Done-when, a blindness contract) gets one explicit confirm
first. A substantive rewrite gets one re-verification: a fresh `Agent` (general-purpose) with
the finding text + post-edit file, returning *resolved / not resolved / new finding*; cap one
re-dispatch per finding; unresolved ones land in the report tail. Git is the recovery path —
this skill commits nothing.

Follow-up gates reuse the speaker's pre-rendered wording where one exists; the orchestrator
never imitates the voice itself. A follow-up genuinely needing voiced prose gets a mini-ledger
and a re-run of `speak_wf.js`.

**Success criteria:** every picked number applied or explicitly bounced with a reason;
unpicked numbers untouched.

### 8. Re-author handoff (only from the Step 6 fork)

```bash
mkdir -p .scratch/skills-backup/skills
cp -r <skill-dir> .scratch/skills-backup/skills/<slug>-$(date -u +%Y%m%dT%H%M%SZ)/
```

Print a seed for `/new-skill <slug>`: the preserved goal, triggers, exclusions, orchestration
intent, one line per CRITICAL finding, and any ideas the user marked for the seed.
Do not invoke `/new-skill` yourself — the user reviews the seed and fires it.

**Success criteria:** backup exists at the printed path; seed + invocation form in chat.

### 9. Post-edit sweep (only when edits landed)

- `description` ≤ 1024 chars; combined with `when_to_use` ≤ 1536 — when frontmatter was touched.
- Body budgets re-measured with the Step 2 awk loop — ≤ 500 lines, under ~5,000 tokens
  (chars / 4), longest line not ballooned — when body content was touched.
- Bang-pattern grep re-run over the touched files.
- AI-tic regex (AGENTS.md § Writing tone) and the abstract-subject probe
  (`docs/contributing/agent-style-guide.md` § Concrete subject, real verb) against the
  post-edit body — hits are candidates for a read-aloud, not verdicts.
- Every step still carries a discriminating Success criteria field; Done-when still distinct from the last step.
- Every reference-file link and dispatched-file path still resolves, one hop from SKILL.md.

Print PASS/FAIL per check; a FAIL gets fixed or recorded as a known concern in the report tail.

**Success criteria:** the sweep block printed; no silent FAIL.

## Output format

```
audit-skill report — <skill-dir>/SKILL.md
=========================================
Goal (director draft): <2–3 sentences>
Probe table: <skipped (default) | N/M pass (user-requested)>
Lens goal check: <derivable per cold-walk lens — its one-sentence statement>

FINDINGS (apply by number)
 1. [IMPORTANT · loader] <one-sentence finding>
    evidence: <file:line> "<short quote>"
    why: <consequence in one plain sentence>
    fix: <the exact proposed change>
 2. ...

DIRECTOR FOLLOW-UPS (mine — lenses outrank these)
 8. ...

IDEAS (separately numbered; not defects)
 9. <title> [<kind>] [WILD]? — recommended: <action>
    anchor: <file:line | URL | vision> · <what changes if it lands>

Director-bias warning: the director read the source; lens findings outrank
director observations; measured numbers outrank both.
----
Audit run: <UTC> · recommendation: <apply-by-number | re-author | report-only>
```

The same content goes to `.scratch/skill-audits/<slug>-<UTC>.md` so the report survives
scrollback. The finding / why / fix lines are the speaker's strings from Step 5b;
evidence lines stay verbatim from the ledger.

## Red flags — stop and reconsider

- The target isn't a SKILL.md → redirect at Step 1.
- Your Step 3 draft disagrees materially with the lenses → the lenses win or the dispatch was under-fed.
- Three or more CRITICAL findings → recommend re-author, not patchwork.
- A lens returned nothing after the workflow's retry → name the missing lens in the report
  rather than quietly auditing with fewer.
- The speaker workflow died entirely → ship the report in ledger wording, say so up top,
  and offer a one-shot re-speak before the mode gate; never block the report on prose.

## Don'ts

- Don't apply any change the user didn't pick by number.
- Don't ask an approval question that fails the question rule.
- Don't run the routing probes unasked — they spend real allowance for marginal signal.
- Don't auto-invoke `/new-skill`; the user fires the seed.
- Don't read other audit-* skills for reference mid-audit; the lens prompts in `audit_wf.js` carry the rules.
- Don't let your read outrank a lens, or judgment outrank a measured number.
- Don't ship raw lens wording anywhere the user reads — report, page, or gates;
  every user-facing line passes through the Step 5b speaker, plain voice included.
- Don't let the speaker add, drop, or soften a fact: ledger facts only, replacement text
  verbatim, voices speak — they never judge.

## Done when

- The numbered report exists at `.scratch/skill-audits/<slug>-<UTC>.md`, opened and in scrollback.
- The report, the page, and the gates carry the speaker's prose in the picked voice;
  lens shorthand survives only inside `ledger.json`.
- `git diff` on the audited skill shows exactly the user's picked numbers — nothing more.
- In re-author mode, the backup + seed are in place and the `/new-skill` invocation is one paste away.
- A reader scrolling this session can answer in a minute: what was found, the evidence,
  what was picked, what moved.
