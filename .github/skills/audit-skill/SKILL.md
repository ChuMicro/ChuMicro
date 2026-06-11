---
description: Audits an existing skill on disk against the skill-writing rules in AGENTS.md and the skill's own stated goal. Use when a skill's flow feels off, contradicts itself, or routes wrong — or before relying on it for important work. Examples: "audit the audit-docs skill", "/audit-skill audit-library", "is the audit-library skill achieving its goal?".
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

Audits a SKILL.md, its reference files, and anything it dispatches (persona files, workflow scripts). One Workflow run fans out six lenses — five blind ones (loader routing, cold-walk, craft, orchestration, a generative ideas lens) plus an outward research lens that web-searches prior art and live Claude Code docs — each returning schema-validated output that carries its own evidence. The director merges them with measured routing probes, prints one numbered evidence-first report, and applies only the fixes the user picks by number.

## When to use this skill

- A skill's directives feel confusing or contradictory on a cold read.
- A skill's goal is hard to derive from its SKILL.md top-to-bottom.
- Before relying on a skill for important or repeated work; after significant edits, to check what drift landed.

**Don't use for:** authoring a new skill (`/new-skill`), prose docs (`/audit-docs`), code comments (`/audit-comments`). Step 1 detects these misroutes and redirects.

## Invocation

| Form | Behavior |
|---|---|
| `/audit-skill <slug>` | Resolves to `.claude/skills/<slug>/SKILL.md` or `.github/skills/<slug>/SKILL.md`, then audits |
| `/audit-skill <path>` | Audits the SKILL.md at the explicit path |
| `/audit-skill` (no arg) | Asks which skill via `AskUserQuestion` populated from the tree's slug list |

## The question rule

Every question this skill asks must be decidable from the question itself plus the report the user just read. A finding's number, its quoted evidence, its consequence, and the exact proposed change appear **before** the user is asked anything about it. Asking for approval through a bare label — where the user must trust the asker instead of seeing the defect — is itself the failure mode this skill audits for, and it is how a prior version of this skill failed in production.

That rule sets the selection mechanics: findings are approved **by number in plain chat** (`apply 1, 3, 5`, `discuss 2`, `edit 4: <wording>`), not through one approval widget per finding. `AskUserQuestion` is reserved for the genuine forks with few options: the Step 1 redirect and the Step 6 mode pick.

## Definition of done

1. A real SKILL.md resolved (or the request redirected cleanly to the right tool).
2. The lens workflow ran; the probe table ran when a `trigger-evals.json` exists; findings merged into one numbered evidence-first report, written to a file and opened, with harness-claims verified against live docs.
3. The user picked a mode (apply-by-number / re-author / report-only) and the picked numbers ran to completion — every applied edit visible, substantive rewrites re-verified.
4. In re-author mode, a backup landed at `.scratch/skills-backup/skills/<slug>-<UTC>/` before the seed paragraph printed.

## Process

### 1. Resolve the target

`ls` the explicit path, or check both `.claude/skills/<slug>/SKILL.md` and `.github/skills/<slug>/SKILL.md` (some projects symlink one to the other). When neither resolves, the request is probably about a different artifact — fire a redirect `AskUserQuestion` whose options carry `preview` fields showing the destination invocation (`/audit-docs <target>`, `/audit-comments <target>`, `/new-skill <slug>`, or "It's a SKILL.md — I'll give a different path"). On a non-skill pick, print the previewed invocation and exit.

**Success criteria:** an absolute SKILL.md path printed, or the redirect invocation printed and the skill exited.

### 2. Inventory

```bash
ls <skill-dir>/*.md <skill-dir>/*.js <skill-dir>/trigger-evals.json <skill-dir>/scripts/ 2>/dev/null
grep -nE 'subagent_type:|\.claude/agents/' <skill-dir>/SKILL.md
grep -E '^description:.*Examples:' <skill-dir>/SKILL.md
```

Capture: the SKILL.md path; reference files; bundled scripts and workflow files; persona files the skill dispatches — from the greps **plus a read of any dispatch or companion table in the body**, since a persona cited by bare slug matches no fixed pattern; whether `trigger-evals.json` exists (feeds the probe lane in Step 4). Extract the three trigger messages from the description's `Examples:` block, salvaging from `when_to_use` when absent. When both are empty, that is a CRITICAL finding on its own — report it and continue; the loader lens still judges the description text.

**Success criteria:** an inventory block in chat naming every file the audit covers, plus the trigger messages or the CRITICAL no-triggers note.

### 3. Director pre-draft

From your own fresh top-to-bottom read, hold two things in chat: (a) a 2–3 sentence statement of the skill's goal; (b) 3–6 predicted findings. The predictions are the baseline for the Step 5 missing-content comparison — what you expected that no lens surfaced becomes a director follow-up, which is how this skill catches what's *absent* rather than wrong. State your bias when you have one (you edited the target recently, you wrote it).

**Success criteria:** goal draft + predictions in chat before any lens output arrives.

### 4. Launch the lenses and the probes

In one turn:

- **Lens workflow:** call `Workflow` with `scriptPath: .github/skills/_shared/audit_wf.js` (shared — `/new-skill` runs the same lenses over its drafts) and `args: {skillPath, referenceFiles, personaFiles, triggerMessages}` (absolute paths; empty arrays where the inventory found none). The script fans out six agents. Five are blind lenses — loader, cold-walk, craft, orchestration, ideas — each restricted to the files its prompt names, each returning schema-validated findings that must carry tier, evidence (file:line + quote), consequence, and a proposed fix. The sixth is a research lens that reads only the audited files but searches outward: prior art for the skill's goal (including Anthropic's public skills repo), an ideal-version sketch diffed against the actual, and live Claude Code docs plus Anthropic's public GitHub for unexploited harness capabilities — every idea anchored to a URL or marked vision. The schema does the format enforcement; there is no re-dispatch-for-missing-tiers loop.
- **Probe lane (when Step 2 found `trigger-evals.json`):** `Bash(run_in_background: true)`: `python3 .github/skills/_shared/run_trigger_evals.py <skill-dir>/trigger-evals.json --workers 4`. Each probe is a fresh `claude -p` whose loader sees the real sibling registry — a routing measurement to set against the loader lens's judgment.

The Workflow runs in the background and notifies on completion; tell the user both are running and the rough duration (lenses a few minutes; probes similar).

**Success criteria:** one Workflow call + (when applicable) one background probe task launched in the same turn; six lens objects and the probe table collected.

### 5. Merge

- **Tiers:** CRITICAL = goal not derivable, frontmatter routes nothing (judged, or measured: every positive probe fails), Done-when missing, tool-event procedure misfiled as a skill. IMPORTANT = non-discriminating or missing Success criteria, a measured routing failure on any row, a missing AskUserQuestion at a real fork, a question-rule violation, lens-table↔persona drift, hedging/moralizing in directives. MINOR = single tic words, voodoo constants, cosmetic drift. AMBIGUOUS = the lens itself stated two readings.
- **Precedence:** lens findings outrank director observations; the measured probe table outranks both on routing.
- **Harness claims:** any finding with `harness_claim: true` (or any you notice resting on documented Claude Code behavior) gets verified before it lands — dispatch `claude-code-guide` with the specific claim; require a doc URL. Confirmed → the finding stands with the URL. Contradicted → the audited skill is fine and the stale rule (in `_shared/audit_wf.js`'s lens prompts) becomes the finding. A claim already verified this session with a URL needs no re-dispatch.
- **Director comparison:** predictions no lens touched become director follow-ups, labeled as yours and outranked accordingly.
- Ideas are not findings: the ideas lens's file-anchored entries and the research lens's URL-or-vision-anchored entries join the report as one separately-numbered menu, each with its lens's `recommended_action`.

**Success criteria:** one merged, numbered findings list + numbered ideas menu, every entry carrying evidence, consequence, and proposed fix.

### 6. Report, then one fork

Render the report in the [Output format](#output-format) below — full evidence inline, nothing the user must take on trust. Write it to `.scratch/skill-audits/<slug>-<UTC>.md` (`date -u +%Y%m%dT%H%M%SZ`), `open` it, and print it in chat.

**Decision page — always, when at least one finding or idea is open.** The evidence-rich layout (facet bar, why/fix rows, diffs, per-item notes) earns its keep even for a single item; only a fully clean pass skips it. Build a picker spec next to the report — one card per finding/idea with id = report number, title, tier badge, `source` naming the lens that raised it, and the structured `summary` / `why` / `fix` / `evidence` fields (never one mashed body block). When the proposed fix is replacement text, emit a `diff` ({location, old, new} — old from the evidence quote) instead of the evidence + fix pair; instruction-style fixes keep the fix row, where a fabricated diff would mislead. Order items by tier across all lenses and give each one `facets: {"tier": <tier>, "lens": <lens>}`; define the page `facets` as a tier group plus a lens group whose per-value `help` lines name each lens's lane — one narrowable list, no tabs hiding most of it. Options are `apply / discuss / skip` with an `option_help` legend; there is no edit option because a note on an applied item *is* the wording adjustment. Defaults: CRITICAL and IMPORTANT findings pre-select `apply`; MINOR, AMBIGUOUS, and ideas pre-select `skip`. Then:

```bash
python3 .github/skills/_shared/picker/render_picker.py <report-dir>/spec.json
PICKER_NO_OPEN=1 python3 .github/skills/_shared/picker/serve_picker.py <report-dir>   # run_in_background
open <url>   # from the server's SERVING line. The session is the only opener — the server's own
             # auto-open is unreliable from a sandboxed background process (silent failure, or a
             # late duplicate tab), so it stays disabled here.
```

Watch the server's stdout (`Monitor`) — a browser submit prints `SELECTION RECEIVED -> <path>` and the blob at that path uses the same selection language as a typed reply (`<id> = <choice>` lines, `note <id>:` riders). Echo the received vector into chat before acting so the transcript stays self-documenting. The page never replaces chat: Copy-selection paste-back and plain typed numbers stay valid the whole time.

Then fire **one** `AskUserQuestion`:

> "Report open. How do you want to act on it?" `header: Mode`
> - "Apply by number" — pick in the served page or type the numbers in chat; I apply each visibly and re-verify substantive rewrites
> - "Route to re-author" — only shown when ≥ 2 CRITICAL findings or any CRITICAL goal-derivability finding landed
> - "Report only — no action"

**Success criteria:** report file written and opened, report in scrollback, decision page served whenever at least one item is open, mode picked. No filesystem change on the audited skill yet.

### 7. Apply by number

Selections arrive as typed chat (`apply 1, 3, 5` · `discuss 2` · `edit 4: <their wording>` · `skip the rest`) or as the picker blob — same semantics; a note on an applied blob number is the user's wording adjustment, the typed `edit 4: <wording>` equivalent. For each applied number: re-read the touched region (earlier fixes shift line numbers), apply via `Edit` so the change is visible, and honor any per-number note. Ideas apply the same way by their numbers; an idea anchored in goal-bearing prose (description, opening paragraph, Done-when, a blindness contract) gets one explicit confirm first. A substantive rewrite (not a word swap) gets one re-verification: dispatch a fresh `Agent` (general-purpose) with the finding text + the post-edit file, asking *confirmed resolved / not resolved / new finding*; cap one re-dispatch per finding, unresolved ones land in the report tail. Git is the recovery path — nothing is committed by this skill.

**Success criteria:** every picked number applied or explicitly bounced with a reason; re-verification verdicts collected for substantive rewrites; unpicked numbers untouched.

### 8. Re-author handoff (only from the Step 6 fork)

```bash
mkdir -p .scratch/skills-backup/skills
cp -r <skill-dir> .scratch/skills-backup/skills/<slug>-$(date -u +%Y%m%dT%H%M%SZ)/
```

Print a seed for `/new-skill <slug>`: the preserved goal, triggers, exclusions, orchestration intent, one line per CRITICAL finding driving the rewrite, and any ideas the user marked for the seed. Do not invoke `/new-skill` yourself — the user reviews the seed and fires it.

**Success criteria:** backup exists at the printed path; seed + invocation form in chat.

### 9. Post-edit sweep (only when edits landed)

- `description` ≤ 1024 chars; combined with `when_to_use` ≤ 1536 — when frontmatter was touched
- AI-tic regex (AGENTS.md § Writing tone) and the abstract-subject probe (`docs/contributing/agent-style-guide.md` § Concrete subject, real verb) against the post-edit body — hits are candidates for a read-aloud, not verdicts
- Every step still carries a discriminating Success criteria field; Done-when still distinct from the last step
- Every reference-file link and dispatched-file path still resolves

Print PASS/FAIL per check; a FAIL gets fixed or recorded as a known concern in the report tail.

**Success criteria:** the sweep block printed; no silent FAIL.

## Output format

```
audit-skill report — <skill-dir>/SKILL.md
=========================================
Goal (director draft): <2–3 sentences>
Probe table: <N/M queries pass | no trigger-evals.json>
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

Director-bias warning: the director read the source and is therefore biased.
Lens findings outrank director observations; the probe table outranks both on routing.
----
Audit run: <UTC> · recommendation: <apply-by-number | re-author | report-only>
```

The same content goes to `.scratch/skill-audits/<slug>-<UTC>.md` so the report survives outside scrollback.

## Red flags — stop and reconsider

- The target isn't a SKILL.md → redirect at Step 1, don't cold-walk the wrong artifact.
- Your Step 3 draft disagrees materially with the lenses → don't paper over it; the lenses win or the dispatch was under-fed.
- Three or more CRITICAL findings → recommend re-author, not patchwork.
- A lens returned nothing after the workflow's retry → name the missing lens in the report rather than quietly auditing with four.

## Don'ts

- Don't apply any change the user didn't pick by number.
- Don't ask an approval question that fails the question rule.
- Don't auto-invoke `/new-skill`; the user fires the seed.
- Don't read other audit-* skills for reference mid-audit; the lens prompts in `audit_wf.js` carry the rules.
- Don't let your read outrank a lens, or a lens outrank the probe table on routing.

## Done when

- The numbered evidence-first report exists at `.scratch/skill-audits/<slug>-<UTC>.md`, was opened, and sits in scrollback.
- `git diff` on the audited skill shows exactly the user's picked numbers — nothing more.
- In re-author mode, the backup + seed are in place and the `/new-skill` invocation is one paste away.
- A reader scrolling this session can answer in a minute: what was found, what the evidence was, what the user picked, what moved.
