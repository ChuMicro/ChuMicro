# Interview — Deep Question Bank with Pushback

**Role.**  A question bank `/new-skill`'s intake conversation draws from — not a gate sequence to march through.  Consult the phase whose area is murky (trigger discovery, scope, procedure form, vocabulary sourcing, agent architecture, stretch angles) for what to ask and how to push back.  The **Pushback patterns** section after the TOC applies to every question regardless of phase.  The intake itself is plain conversation; the widget table below applies only at genuine 2–4-option forks.

**If running low on context mid-interview** (compaction fired, working memory thin), extract a single phase with `awk '/^## Phase N:/,/^## Phase N+1:/' .github/skills/new-skill/interview.md` — replace `N`/`N+1` with the actual phase numbers; for Phase 11, use `/^## Appendix:/` as the end anchor.  Re-extract the framing block at the top (intro + widget table + Pushback patterns) the same way: `awk '/^# Interview/,/^## Phase 0:/' .github/skills/new-skill/interview.md` — it's the standing context for whichever phase you're working.

This reference drives the interview phase of `/new-skill`.  Pick the widget per artifact (see [`spec.md` § Widget selection](spec.md#widget-selection--askuserquestion-vs-plain-text)):

| Artifact | Widget |
|---|---|
| One path from a known set | `AskUserQuestion` single-pick |
| Subset of a finite set of predefined items | `AskUserQuestion` with `multiSelect: true` |
| Free-text content (lists, paragraphs, multi-step walks) | Plain chat — optionally preceded by a one-pick gateway *"ready / show examples first"* |

Every phase produces a concrete artifact the next phase consumes; if a phase exits without its artifact, re-run that phase before moving on.

## Table of contents

- [Pushback patterns](#pushback-patterns) — the philosophy
- [Phase 0: Pre-flight](#phase-0-pre-flight) — mode + slug candidate
- [Phase 1: Trigger discovery](#phase-1-trigger-discovery) — three example user messages
- [Phase 2: Scope boundary](#phase-2-scope-boundary) — in / out / adjacent
- [Phase 3: Audience and context](#phase-3-audience-and-context) — who calls, inline vs fork
- [Phase 4: Frontmatter draft](#phase-4-frontmatter-draft) — name + description
- [Phase 5: Sibling-overlap check](#phase-5-sibling-overlap-check) — compare against the tree
- [Phase 6: Procedure form](#phase-6-procedure-form) — driver vs prose
- [Phase 6.5: Stretch angles (optional)](#phase-65-stretch-angles-optional) — propose 3 angles the author didn't think to ask about, fold / discuss / skip
- [Phase 7: Steps + per-step annotations](#phase-7-steps--per-step-annotations) — per-step success criteria
- [Phase 8: Arguments and tools](#phase-8-arguments-and-tools) — finalize frontmatter
- [Phase 9: Citations, incident trail, and vocabulary sourcing](#phase-9-citations-incident-trail-and-vocabulary-sourcing) — absolutes AND every label / tier / verdict the skill uses
- [Phase 10: Validation via the blind lenses](#phase-10-validation-via-the-blind-lenses) — loader, cold-walk, craft, orchestration, ideas, research
- [Phase 11: Where files land and how the run closes](#phase-11-where-files-land-and-how-the-run-closes) — pointer to SKILL.md Steps 2 and 5
- [Appendix: Trigger-match test](#appendix-trigger-match-test)
- [Appendix: What the validation lenses surface](#appendix-what-the-validation-lenses-surface)

---

## Pushback patterns

The user is not the adversary, but vague answers are.  An interview that accepts *"it handles all the edge cases"* produces a skill that no agent can load cold.  Every vague answer gets restated and challenged.

**The general loop**

1. Read the user's answer aloud (mentally).  Does it name an observable thing — a verb, a file, an artifact, a user message?  If yes, move on.
2. If no, restate the vagueness back: *"You said 'X-related stuff' — that doesn't name a verb.  Try again."*
3. Offer two concrete options the user can pick from instead of leaving the floor open.  An "Other" escape is always available via `AskUserQuestion`.
4. Repeat.  Two rounds of pushback is normal.  Four is fine.  Ten means the user does not yet know what the skill is — at that point, offer to stop the interview and pick it up after they've done the work in a real session.

**Hard-pushback table** (mirrors the table in `SKILL.md`, expanded with example follow-ups):

| User answers… | Pushback | Follow-up options to offer |
|---|---|---|
| *"X-related stuff"* / *"works with X"* | "That doesn't name a verb. Give three user messages that should fire this skill." | (a) "Audit all X for Y," (b) "Generate an X report," (c) "Validate X against Z" |
| *"It's flexible"* / *"handles many cases"* | "Name two invocations that look different. We'll decide whether that's one skill or two." | (a) Same trigger, different arg, (b) Different trigger, similar structure, (c) Two skills sharing a reference file |
| *"It handles edge cases too"* | "Name one edge case concretely. If you can't, it's not in scope yet — we can add it later." | (a) Defer the edge case, (b) Promote it to a real scope item, (c) Split into a sibling skill |
| *"Always do X"* | "After which incident? Where's the evidence? Three observations of the failure mode is the rough cut-off for codifying a rule." | (a) Trace to an incident / ADR, (b) Soften to a guideline, (c) Drop the rule |
| *"Similar to <existing skill>"* | "Then why isn't it just `<existing skill>`? Name the trigger that doesn't overlap, or the procedure step that diverges." | (a) Extend the existing skill, (b) Build a sibling with a clear disambiguator, (c) Stop — the existing skill already does this |
| *"Generates a report"* / *"produces output"* | "Show me one line of the output. What columns?" | (a) Pipe-delimited rows, (b) Markdown punch-list, (c) JSON for piping |
| *"It should be smart about X"* | "Smart how? Describe the decision the skill makes, including the inputs it weighs." | (a) Static rule table, (b) Pattern-match against samples, (c) Defer to user — the skill asks |
| *"Maybe / I'm not sure"* | "We don't have to lock it in. Pick the answer for the most common case; the skill body can note alternatives." | (a) Common case, (b) Rare case, (c) Both via flag |
| Skips a phase's required artifact | "I need <artifact> before the next phase. Pick one of <two drafts I supply>." | (a) Draft A, (b) Draft B, (c) Other — type your own |
| Long aspirational scope | "That's three skills, not one. Pick the first one to build. The others can land later." | (a) Skill A only, (b) Skill A + B as one, (c) Phase 0 of A — the smallest useful version |
| Loops back to a phase already closed | "We settled <artifact> in Phase N.  Either we re-open it (which invalidates <downstream artifacts>) or we keep going.  Which?" | (a) Re-open phase N, (b) Keep going, (c) Park the concern for the cold-walk |

**Stance rule.**  Push back as the engineer-pair would, not as the skeptic.  *"That doesn't name a verb"* lands; *"That's vague and won't work"* gets the user defensive.  The goal is to extract the concrete answer that lives behind the vague one — usually the user knows it, they just didn't think to say it.

---

## Phase 0: Pre-flight

**Goal.**  Decide mode (interview vs spec-in), capture a slug candidate if one was passed, and **route to the right artifact type** — not everything that feels like a skill is a skill.

### Phase 0.5 — Artifact-type routing

Before the interview proceeds, confirm the right artifact is being authored.  Fire once, near the top:

> Q0.5: "What kind of artifact does this work want to be?  Some things that feel like skills are really hooks, agent personas, or CLAUDE.md notes." `header: Artifact type`
> Options:
> - "A slash-command / skill (proceed with `/new-skill`)" — invoked by user typing `/<slug>` or by the main agent matching the description
> - "A hook (deterministic on a tool event — `PreToolUse`, `PostToolUse`, `Stop`, etc.)" — route to `/update-config` for `settings.json` authoring
> - "A CLAUDE.md note (guidance the main agent should always carry)" — write directly into the project's CLAUDE.md
> - "A sub-agent persona alone (no orchestrating skill)" — write directly to `.claude/agents/<name>.md`; no skill needed
> - "Not sure — explain the choices" (then print the routing table below; re-fire Q0.5)

**Routing table** (print as plain text if user picks "Not sure"):

| Right artifact when… | Why |
|---|---|
| User-triggered slash command, multi-step procedure | Skill |
| Fires on a tool event without user input (auto-format after edit, lint before commit, notify on Stop) | Hook |
| Always-on guidance the main agent should carry session-to-session | CLAUDE.md note |
| A reusable persona dispatched by other skills (no procedure of its own) | Agent persona file alone |
| Reusable persona AND its own slash-command procedure | Both — a skill that dispatches the persona |

If the user picks anything other than "skill," stop the interview and route them to the right tool.  If they pick "skill," continue to the rest of Phase 0.

**Questions (only fire what hasn't been answered by the invocation form).**

If the user invoked `/new-skill` with no arguments:

> Q0a: "What's the rough job this skill should do? Pick the closest." `header: Job type`
> Options:
> - "Audit / scan / lint something" — produces a punch-list, fixes safe items
> - "Generate / create something" — produces a new file or artifact
> - "Run / drive / verify something" — invokes code or a tool against state
> - "Reference / cookbook" — answers a class of questions on demand

If the user passed a slug like `/new-skill verify-deploy`:

> Q0b: "I'll use `<slug>` as the working name. Adjust later in Phase 4. Continue?" `header: Slug check`
> Options:
> - "Continue with this slug"
> - "Tweak it now"

If the user passed a slug followed by free-form context (e.g. `/new-skill verify-deploy verifies prod deployments by hitting the health endpoint and posting to Slack`):

**Q0d — surface the parsed seeds before opening the interview.**

Parse the trailing context per the SKILL.md rules.  Group what you found into:

- **Goal / what-the-skill-does**: <quote sentences from the context that describe behavior>
- **Candidate trigger messages**: <2–3 you derive>
- **Candidate exclusions**: <any *"do not X"* / *"not for Y"* phrases>
- **Architecture hints**: <mentions of agents, director, parallel, orchestration, hooks>
- **Quality emphasis**: <any *"thorough"* / *"go the extra mile"* / *"beyond what the user thinks"* phrases>
- **Author-only hints** (NOT carried into the produced SKILL.md): <any reference paths, *"don't read X"* directives that govern the writing process>

Print these as a structured plain-text block.  Then fire:

> Q0d-confirm: "I parsed these seeds from your input. The interview will use them as draft candidates that you confirm or revise per phase. OK to proceed?" `header: Parsed seeds`
> Options:
> - "Yes — open the interview with these seeds"
> - "Edit the seeds first" — accept plain-text revisions
> - "Drop the seeds and run a clean interview" — context becomes scratch context only, not draft candidates

If *"Yes"*, the interview opens normally but each phase **starts with the seed candidates pre-drafted** and asks the user to confirm or revise — saving a round per phase when the seeds are accurate.

If the user passed `--spec`:

The spec is a free-text paragraph, not a branch.  Use the gateway pattern:

> Q0c-gate: "Spec-in mode. Paste a paragraph or two describing the skill — what it does, when it should fire, who calls it. Ready?" `header: Spec ready?`
> Options:
> - "Ready — I'll paste now"
> - "Show me what a good spec looks like first"
> - "Actually, let's do the interview instead"

If *"Ready"* — exit AskUserQuestion and say in plain text: *"Paste the spec now."*  Accept the paragraph in plain chat.  Restate: *"To confirm — the spec is: <quote>. Anything to add or correct?"* Fire a follow-up single-pick: *"Spec correct?"* (Yes / Edit / Switch to interview).

**Exit artifact.**  `{mode, slug_candidate, job_type}`.

**Pushback.**  If the user picks a job-type but then describes a procedure that doesn't fit it (e.g., picks "Audit" but the procedure writes new code), surface in Phase 6.

---

## Phase 1: Trigger discovery

**Goal.**  Three example user messages the skill should fire on, plus three-to-five near-miss messages it should NOT fire on.  These are the loader test material for Phase 4 and the cold-walk in Phase 10, and they persist as `trigger-evals.json` next to the written SKILL.md (so routing stays re-testable after every later description edit).

**The phase 1 question is the most load-bearing in the interview.**  Spend the pushback budget here.  A skill with a vague description never fires — no other phase fixes that.

**Three trigger messages is a free-text artifact, not a branch.**  Use the gateway-plus-plain-text pattern.

**Q1a-gate:** Fire a single-pick `AskUserQuestion`.

> "Phase 1 needs three example user messages that should fire this skill.  Ready to type them, or want to see examples of what a good trigger message looks like first?" `header: Trigger messages`
> Options:
> - "Ready — I have three in mind"
> - "Show me examples of a good trigger message first"
> - "I only have one or two — help me find a third"

**Branch on the answer:**

- If *"Ready"* — exit `AskUserQuestion` and say in plain chat:
  > *"Type your three trigger messages now, one per line, verbatim — the way a user would actually phrase the ask in chat."*
  Accept the next user message as plain text containing all three.

- If *"Show me examples first"* — print this in plain text, then re-fire Q1a-gate:
  > Good trigger messages name a *verb* + *object* a user would actually type:
  > - *"audit the new-decision skill"* (verb=audit, object=skill)
  > - *"lint the YAML in this repo"* (verb=lint, object=YAML)
  > - *"deploy to staging"* (verb=deploy, object=staging env)
  >
  > Bad ones are vague or aspirational:
  > - *"do skill stuff"* — no verb, no object
  > - *"I want a /foo command"* — names the slash command, not the trigger
  > - *"like Y but for Z"* — references another skill instead of naming the message

- If *"I only have one or two"* — exit `AskUserQuestion`, accept what they have in plain chat, then push back: *"Two messages don't cover the range the loader has to route. Either name a third real one, or scope the skill tighter so two cover everything."*

**Pushback after the user types their messages** (each push fires as plain chat, then re-fires Q1a-gate to give them a clean re-entry):

| Answer pattern | Push |
|---|---|
| One example only | "I need three. The loader matches user messages against the description; one example doesn't tell us the range it has to cover." |
| Three near-identical examples | "These all use the same verb. Either the skill is narrower than you think (one trigger), or there's a verb missing. Give me one example using a different verb." |
| Aspirational examples (*"I'd love a skill that…"*) | "What's the simplest version a user types tomorrow? Not the dream — the first one we ship." |
| *"Whatever I'd type"* | "Pick three messages from a session you actually had this week, or could plausibly have next week." |

**Q1b — confirmation:** After three real messages are captured, restate as plain text:

> *"To confirm — the skill should fire on:*
> *(1) `<message1>`*
> *(2) `<message2>`*
> *(3) `<message3>`*
> *Anything to add or correct?"*

Then fire a single-pick `AskUserQuestion`:

> "Trigger set correct?" `header: Confirm triggers`
> Options:
> - "Yes — that covers it"
> - "Add a fourth example" (re-runs the capture loop)
> - "Drop one — it's actually a different skill"
> - "Edit one — I'll say which"

**Q1c — near-miss negatives.**  After the positive set is confirmed, draft three-to-five **near-miss** messages yourself and present them for the user to confirm, edit, or replace: messages that share the skill's keywords or concepts but belong to a sibling skill or to a plain edit.  Obviously-irrelevant negatives (*"write a fibonacci function"* for a deploy skill) test nothing — every negative should be one a naive keyword match would route wrong.  For each, name the `expected_route` (the sibling slug from the Step 1 sibling survey, or `none`).  Write all queries — positive and negative — the way a user actually types: a concrete file path or symbol name, some backstory, casual phrasing, the occasional lowercase or typo.  Abstract requests (*"format this data"*) measure nothing.

> *"These near-misses should NOT fire the skill: (1) `<msg>` → `<sibling|none>` … Confirm, edit, or add your own?"*

**Exit artifact.**  Three positive user-message strings plus three-to-five near-miss strings with expected routes.  These travel through every later phase and become `trigger-evals.json` at write time.

---

## Phase 2: Scope boundary

**Goal.**  Explicit in-scope / out-of-scope / adjacent lists.  Stops the skill from drifting into a kitchen-sink.

Exclusions divide into common categories (faster picked from a list) and specific exclusions (free-text).  Fire the multi-select first to capture the common ones quickly, then a free-text gateway for any specifics.

**Q2a — common exclusion categories (multi-select):**

> "Which of these categories does the skill explicitly NOT handle?  Pick all that apply." `header: Common exclusions` — fire as `multiSelect: true`
> Options:
> - "Markdown / prose docs" — a separate docs skill handles those
> - "A specific file type / language" — e.g. JSON, TOML, YAML — name in Other
> - "A specific runtime / platform" — e.g. Windows-only, mobile-only — name in Other
> - "A specific scale / size" — e.g. *"single files"*, *"trees ≥ 1000 files"*
> - "A specific user role / privilege level" — e.g. CI-only, admin-only
> - "Anything destructive (delete / drop / overwrite)" — skill refuses to do
> - "External services / network calls" — skill stays local
> - "None of these — exclusions are skill-specific"

If the user picks "None of these," proceed to Q2a-gate below.  Otherwise capture the selected categories AND fire Q2a-gate to gather any specifics.

**Q2a-gate (after the multi-select):**

> "Phase 2 needs at least two things this skill should NOT do.  Ready to name them, or want to see what good exclusions look like first?" `header: Out of scope`
> Options:
> - "Ready — I know what to exclude"
> - "Show me what good exclusions look like first"
> - "Nothing comes to mind — help me find one"

**Branch on the answer:**

- If *"Ready"* — exit `AskUserQuestion`:
  > *"Type two things the skill should NOT do, one per line."*
  Accept plain text.

- If *"Show examples first"* — print this in plain text, then re-fire Q2a-gate:
  > Good exclusions name a specific action or scope:
  > - *"Should not edit YAML files — that's a future yaml-fixer skill"*
  > - *"Should not run when no project root is detected"*
  > - *"Should not handle markdown docs — that's a separate sibling skill's job"*
  >
  > Bad exclusions (universal, untestable, not in scope) get caught by the pushback table that follows this question.

- If *"Nothing comes to mind"* — exit `AskUserQuestion` and push back in plain text:
  > *"Look at the three trigger messages from Phase 1.  Is there a user message that's nearby but should NOT fire this skill?  That's an exclusion."*
  Accept plain text.

**Pushback after they type** (each push fires as plain chat, then re-fires Q2a-gate):

| Answer pattern | Push |
|---|---|
| *"I can't think of exclusions"* | "Then it's probably too broad. Look at the three trigger messages — is there an obvious user message that should NOT fire it? That's an exclusion." |
| *"It should not break things"* | "Not an exclusion — every skill respects that. Name a specific action the skill should refuse to take." |
| Exclusion that contradicts Phase 1 | "Trigger message #2 fires on `<X>`, but you said the skill should not do `<X>`. Which is right? Re-run Phase 1, or tighten Phase 2?" |

After the user types two real exclusions, restate them as plain text, then fire a single-pick confirmation:

> "Exclusions correct?" `header: Confirm exclusions`
> Options:
> - "Yes — locked in"
> - "Add a third"
> - "Edit one"

**Q2b:** "Is there an adjacent task that's close but separate? Worth naming explicitly so a user knows which skill to invoke." `header: Adjacent`

Options:
- "Yes — `<adjacent skill name>`"
- "No, the boundary is clear"
- "There's an existing skill that handles the adjacent" (queues a Phase 5 check)

**Exit artifact.**  `{in_scope: [...], out_of_scope: [...], adjacent: [...]}`.

---

## Phase 3: Audience and context

**Goal.**  Decide who invokes the skill and whether it runs inline or in a fork.

**Q3a:** "Who invokes this skill?" `header: Caller`

Options:
- "User types `/<slug>` directly" — slash-command-first; consider `disable-model-invocation: true`
- "Main agent picks it up mid-task from the description" — autonomous load
- "Both — slash-command-friendly and auto-loadable"

**Q3b:** "Inline or fork?" `header: Context`

Options:
- "Inline (default) — runs in this conversation; the user can steer mid-process"
- "Fork — runs in a sub-agent with its own context, reports back when done"
- "Not sure — explain the tradeoff" (then show the tradeoff and re-ask)

The fork-vs-inline tradeoff to read aloud if asked:

> Inline keeps the user in the loop — they see every tool call, can interrupt, can answer mid-process clarifications.  Fork is for self-contained work where there's nothing for the user to add until the final output.  An audit skill is usually inline (the user sign-offs on findings); a smoke-test runner is usually fork.

**Q3c:** "Does the skill need the conversation history before this invocation, or does it start fresh?" `header: Context dependence`

Options:
- "Fresh — the skill body is self-contained"
- "It uses the recent conversation" — only valid for inline; fork can't see it

**Pushback.**

| Answer | Push |
|---|---|
| *"Fork, but it asks questions mid-process"* | "Fork sub-agents can't take live user input — they run to completion. Either inline, or the skill needs to gather all inputs up front." |
| *"It uses recent conversation"* without naming what | "What specifically? A file the user mentioned? An error message? Pin it down — *'uses recent conversation'* is too loose for a SKILL.md body to capture." |

**Exit artifact.**  `{caller, context_mode, conversation_dependence}`.

### Phase 3b: Fork-mode briefing (only when Phase 3b picks `fork`)

**Goal.**  Draft the opening brief the SKILL.md gives to the fork sub-agent.

A fork starts cold — no conversation history, no shared state.  Skill bodies for fork-mode skills must brief the sub-agent the way you would brief a smart colleague who walked into the room: name the goal, the inputs, what is already known or ruled out, and the exact form of the expected output.

The fork brief is free-text the user composes.  Gateway-plus-plain-text pattern.

**Q3b-gate:**

> "Phase 3b drafts the fork's opening brief — three sentences max.  Ready to draft, or want to see two starter templates first?" `header: Fork brief`
> Options:
> - "Ready — I'll draft"
> - "Show me two starter templates first"

**Branch on the answer:**

- If *"Ready"* — exit `AskUserQuestion`:
  > *"Type the fork's opening brief now (≤3 sentences).  Name the goal, inputs, and expected output form."*
  Accept plain text.

- If *"Show templates first"* — print these in plain text, then re-fire Q3b-gate:
  > Two starter templates:
  > - *"You are doing `<task>`.  Your inputs are `<inputs>`.  Report `<output form>` when done."*
  > - *"`<Task>`.  Read `<files>`.  Return `<structured output>`."*

**Pushback after the user types** (each push fires as plain chat, then re-fires the capture):

| Answer pattern | Push |
|---|---|
| *"Just do `<task>`"* | "A fork-agent reading that cold has no idea where to start.  Name the inputs and the expected output." |
| Brief assumes context the fork won't have | "The fork can't see this conversation.  Either inline (default) the skill, or move that context into the brief." |
| Brief delegates synthesis (*"based on your findings, decide…"*) | "Never delegate understanding to a fork.  Tell it what to do, not what to figure out.  Pull the synthesis back into the inline body." |

After a real three-sentence brief lands, restate it as plain text and fire a single-pick confirmation:

> "Brief locked in?" `header: Confirm brief`
> Options:
> - "Yes — use this"
> - "Edit one sentence"
> - "Switch to inline mode — fork is overkill here"

**Exit artifact.**  Three-sentence fork brief, captured for inclusion in the SKILL.md body.

---

## Phase 4: Frontmatter draft

**Goal.**  Candidate `name:` and `description:`.  These get tested against the three trigger messages.

**Q4a:** Suggest a slug.  Derive from job-type + the main verb in the trigger messages.

> "I suggest `<slug>` as the slash-command name. It'll live at `<skill-dir>/<slug>/SKILL.md` and invoke as `/<slug>`." `header: Slug`
> Options:
> - "Use `<slug>`"
> - "Tweak — `<alternative>`"
> - "Different slug" — user fills "Other"

Pushback on names:

| Submitted | Push |
|---|---|
| Includes `helper`, `utility`, `tool` | "Generic suffix. Name the action: `<slug>-<verb>` reads stronger." |
| > 64 chars or has slashes | "Slugs are lowercase + digits + hyphens, ≤64 chars. Try `<shorter alternative>`." |
| Collides with existing skill | "There's already a `<existing>`. Pick a different stem, or extend that skill instead." |

**Q4b:** Draft the description.  Write a candidate, then test against the three trigger messages.

```
description: <verb> <object> <when> Use when <triggering condition>.
            Examples: "<message1>", "<message2>", "<message3>".
```

Show the draft as normal assistant text, then:

> "Read this description aloud. Does it match the three trigger messages? Each one should map to one verb + one object in the description." `header: Description check`
> Options:
> - "Yes — all three map"
> - "Message #1 doesn't match — fix the description"
> - "Message #2 / #3 doesn't match — fix"
> - "The description has words the user wouldn't type"

**Pushback.**

| Issue | Push |
|---|---|
| Description starts *"Tools for…"* / *"Helps with…"* / *"Utilities for…"* | "Vague stem. The loader matches against verbs the user would type. Start with the action: `<rewrite>`." |
| Description has internal jargon (CHU codes, ADR numbers, library names that aren't in trigger messages) | "The loader sees this on every session-start. Jargon burns the only signal it has. Move the citation to the body." |
| Description is > ~400 chars | "Body of the description rides every session-start cost. Cut the elaboration; the body of the SKILL.md is for that." |
| Description doesn't include *"Use when…"* | "The trigger clause is what the loader keys on. Without it, the description tells the loader what it *does* but not *when* to fire." |

**Q4c — body sections (multi-select):** Which body sections will this skill carry?  Fire as `multiSelect: true`:

> "Which sections does the body need? Pick all that apply." `header: Body sections` — fire as `multiSelect: true`
> Options:
> - "Definition of done" — verifiable criteria the agent uses to know the skill ran correctly (recommended for action / driver-backed skills)
> - "Process" — numbered steps with per-step annotations (always)
> - "Output format" — when the skill produces structured output (table / JSON / punch-list)
> - "Red flags" — failure modes the agent should recognize as *"about to ship the wrong thing"*
> - "Don'ts" — explicit anti-actions
> - "Defer / out of scope" — what the skill explicitly hands off elsewhere
> - "Gotchas" — non-obvious traps the author hit during this session (action / driver-backed skills only)
> - "Troubleshooting" — symptom → fix table (action / driver-backed skills only)
> - "Companion agents" — table listing each agent the skill dispatches (orchestrator skills only)

The picked sections become the structure of the SKILL.md body.  Skip the standard Process section — it's always included.

**Exit artifact.**  `{slug, description_draft, body_sections}` — passes the three-message trigger test; section list determines the body skeleton.

---

## Phase 5: Sibling-overlap check

**Goal.**  Surface trigger overlap with any existing skill before locking in the description.

**Pre-step.**  From the SKILL.md procedure, you have the list of every sibling skill's description.  Pull it up.

**For each sibling whose description line shares ≥3 content words with the draft description**, surface as a question:

> "`<sibling>` and the new `<slug>` both look like they'd match `<user message>`. Disambiguate?" `header: Overlap with <sibling>`
> Options:
> - "Tighten the new description to exclude the sibling's case"
> - "Extend the sibling — don't build a new skill"
> - "Build both — they're genuinely different. Add a *Do NOT use to <X>* clause to each"
> - "The overlap is acceptable — both fire and the user picks"

**Pushback.**

| Answer | Push |
|---|---|
| *"They're different"* without naming how | "Name the user message that fires the new skill but NOT the sibling. That's the disambiguator." |
| *"Build both"* with identical trigger clauses | "If both descriptions match the same message, the loader picks one — usually the wrong one. Either tighten or merge." |

**Exit artifact.**  `{overlap_decisions: [...]}` — none, or one per overlapping sibling.

---

## Phase 6: Procedure form

**Goal.**  Decide whether the skill needs a driver (a script next to the SKILL.md that runs code) or is pure prose-procedure.

**Q6a:** "What does the skill *do* in one sentence?" `header: Procedure summary`

Options:
- "Reads files and produces a punch-list" — pure prose; no driver, no agents
- "Runs commands and reports the result" — possible driver
- "Asks the user a series of questions and writes a file" — pure prose; AskUserQuestion-driven
- "Drives an external tool / API / service" — driver almost certainly needed
- "Dispatches one sub-agent to do work I can't / shouldn't do inline" — single fork; e.g. an investigation, a generation pass
- "Dispatches multiple sub-agents in sequence (director pattern — writer → verifier)" — orchestration where agent N's blindness to agent N-1's inputs is load-bearing
- "Dispatches multiple sub-agents in parallel (N independent agents, results aggregated)" — independent passes fired concurrently
- "Should probably be a hook in `settings.json`, not a skill" — deterministic enforcement on a tool event; surfaces as a routing decision
- "Orchestrates other skills via the `Skill` tool" — skill-of-skills

**Pushback.**

| Answer | Push |
|---|---|
| *"It runs some commands"* without naming them | "Which commands? List the first three the skill would invoke." |
| Driver implied but Q3b said *"Fresh — self-contained"* | "If the skill drives external state, it's not self-contained — there's a tool / endpoint / file the body needs to name. Re-run Phase 3, or qualify what 'fresh' means." |
| Multi-agent picked but the verifier can do its job inline | "Why does the verifier need to be a sub-agent? If 'director is biased by reading the source' isn't the answer, the verifier is probably just inline judgment dressed up as architecture." |
| Hook picked but the trigger isn't a tool event | "Hooks fire on `PreToolUse`, `PostToolUse`, `Stop`, etc. — tool-event triggers. If the trigger is *'when the user types /<slug>'*, it's a skill, not a hook." |

**Q6b — driver branch:** (Only if Q6a picks "Runs commands" or "Drives external tool") "Is there an existing CLI / script that already does this?" `header: Existing driver`

Options:
- "Yes — `<command>`. The skill wraps it"
- "No — we'd write a `driver.<ext>` in the skill dir"
- "Partly — `<command>` does X, we'd add Y on top"

**Q6c — hook-routing branch:** (Only if Q6a picks the hook option) "Hook target?" `header: Hook target`

Options:
- "Project hooks — `.claude/settings.json`"
- "Personal hooks — `.claude/settings.local.json`"
- "Not sure — I'll route through `/update-config` after"

**Exit artifact.**  `{procedure_form, driver_decision, existing_tool, agent_architecture_needed}`.  If `procedure_form` is one of {single fork, director, parallel, skill-of-skills}, set `agent_architecture_needed = true` and fire Phase 6b.  If hook-backed, the skill might still be authored as a thin wrapper around the hook, OR the user might decide to skip new-skill entirely and route through `/update-config` — surface that choice before continuing.

### Phase 6b: Agent architecture (only when Phase 6 selected a multi-agent option)

**Goal.**  Identify every sub-agent the skill will dispatch.  For each, decide custom-persona vs general-purpose, check whether the agent file already exists, and gather inputs for any missing personas.

The architecture artifact has one entry per agent role:

```
agent_roles: [
  { name: <slug>, role: <writer|verifier|investigator|...>,
    persona_kind: <custom | general-purpose>,
    persona_exists: <true|false>,
    inputs: <what this agent sees>,
    blind_to: <what this agent must NOT see>,
    output_form: <what it produces>,
    tools: <minimal tool list>,
    sequence_position: <int — 1, 2, 3 for sequential; null for parallel> }
]
```

**Q6b-1:** "How many sub-agent roles does the skill orchestrate? (Roles, not invocations — the regen-comments writer is one role even when fired as four parallel passes over the same file.)" `header: Agent roles`

Options:
- "One — a single sub-agent doing one job"
- "Two — typical director pattern (writer + verifier)"
- "Three — director + writer + verifier, or some other triad"
- "More — describe in plain text"

**Q6b-2 — sequencing:** "Sequential or parallel?" `header: Agent sequencing`

Options:
- "Sequential — agent N's output feeds agent N+1 (director pattern)"
- "Parallel — N independent agents, results aggregated by the director"
- "Mixed — some sequential, some parallel"

**For each agent role, fire the per-agent sub-flow:**

**Q6b-3 — persona kind:** "Agent role `<N>`: custom persona or general-purpose?" `header: Agent <N> persona`

Options:
- "Custom persona at `.claude/agents/<name>.md`" — describe the role; needs its own system prompt
- "General-purpose subagent (`subagent_type: general-purpose`)" — for one-shot research / generation with no special voice or rules
- "Reuse an existing custom persona" — name it; new-skill will verify it exists

**Q6b-4 — persona file check:** (Only if "Custom persona") The skill checks `.claude/agents/<name>.md` for existence:

```bash
ls .claude/agents/<agent-name>.md 2>/dev/null && echo "exists" || echo "missing"
```

Branch:
- If exists — confirm via single-pick: *"`<name>` already exists.  Use as-is, audit it first, or replace it?"*
  Options: *"Use as-is"* | *"Audit via `/audit-skill <name>` before relying on it"* | *"Replace it — different role"*
- If missing — fire the **persona mini-interview** (below).

**Persona mini-interview** (per missing custom subagent):

This is a compact version of the main skill interview, focused on the persona file's smaller surface.  Both `name` and `description` are required in subagent frontmatter; everything else is optional.  Fire the required questions first, then the optional ones the user opts into.

**Required (always fire):**

> **Persona name** — *"What's the slug for this agent?  Lowercase + hyphens, unique across the agents tree."* — gateway → plain text

> **Persona description** — *"One or two sentences: what this agent does + when Claude (or the orchestrating skill) delegates to it.  Name the agent's role concretely.  Don't copy phrasing from another skill's verifier — borrowed vocabulary leaks the wrong scope."* — gateway → plain text

**Optional — fire as a single multi-select gateway, then drill into each picked field:**

> "Which optional subagent fields does this persona need? Pick all that apply." `header: Optional persona fields` — `multiSelect: true`
> Options:
> - `tools` — restrict to a specific tool set (defaults: inherits all)
> - `disallowedTools` — deny specific tools from the inherited or listed set
> - `model` — override the session model (`opus` / `sonnet` / `haiku` / `<full-id>` / `inherit`)
> - `permissionMode` — `default` / `acceptEdits` / `auto` / `dontAsk` / `bypassPermissions` / `plan`
> - `maxTurns` — cap agentic turns before the subagent stops
> - `skills` — preload full skill content at startup (not just the description)
> - `mcpServers` — make specific MCP servers available
> - `hooks` — lifecycle hooks scoped to this subagent
> - `memory` — persistent memory (`user` / `project` / `local`) for cross-session learning
> - `background` — always run as a background task
> - `effort` — override session effort (`low` / `medium` / `high` / `xhigh` / `max`)
> - `isolation` — run in an isolated git worktree
> - `color` — UI color hint

For each picked field, fire a focused plain-text follow-up to gather the value.

**Then gather the role-shape free-text fields:**

> **Inputs the persona sees** — *"What inputs does this agent see at invocation time?  Paths, plus whatever the orchestrating skill's task prompt names."* — gateway → plain text

> **What the persona must NOT see (blindness contract)** — *"For multi-agent patterns, blindness is engineered: each agent's task prompt names ONLY the inputs that agent should see.  What does this persona need to be blind to?  'Nothing' is a valid answer for agents whose role doesn't depend on independence from another agent's view."* — gateway → plain text

> **Output form** — *"What does the persona return to the director?  A list of files written, a structured punch-list, a single verdict, etc."* — gateway → plain text

> **Persona body — system prompt** — gateway → plain text, multi-paragraph
> *"This is the agent's system prompt: the role, the hard rules, the output format.  Write it in second person (e.g., 'You judge …', 'You return …'), with no narrative preamble.  See `template.md` for the persona file skeleton.  Reference bundled scripts (if any) via `${CLAUDE_SKILL_DIR}/...` patterns when the persona dispatches inside a skill that bundles them."*

**Loading caveat to surface to the user:** *"Subagent persona files are loaded at session start.  After `/new-skill` writes a new `.claude/agents/<name>.md`, the user must restart their Claude Code session for the persona to load."*

**Q6b-5 — director bias check:** (Only if director-pattern picked) `header: Director bias`

> "The director (the skill body itself) reads the baseline / source / inputs before dispatching the writer or verifier.  That makes the director a biased reader of agent output.  Confirm you understand:"
> - "Yes — verifier's findings outrank director's observations in the consolidated report"
> - "Explain more first"

If *"Explain more first"* — print this in plain text, then re-fire Q6b-5:

> The director — the assistant invoking this skill — saw the inputs during the procedure (reading files, gathering data, surveying state).  That makes the director a biased reader of any downstream agent's output: it knows what *should* be in the output because it saw what *was* in the inputs.  A director's *"this looks fine"* is unreliable.
>
> The second-stage agent in a director pattern is independent of that bias — its task prompt names only what it should see.  When reporting to the user, prefer the second-stage agent's findings over the director's observations.  If the director noticed something the agent missed, mention it as a single follow-up note — don't substitute the director's bias for the agent's blindness.

**Q6b-6 — parallel dispatch confirm:** (Only if parallel sequencing picked) `header: Parallel dispatch`

> "Parallel dispatch fires N `Agent` tool calls in ONE message — that's how the harness runs them concurrently.  Confirm the skill body will batch the dispatches into a single message?"
> - "Yes — batch into one message"
> - "Walk me through the batching pattern"

If *"Walk me through the batching pattern"* — print this in plain text, then re-fire Q6b-6:

> ```
> Message 1: <Agent call 1> <Agent call 2> <Agent call 3>     ← all three run in parallel
> Message 2: (wait for all three to complete, then consolidate)
> ```
>
> Sequential messages serialize the calls; concurrency comes from batching them into one message.  The procedure step describing this dispatch should say *"in one message, fire `Agent` for each <input>"* — explicit batching, not implicit.

**Q6b-7 — multi-level ecosystem (multi-select):**  Architectures sometimes nest.  An agent the skill dispatches might itself dispatch further agents, invoke other skills, or rely on hooks.  Fire as `multiSelect: true`:

> "What else is in the ecosystem? Pick all that apply." `header: Ecosystem`
> Options:
> - "One level only — skill dispatches N agents, agents do not nest further"
> - "Nested dispatch — at least one sub-agent itself dispatches further sub-agents"
> - "Skill-of-skills — the orchestrating skill invokes other skills via the `Skill` tool"
> - "A hook in `settings.json` complements the skill" — e.g. a `PostToolUse` hook that fires the skill, or a `Stop` hook that triggers it on session end
> - "A CLI / driver script" — committed alongside the SKILL.md, invoked by the procedure
> - "A reference data file" — table / config the skill reads at invocation time
> - "Not sure — show me what each looks like" (print the ecosystem-table below, re-fire)

**Ecosystem table** (print as plain text if user picks "Not sure"):

| Component | Lives at | When the skill needs it |
|---|---|---|
| Skill body | `.claude/skills/<slug>/SKILL.md` | Always |
| Reference files | `<skill-dir>/<file>.md` | When the SKILL.md links to them; one hop deep only |
| Driver script | `<skill-dir>/driver.<ext>` | When Phase 6 picked a driver-backed type |
| Sub-agent persona | `.claude/agents/<name>.md` | When Phase 6 picked single-fork / director / parallel |
| Nested sub-agent persona | `.claude/agents/<name>.md` | When a sub-agent itself dispatches further agents |
| Hook entry | `settings.json` | When deterministic enforcement on a tool event is part of the design |
| Sub-skill (skill-of-skills) | `.claude/skills/<sub-slug>/SKILL.md` | When the orchestrator invokes another skill via the `Skill` tool |

**For each picked component, fire a focused follow-up:**

- **Nested dispatch** — *"Which sub-agent role nests further, and what does the nested level dispatch?"* (plain text) — produces the additional `agent_roles` entries and their `dispatched_by: <parent-agent>` field
- **Skill-of-skills** — *"Which sub-skills are invoked? Are they sequential or parallel?"* (plain text + the same parallel-dispatch confirm pattern as Q6b-6)
- **Hook** — exit to a brief sub-flow: *"Hook event (`PreToolUse` / `PostToolUse` / `Stop` / other), matcher (which tool fires it), and target file (`.claude/settings.json` vs `.claude/settings.local.json`)."*  The skill itself does not author the hook; it tells the user to also run `/update-config` to author the `settings.json` entry.
- **CLI / driver script** — re-confirms Phase 6's driver decision; gathers the exact filename and what it does
- **Reference data file** — gathers filename, format, what the SKILL.md does with it

**Pushback.**

| Answer | Push |
|---|---|
| *"Two agents, but both are general-purpose"* | "If both are general-purpose, are they really two roles or one role fired twice in parallel? If two roles with two personas, name the role distinction." |
| Verifier persona has `tools: Read, Write, Edit` | "A verifier that can write is no longer blind to its own output. Strip Write/Edit — verifiers report, they don't fix." |
| Director-pattern picked but no blindness contract | "Why two agents then? If the second agent sees what the first agent saw, you've just split one job in half. Either name the blindness or collapse to single-agent." |
| Persona body restates the orchestrating skill's rules | "Don't restate. The persona file is loaded as the agent's system prompt; the skill body's task prompt only carries paths and per-invocation specifics." |
| Nested dispatch picked but the nesting reason is *"more thoroughness"* | "Nesting is for when the inner agent needs its own blindness / its own tool subset / its own model — not for stacking thoroughness. Justify the nesting." |
| Hook picked alongside an inline skill | "The hook fires deterministically on a tool event; the skill fires on user intent. Confirm these two triggers don't compete — name one user-typed example for the skill and one tool event for the hook." |

**Exit artifact.**  `agent_roles: [...]` — one entry per role (including nested), every custom persona either confirmed to exist or fully specified for write.  Plus `ecosystem: { nested: bool, skill_of_skills: [...], hook: {...}, driver: {...}, data_files: [...] }`.

**The Phase 6b output drives Process step 2 (draft to disk).**  Multi-level ecosystems mean multiple writes spread across multiple paths.  Step 2's success criteria includes verifying each component landed at its expected path.

---

## Phase 6.5: Stretch angles (optional)

**Goal.**  After procedure form is locked, give the user a chance to fold in angles they probably didn't think to ask about — alternative framings, adjacent problems to fold in, harness affordances not reached for, output-shape rethinks, lifecycle gaps.  This is the design-time complement to Phase 10's ideas-reader: surface ideation while the scope is still cheap to change, before per-step annotations land.

**When this fires.**  Default-on for the full-lifecycle tier.  Optional on three-to-five-step tier (gated by Q6.5a below).  Skipped on two-step trivial.

**Q6.5a — opt-in gate.**

> "Run a stretch-angles check before locking the steps? Three candidate angles based on what we have so far — fold any in, discuss inline, or skip." `header: Stretch angles`
> Options:
> - *"Yes — propose three angles"*
> - *"Skip — proceed to Phase 7 with the current draft"*

If *Skip*, exit the phase. Otherwise continue to Q6.5b.

**Q6.5b — propose and pick.**  Draft 3 stretch-angle candidates as plain text, grounded in what's been gathered so far (the goal from Phase 0, the scope from Phase 2, the procedure form from Phase 6). Each candidate names:

- A one-line title
- The kind: alternative framing | adjacent problem | harness affordance | scope expansion | scope contraction | lifecycle gap | output-shape rethink | inversion
- What the current draft does in that area
- What changes if the angle lands

Then fire `multiSelect: true`:

> "Three stretch-angles. Fold any in before we lock the steps?" `header: Pick angles`
> Options:
> - One row per candidate: *"`<title>` [`<kind>`]"*
> - *"Skip all — proceed to Phase 7"*

**Q6.5c — per picked angle.**  For each picked candidate, fire a follow-up:

> "Angle `<title>`: fold in how?" `header: <title>`
> Options:
> - *"Apply as-drafted — update the in-progress draft per the angle"*
> - *"Apply with edits — I'll revise the wording"*
> - *"Discuss inline first"* — expand the angle in chat (rationale, tradeoffs, what changes if applied); re-fire Q6.5c after the discussion.
> - *"Skip after all — leave the draft as it was"*

For *Apply*, update the in-memory draft (scope, procedure-form notes, or wherever the angle landed) and print the diff for sign-off before continuing.  Angles do **not** get filed to `plans/next-up.md` — the interview is the place to solve them, not a bullet that rots.

**Pushback.**

| Answer | Push |
|---|---|
| *"Apply"* an angle that broadens scope past Phase 2 | "This angle adds `<Y>` to scope, but Phase 2 marked `<Y>` as out-of-scope.  Re-open Phase 2 (intentional scope expansion) or skip the angle (keep the skill focused).  Pick *Discuss inline first* if unsure." |
| Three candidate angles are all minor riffs on one idea | "When all three candidates land in the same kind, the stretch is trivial.  Re-draft across different kinds, or skip the phase." |
| User picks all three reflexively | "Folding three angles at once is rewriting the skill mid-interview.  Pick the one that matters most; skip the others or Discuss them inline to scope properly before deciding." |

**Exit artifact.**  `stretch_angles_outcomes: [...]` — one entry per proposed angle (applied / edited / discussed / skipped).  The in-progress draft reflects applied / edited angles.

---

## Phase 7: Steps + per-step annotations

**Goal.**  Numbered procedure with per-step annotations.  Each step has Success criteria; others (Execution, Artifacts, Human checkpoint, Rules) are conditional.

The procedure walk is a multi-step free-text artifact.  Gateway-plus-plain-text pattern.

**Q7a-gate:**

> "Phase 7 captures the numbered procedure — what the skill does, step by step.  Ready to walk it, or want me to draft from the job-type + Q6a answer first?" `header: Procedure walk`
> Options:
> - "Ready — I'll walk it"
> - "Draft from the job-type first — I'll edit"
> - "I don't know yet — show me a draft and we'll iterate"

**Branch:**

- If *"Ready"* — exit `AskUserQuestion`:
  > *"Walk the procedure now, numbered.  One line per step.  Don't worry about success criteria yet — that's Q7b."*
  Accept plain text.

- If *"Draft from job-type"* or *"Don't know yet"* — print a draft procedure as plain text based on job-type and Q6a, then re-fire Q7a-gate with two options:
  > Options:
  > - "Use this — proceed to Q7b"
  > - "Edit it — I'll send revised steps"

**Q7b — per step, one multi-select.**  For each step the user named, fire ONE `multiSelect: true` question instead of three sequential probes:

> "Step `<n>`: which annotations does this step carry? (Success criteria is required when the skill has more than two steps; the rest are conditional.)" `header: Step <n> annotations` — fire as `multiSelect: true`
> Options:
> - "Success criteria" — one observable artifact or assertion that proves the step is done (required for non-trivial skills)
> - "Execution: non-Direct" — Task agent / Teammate / [human] (only when not Direct)
> - "Artifacts" — data this step produces that later steps consume (PR number, commit SHA, file path)
> - "Human checkpoint" — pause and confirm with the user before proceeding (for irreversible actions, error judgment, output review)
> - "Rules" — hard rule(s) the step must respect

**For each annotation the user picked, fire a focused follow-up:**

- **Success criteria** → single-pick gateway: *"Pick the shape that fits, or type your own in Other"* `header: Step <n> success kind`
  Options: *"A file exists at `<path>`"* | *"A command returns exit 0"* | *"A grep / assertion matches"* | *"User confirms via AskUserQuestion"* | *"Other"*
- **Execution** → single-pick: `Task agent` | `Teammate` | `[human]`
- **Artifacts** → plain text: *"Name the artifact(s) this step produces."*
- **Human checkpoint** → plain text: *"One sentence: what the user confirms at this checkpoint."*
- **Rules** → plain text: *"State the rule(s) — one per line."*

**Pushback.**

| Answer | Push |
|---|---|
| Success criterion is *"the step is done"* / *"X is complete"* | "That's tautological. What changes in the filesystem, the command output, or the user's view? Name the observable." |
| Step is *"figure out X"* | "*Figure out* is not a procedure. Either it's `grep <pattern>` (concrete) or it's `AskUserQuestion` (concrete). Pick." |
| Procedure walks past the success artifact | "You said Step N produces `<artifact>` and Step N+1 uses it — but Step N's success criterion doesn't mention `<artifact>`. Either Step N is wrong or Step N's success criterion needs to assert the artifact exists." |

**Q7c:** "Done-when. What's the observable end-state for the whole skill — distinct from the last Process step?" `header: Done-when`

Options:
- "All Process steps completed AND `<observable check>`"
- "User explicitly confirmed `<artifact>` is acceptable"
- "Other"

Pushback if Done-when is the same as the last step: *"That's just step N. Done-when describes the state, not the action. What's the state?"*

**Exit artifact.**  Numbered procedure with annotations + Done-when block.

---

## Phase 8: Arguments and tools

**Goal.**  Final frontmatter — `allowed-tools`, `argument-hint`, `arguments`, `context`, `disable-model-invocation` as needed.

**Q8a:** "Does the skill take arguments?" `header: Arguments`

Options:
- "Yes — `<list>` (required + optional)"
- "No — it elicits everything via questions or auto-detect"
- "Yes — but the body can take them via `$ARGUMENTS` without naming them individually"

If yes, follow up with `argument-hint:` syntax: `[<optional>] <required>`.

**Q8b:** "Which tools does the skill actually need? Pick the minimal set." `header: Tools` — fire as `multiSelect: true`

Options (the user picks any number; tools come from a finite predefined set):
- "File ops" — `Read`, `Write`, `Edit`, `Glob`, `Grep`
- "Bash for specific prefixes" — user names prefixes in Other (e.g. `Bash(npm *)`, `Bash(find *)`); never bare `Bash`
- "AskUserQuestion" — for any interactive skill
- "WebFetch / WebSearch" — only if the skill genuinely needs network
- "MCP tools" — user names the `mcp__<server>__<tool>` patterns in Other
- "Sub-agent dispatch (`Agent`)" — for fork-mode skills that dispatch sub-agents

After the multi-select returns, fire a single-pick to capture any Bash prefixes or MCP patterns the user named in Other:

> "Any Bash prefixes or MCP tools to name? Type them now, or skip." `header: Tool names`
> Options:
> - "Skip — covered above"
> - "I'll name them in plain text"

**Q8c:** "If the skill has side effects (deploys, sends messages, commits), should only the user trigger it?" `header: Invocation policy`

Options:
- "Only the user — `disable-model-invocation: true`"
- "Either — main agent can auto-load it"
- "It has no side effects"

**Exit artifact.**  Final frontmatter block.

---

## Phase 9: Citations, incident trail, and vocabulary sourcing

**Goal.**  Two passes:

1. **Pass A — absolute rules.**  Every *"always do X"* / *"never do Y"* traces to a source.  Otherwise softened to a guideline.
2. **Pass B — every named vocabulary in the draft.**  Every label, tier name, severity scale, verdict scheme, finding-type, status enum, or output-row column header has a named source.  Unsourced vocabulary is rejected.

Pass B catches the failure mode where the agent imports terminology from training data, loader-injected sibling descriptions, or vague pattern-matching — terminology that *sounds* universal but came from a specific other skill whose job is different from this one.

### Pass A — absolute rules

**Pre-step.**  Read the procedure draft and extract every imperative — *always*, *never*, *must*, *should*.

**For each:**

> "Rule: *<extracted rule>*. What's the source?" `header: Rule for <rule>`
> Options:
> - "Linked doc / decision file `<path>`"
> - "An incident — `<one-line description>`"
> - "Three prior observations — I'll list them" (user fills "Other")
> - "No source — soften to a guideline (*'prefer X'*, *'usually Y'*)"
> - "No source — drop the rule"

### Pass B — vocabulary sourcing

**Pre-step.**  Scan the draft for vocabulary the skill introduces.  Categories to check:

- **Tier / severity labels** in tiered findings output (e.g. names you'd put in a punch-list column)
- **Verdict / status enums** (e.g. names for overall success states)
- **Finding-type / category names** (e.g. labels for kinds of issues a finding can be)
- **Phase / stage / mode names** the skill uses (if not borrowed from this skill's own template)
- **Output row / column headers** in any structured output

For each piece of vocabulary, fire:

> "Vocabulary: *<term-set the skill uses>*.  What's the source?" `header: Source for <vocabulary>`
> Options:
> - "Borrowed from a published Anthropic skill — `<name and link>`"
> - "From a project doc — `<path>` the skill cites"
> - "Invented for this skill — and the skill body defines each term inline as part of its output contract"
> - "Unsourced — re-draft using a published scheme or inline-defined terms"

**Rejection rule.**  If a vocabulary is "unsourced — re-draft" and the agent cannot name a source on the next round, **block the draft from proceeding to Phase 11**.  Return to Phase 7 to re-design the output format using a sourced vocabulary or explicit inline definitions.  Unsourced vocabulary is the most common leak vector — *KEEP/TRIM/REFACTOR/REWRITE*, *HIGH/IMPORTANT/MINOR/AMBIGUOUS*, and similar are signals that the agent pattern-matched from training or from sibling-skill descriptions in the loader rather than sourcing.

### Pushback (both passes)

| Answer | Push |
|---|---|
| *"It's just good practice"* (Pass A) | "Good practice is a guideline, not an absolute. Either trace it or soften the wording." |
| *"Everyone knows X"* (Pass A) | "If everyone knows it, the skill doesn't need to assert it. Drop." |
| Doc cited but the doc doesn't actually say the rule (Pass A) | "I read the doc — it covers `<A>` but not the specific rule `<B>`. Either find a closer source or soften." |
| *"That vocabulary is standard"* without naming where (Pass B) | "*Standard* in which skill or doc? Name the source. If you can't, the vocabulary came from training pattern-match — re-draft." |
| Vocabulary from a sibling skill not in this skill's allowed sources (Pass B) | "Sibling skill vocabulary is exactly the bias new-skill exists to prevent. Either invent and inline-define, or borrow from a published Anthropic skill that's truly standard." |

**Exit artifact.**  Pass A: every absolute rule is sourced, softened, or dropped.  Pass B: every introduced vocabulary has a named source.  Neither pass leaves unsourced terminology in the draft.

---

## Phase 10: Validation via the blind lenses

**Goal.**  Surface the gaps mechanical sweeps miss — the content the skill *doesn't* have, plus the angles the author didn't think to ask about.

**The author cannot do the cold-walk themselves.**  By Phase 10 the author has gathered the user's intake answers, drafted the description, and walked every Process step.  The author's *"this looks fine"* is unreliable.  SKILL.md Step 3 owns the dispatch: the `Workflow` call to `.github/skills/_shared/audit_wf.js` runs five blind lenses (loader, cold-walk, craft, orchestration, ideas) and an outward research lens, plus the probe lane — this phase describes what the lenses surface, not a fan-out to run by hand.  Each lens reads only what its prompt names (the research lens additionally searches the web and the live Claude Code docs); none sees the user's intake answers or the author's drafting context.

The four checklist lenses return tiered, evidence-carrying findings.  The ideas lens returns a curated menu (up to 5) of improvements the author probably did not consider — alternative framings, adjacent problems to fold in, harness affordances not reached for, scope adjustments — each with a recommended action.  The research lens returns a second menu (up to 5) anchored outward instead of inward: prior art for the skill's goal, capabilities present in an ideal-version sketch but absent from the draft, and harness capabilities from the live Claude Code docs — each anchored to a URL or marked vision.  Ideas from either menu are **not findings**; they never gate sign-off.  Ideas do **not** get filed to `plans/next-up.md` — the authoring session is the place to solve them, not a bullet that rots.

Resolve everything per SKILL.md Step 4: one numbered report (tier, quoted evidence, consequence, exact proposed fix; ideas continue the numbering), picks in plain chat — `apply 1, 3` · `discuss 2` · `edit 4: <wording>` · `skip the rest`.

**Pushback.**

| Answer | Push |
|---|---|
| *"Accept the gap"* on a description-level finding | "Description-level gaps mean the loader won't route the trigger messages. That's the one thing we can't ship with." |
| *"Apply the fix"* but the fix contradicts Phase 1 trigger messages | "The fix changes the trigger. Re-run Phase 1, or change the fix." |
| *"Apply"* an idea that contradicts the Phase 2 scope | "This idea expands scope past what Phase 2 named in-scope. Re-open Phase 2 (intentional expansion), or skip the idea (keep current scope). Pick *discuss* if unsure." |

**Exit artifact.**  Every numbered item resolved or explicitly accepted; each idea has an outcome (applied / edited / discussed / skipped).

---

## Phase 11: Where files land and how the run closes

**Goal.**  A pointer, not a phase of its own.  Files land on disk at SKILL.md Process step 2 — the lenses and probes need them there, and git is the safety net — so there is no separate show-confirm-write gate; the user steers through the intake conversation before the draft and the numbered report after it.  The run closes with SKILL.md Step 5's closing block: files written with line counts, the `/<slug>` invocation form, and the user's next actions.

**Pushback.**

| Answer | Push |
|---|---|
| *"Throw it away — start over"* late in the run | "The draft is on disk and uncommitted — the next intake can overwrite it, and the pushback work survives in this chat either way. Sure you want a full restart rather than re-opening the phase that went wrong?" |

**Exit artifact.**  Files on disk per Step 2; closing block printed per Step 5.

---

## Appendix: Trigger-match test

For each of the three example user messages from Phase 1, verify the draft description would route it:

1. Read the message aloud.
2. Read the description aloud.
3. Ask: would a loader matching user-message → description pick this skill?
4. The match passes if:
   - At least one verb in the message appears (or is a synonym of a verb) in the description.
   - The object the user names is mentioned in the description.
   - The *when* clause in the description plausibly covers the message's context.
5. The match fails if:
   - The description is jargon-heavy and the message uses plain language.
   - The description names a different verb than the message.
   - The *when* clause is missing.

Mark each message ✓ or ✗.  Three ✓ is the bar.  Two ✓ means iterate the description.  One ✓ or fewer means the scope or trigger is wrong — re-run Phase 1 or Phase 2.

---

## Appendix: What the validation lenses surface

(The shared lens workflow — `.github/skills/_shared/audit_wf.js` — implements these checks; sibling trigger overlap is measured by the probe lane rather than judged. The lists below describe what comes back, per lens.)

### Loader agent

Reads only the `description:` line.  Surfaces:

- Vague stem (*"Tools for…"*, *"Helps with"*, *"Utilities for"*) → finding.
- Description missing *what* → finding.
- Description missing *when* → finding.
- Description > ~400 chars triggering text → finding (loader cost).
- Internal jargon in the description → finding (loader has no way to match).
- Description verbs don't include any verb a Phase-1 user message uses → finding.

### Triggering agent

Has matched.  Opens the body cold, no prior conversation.  Surfaces:

- No exit condition / Done-when block → finding.
- *"As we discussed"* / *"continuing from earlier"* references → finding.
- Arguments referenced but not documented → finding.
- Procedure that requires jumping around (Step 3 says "first do what Step 5 says") → finding.
- Narrative preamble before any actionable step → finding.
- A Process step without Success criteria → finding.
- A reference file linked but missing on disk → finding.
- A reference file > 100 lines without a table of contents → finding.

### Sibling-skill author

Adding a new skill next month.  Checks whether the new task overlaps.  Surfaces:

- Trigger phrase overlap with an existing skill not disambiguated in the description → finding.
- Re-implements logic an existing skill already does (instead of citing) → finding.
- Restates a rule from an existing source-of-truth doc → finding.
- The new skill's name is confusable with an existing skill's name → finding.

### Ideas agent

Reads the draft cold and proposes a curated menu — up to 5 improvements the author probably did not consider.  Output is a menu, not findings; ideas don't gate sign-off.  Surfaces:

- Alternative framing the author didn't see (different decomposition that might cover more ground).
- Adjacent problem small enough to fold in (shares the skill's tooling, extends value).
- Harness affordance the skill could reach for but doesn't (`ScheduleWakeup`, `SendUserFile`, `multiSelect`, hooks, parallel `Agent` batching).
- Scope expansion / contraction that would sharpen the deliverable.
- Lifecycle gap (idempotent re-invocation, recovery after partial failure, retiring the skill).
- Output-shape rethink (table where there's prose; `SendUserFile` attachment where there's a wall of text).
- Inversion (the skill always does X — when shouldn't it?).

### Source-first discipline

For each load-bearing piece (description, Procedure, Done-when), draft the ideal version from a fresh read of what this skill does *before* re-reading the actual draft.  Items present in your fresh draft but absent from the actual are gaps mechanical sweeps miss.
