export const meta = {
  name: 'audit-skill-lenses',
  description: 'Six blind audit lenses plus an outward research lens over one SKILL.md, schema-validated output',
  phases: [{ title: 'Audit' }],
}

// args: { skillPath, referenceFiles: [], personaFiles: [], scriptFiles: [], triggerMessages: [], sizing: '' }
// sizing is the director's measured size table (lines / words / estimated tokens / longest
// line per file) — measured numbers outrank a lens's own counting, so they ride into the
// cold-walk prompt verbatim. scriptFiles are bundled executables for the craft lens.
// Accept both an object and a JSON-encoded string — stringified args reach the script
// as one string, and reading .skillPath off a string silently yields undefined, which
// would dispatch every lens against the literal path "undefined". The guard below
// makes that failure loud and immediate instead.
const input = typeof args === 'string' ? JSON.parse(args) : (args || {})
const skill = input.skillPath
const refs = input.referenceFiles || []
const personas = input.personaFiles || []
const scripts = input.scriptFiles || []
const triggers = input.triggerMessages || []
const sizing = input.sizing || ''
if (!skill || typeof skill !== 'string' || skill === 'undefined') {
  throw new Error(`audit target unresolved: skillPath=${JSON.stringify(skill)} — pass args {skillPath, referenceFiles, personaFiles, triggerMessages}`)
}

const FENCE = 'Read only the files this prompt names. Do not read any other skill, persona, or reference file.'

// Every finding carries its evidence so the director can show the user a decidable
// question. A finding without a quote and a consequence is unusable downstream.
const FINDING_ITEM = {
  type: 'object',
  required: ['tier', 'finding', 'evidence', 'why', 'proposed_fix'],
  properties: {
    tier: { enum: ['CRITICAL', 'IMPORTANT', 'MINOR', 'AMBIGUOUS'] },
    finding: { type: 'string', description: 'one sentence naming the defect' },
    evidence: { type: 'string', description: 'file:line plus a short verbatim quote' },
    why: { type: 'string', description: 'the consequence for a real run, one plain sentence' },
    proposed_fix: { type: 'string', description: 'the exact replacement text or concrete change; empty string when only the author can draft it' },
    harness_claim: { type: 'boolean', description: 'true when the finding rests on documented Claude Code behavior (field semantics, caps, loader mechanics) rather than judgment' },
  },
}
const FINDINGS = {
  type: 'object', required: ['findings'],
  properties: { findings: { type: 'array', items: FINDING_ITEM } },
}
const LOADER_OUT = {
  type: 'object', required: ['routing', 'near_miss', 'findings'],
  properties: {
    routing: {
      type: 'array',
      items: {
        type: 'object', required: ['message', 'routes', 'reason'],
        properties: { message: { type: 'string' }, routes: { type: 'boolean' }, reason: { type: 'string' } },
      },
    },
    near_miss: {
      type: 'object', required: ['query', 'would_route', 'reason'],
      properties: { query: { type: 'string' }, would_route: { type: 'boolean' }, reason: { type: 'string' } },
    },
    findings: { type: 'array', items: FINDING_ITEM },
  },
}
const COLD_OUT = {
  type: 'object', required: ['goal', 'findings'],
  properties: {
    goal: {
      type: 'object', required: ['derivable', 'statement'],
      properties: { derivable: { type: 'boolean' }, statement: { type: 'string', description: 'the one-sentence goal you derived, or why you could not' } },
    },
    findings: { type: 'array', items: FINDING_ITEM },
  },
}
const RESEARCH_OUT = {
  type: 'object', required: ['ideas'],
  properties: {
    ideas: {
      type: 'array', maxItems: 5,
      items: {
        type: 'object', required: ['title', 'kind', 'source', 'change', 'recommended_action'],
        properties: {
          title: { type: 'string' },
          kind: { enum: ['prior-art', 'vision', 'toolset'] },
          source: { type: 'string', description: 'the URL actually read for prior-art and toolset ideas; the word "vision" plus a one-clause rationale for vision ideas' },
          change: { type: 'string', description: 'what changes if this lands, one sentence' },
          recommended_action: { enum: ['apply-inline', 'apply-with-edits', 'discuss-first'] },
        },
      },
    },
  },
}
const IDEAS_OUT = {
  type: 'object', required: ['ideas'],
  properties: {
    ideas: {
      type: 'array', maxItems: 5,
      items: {
        type: 'object', required: ['title', 'kind', 'wild', 'anchor', 'change', 'recommended_action'],
        properties: {
          title: { type: 'string' },
          kind: { enum: ['alternative-framing', 'adjacent-problem', 'harness-affordance', 'scope-adjustment', 'lifecycle-gap', 'output-shape', 'persona-lens', 'cross-cutting'] },
          wild: { type: 'boolean', description: 'true for the one loosened-plausibility idea allowed per menu' },
          anchor: { type: 'string', description: 'file:line or section the idea grows from' },
          change: { type: 'string', description: 'what changes if this lands, one sentence' },
          recommended_action: { enum: ['apply-inline', 'apply-with-edits', 'discuss-first'] },
        },
      },
    },
  },
}

phase('Audit')

const [loader, cold, craft, orchestration, surprise, ideas, research] = await parallel([
  () => agent(
    `${FENCE}\n\nRead ONLY the YAML frontmatter of ${skill} — stop at the closing ---. Do not open the body.\n\n` +
    `Judge whether the skill loader would route each of these user messages to this skill on the description/when_to_use text alone:\n` +
    triggers.map((m, i) => `${i + 1}. "${m}"`).join('\n') +
    `\n\nThen draft one near-miss query — a message sharing this skill's keywords but needing a different tool — and judge whether the description stays silent on it.\n\n` +
    `Work through every numbered rule below in order; skip none.\n` +
    `1. The description opens third-person with what-it-does, then a "Use when" coda — both halves required; no first or second person anywhere.\n` +
    `2. Verbs a user would type, not abstract stand-ins (handle, manage); no vague stems ("Tools for…", "Helps with…"); no implementation leak — the description sells when to route, not how the body works.\n` +
    `3. Pushy about adjacent phrasings — the loader under-triggers, so the description names the keywords and nearby asks a user would actually type — while staying precise against near-misses; a "Do NOT use" clause when a sibling tool shares the boundary.\n` +
    `4. The key use case leads: the skill listing truncates the combined description + when_to_use text at 1,536 characters, so a trigger placed past the cap never routes (harness_claim: true).\n` +
    `5. Caps: description <= 1024 chars hard, description + when_to_use <= 1536 combined; neither field contains XML tags (mark cap and XML findings harness_claim: true — they rest on documented loader behavior).\n` +
    `6. name (or the directory name when name is omitted): <= 64 chars, lowercase/digits/hyphens, never "anthropic" or "claude"; gerund form (verb + -ing) is the documented preference, and a vague or generic name (helper, utils, tools, documents, data, files) is a MINOR finding.\n` +
    `7. allowed-tools carries prefix-scoped Bash forms, never bare Bash, and includes AskUserQuestion when the body asks the user anything.\n` +
    `8. Execution-control fields stay consistent: context: fork fits only a skill that runs to completion without user input — fork alongside AskUserQuestion in allowed-tools contradicts itself, and fork on guideline-only content returns nothing; a description naming side effects (deploys, commits, sends) wants disable-model-invocation: true (harness_claim: true).\n\n` +
    `For every finding: evidence = the frontmatter line quoted; why = what misroutes or fails to load in production; proposed_fix = the exact replacement text. Strict marking: a borderline routing call is a miss with the reason stated.`,
    { label: 'lens:loader', schema: LOADER_OUT }),

  () => agent(
    `${FENCE}\n\nCold-walk the body of ${skill} top-to-bottom as a fresh agent about to execute it` +
    (refs.length ? `, plus its reference files (one hop): ${refs.join(', ')}` : ' (the skill directory has no reference files)') + `.\n\n` +
    (sizing ? `Measured sizing (director-supplied; trust these numbers over your own count):\n${sizing}\n\n` : '') +
    `Work through every numbered check below in order; skip none.\n` +
    `1. Goal-derivability — state the skill's goal in one sentence after the read, or report why you cannot.\n` +
    `2. Section ordering — procedure first, narrative buried below it.\n` +
    `3. Walkability — no step depends on a later step; every linked reference file exists.\n` +
    `4. Per-step Success criteria — present on every step past two, observable, and DISCRIMINATING: a clearly-wrong run must fail it ("report generated" passes on an empty report — flag like a missing criterion).\n` +
    `5. A Done-when block distinct from the last step — the last step is what you do; Done-when is what you observe after. Local convention, not a documented Anthropic rule: flag its absence, never cite documentation for it.\n` +
    `6. Size against both documented budgets: <= 500 lines AND under ~5,000 tokens (~20,000 characters; tokens = chars / 4 — word counts under-count dense markdown) for the body — the body enters context whole on trigger and stays there, so every line is a recurring token cost. A body inside the line target only because its lines run hundreds of characters has gamed the budget: flag it with the token figure as evidence and propose what moves to a reference file. Mark size findings harness_claim: true.\n` +
    `7. Compaction-prefix placement — auto-compaction re-attaches only the first ~5,000 tokens of an invoked skill, so a load-bearing rule in the back half of a long body vanishes mid-session; flag any rule whose loss would corrupt the run sitting past the early body (harness_claim: true).\n` +
    `8. Standing instructions — the body is read once and never re-read; guidance meant to hold for the whole task but phrased as a one-time step is a finding.\n` +
    `9. Rule salience — a constraint whose violation breaks the run, appearing once mid-paragraph, fused into a long sentence with other imperatives, or far from the step it governs, is a rule the executing agent will skip; propose moving it onto its own line at the point of use with its reason stated. The inverse fails too: walls of all-caps MUST/NEVER and over-rigid structure are a documented yellow flag — placement and a stated why beat volume.\n` +
    `10. Progressive disclosure — the SKILL.md is an overview pointing to detail. Body content not needed on every run (long worked examples, big tables, per-domain detail) belongs in a reference file: propose the split and name what moves. Every reference link states what the file contains and when to read it; a reference the body orders read up front "just in case" defeats the split. References stay one hop from SKILL.md — a reference linking onward to another reference gets partially read in practice, so flag the nesting. A reference file over ~100 lines opens with a table of contents. A skill serving several domains or variants splits reference material per domain so a run loads only the slice it needs — one fat reference mixing variants is a finding. Bundled file names say what they hold (form_validation_rules.md, not doc2.md); paths use forward slashes only.\n` +
    `11. Consistent terminology — one term per concept; a body mixing names for the same thing (extract / pull / get) is a finding.\n` +
    `12. Time-sensitive content — version-conditional branches ("before <date> use the old API"), dates that rot, claims that drift with product releases.\n` +
    `13. Degrees of freedom — prescription tightness matches fragility: a fragile or destructive sequence needs exact commands or a script (low freedom); an open judgment task needs direction, not lockstep (high freedom). Flag over- and under-constraint both.\n` +
    `14. Token justification — assume a capable, knowledgeable reader: a paragraph explaining what the model already knows fails the "does this paragraph justify its token cost" test.\n` +
    `15. Cold-read patterns — anti-self-assertions, dated phrasing, first-person plural, defensive hedging, moralizing imperatives, voodoo constants, unrun commands, AI-tic vocabulary (canonical, comprehensive, seamless, robust, leverage, intuitive, elegant, battle-tested, worth noting, under the hood, empowers, magic, powerful, and kin).\n` +
    `16. Stance — written to a capable practitioner: no apologetic scope notes, no narration of self-evident actions, no over-cautious checkpointing.\n` +
    `17. Output template — a skill that emits a structured artifact (report, commit message, generated page) carries a template or one worked input/output example, strictness matched to need; absence is a finding when output quality depends on format.\n\n` +
    `For every finding: evidence = file:line + a short verbatim quote; why = how a cold execution goes wrong; proposed_fix = exact replacement text, or empty when only the author can draft it. A pattern that appears once and may be load-bearing is AMBIGUOUS, not MINOR. Default to flagging: a false flag costs one confirmation round; a missed one ships unexecutable.`,
    { label: 'lens:cold-walk', schema: COLD_OUT }),

  () => agent(
    `${FENCE}\n\nAudit the craft of ${skill} — how it collaborates with the user and whether its procedure reaches for the right tools.` +
    (scripts.length ? ` Also read the bundled scripts it ships: ${scripts.join(', ')}.` : '') + `\n\n` +
    `Work through every numbered check below in order; skip none.\n` +
    `1. Every user-input fork uses AskUserQuestion, with multiSelect where the user picks M of K, and previews where alternatives need visual comparison.\n` +
    `2. THE QUESTION RULE — any step that asks the user to decide places the finding's evidence, consequence, and exact proposed change in front of them in the same message; a question answerable only by trusting the asker is IMPORTANT (cryptic chip-label approval prompts are the recognizer).\n` +
    `3. Defaults carry escape hatches; silent picks where the user might override are IMPORTANT. The inverse fails too: a body enumerating three or more co-equal approaches with no default is the documented too-many-options failure.\n` +
    `4. Scope — the skill delivers to its stated goal; playing small and goal-drifting expansion are both findings.\n` +
    `5. Mashed phases that lose fresh-eyes value when one context drafts AND self-reviews.\n` +
    `6. Repeated mechanical work that should be a bundled script — a step describing multi-line mechanical work in prose that every run would reproduce identically; a pre-made script beats regenerated code for any deterministic operation.\n` +
    `7. Every bundled-script mention states its intent — execute it ("run analyze.py to extract fields") or read it as reference ("see analyze.py for the algorithm"); a script referenced without that intent leaves the executor guessing.\n` +
    `8. Scripts solve, don't punt — a bundled script that defers its error cases to the model, or a validator that fails without naming what failed and what was available, is a finding.\n` +
    `9. Dependencies declared — a step saying "use the X library" without an install line or availability check, or required packages unlisted, is a finding.\n` +
    `10. Bundled scripts run non-interactively (a TTY prompt hangs an agent shell), pin their runners' versions (uvx / npx / pipx run with explicit pins), and bound their output; a body path to a bundled script uses \${CLAUDE_SKILL_DIR} so it resolves at any install level (harness_claim: true on the path rule).\n` +
    `11. MCP tools named fully qualified (ServerName:tool_name) — a bare tool name fails with tool-not-found (harness_claim: true).\n` +
    `12. Fragile-sequence protection — a fragile non-scriptable sequence carries a copyable checklist; a quality-critical step carries a validate-fix-repeat loop; a batch or destructive operation produces a machine-checkable plan validated before execution.\n` +
    `13. Weak directives ("handle appropriately", "as needed") that gesture instead of instruct.\n` +
    `14. Harness-affordance fit — flag a step doing the weak-tool version of work the harness does better: a long-running command foregrounded instead of a background Bash task; a running task watched through repeated manual polls or sleeps instead of the Monitor tool or the harness's completion notification; a long-running step that stays silent until it finishes — printing no progress markers mid-run for a Monitor check to surface as a status report — when its work has reportable stages; a report the user must act on printed only to scrollback instead of written to a file and opened; a rich pick (many options, side-by-side candidates, free-form per-item input) crammed into AskUserQuestion's 4-option cap instead of a generated HTML page the skill writes, opens, and collects a submission from; a time-sensitive or product-behavior fact asserted from memory instead of verified (web search for the live web, the claude-code-guide agent for Claude Code behavior); file content written via shell heredocs instead of Write/Edit; a multi-item user pick forced through repeated single questions instead of one multiSelect; independent sub-agent work dispatched one message at a time. Mark findings resting on documented tool behavior harness_claim: true.\n` +
    `This lane flags only affordances a step plainly needs; affordances that would merely upgrade the skill belong to the ideas lens, not yours.\n\n` +
    `For every finding: evidence = file:line + quote (name which file); why = what the user experiences when it fires; proposed_fix = exact text or concrete change.`,
    { label: 'lens:craft', schema: FINDINGS }),

  () => agent(
    `${FENCE}\n\nAudit the orchestration of ${skill}` +
    (personas.length ? ` and the persona files it dispatches: ${personas.join(', ')}` : ' (it dispatches no custom persona files)') + `.\n\n` +
    `Work through every numbered check below in order; skip none. These are local orchestration conventions — judge against them, but never cite Anthropic documentation for them.\n` +
    `1. Multi-agent work is batched — parallel Agent calls in one message, or a Workflow script — never sequential dispatches that serialize.\n` +
    `2. Judgment passes the author is biased about go to blind readers, with a director-bias rule stating reader findings outrank director observations.\n` +
    `3. Each dispatched lens names exactly what it may read (blindness by named inputs), and lanes are disjoint — two readers judging the same surface from the same angle is a finding; a defect-lens and an upgrade-lens sharing a surface is acceptable only when the boundary is stated.\n` +
    `4. When persona files exist: required frontmatter (name, description), tools limited to the lens's need, body matches what the skill says the persona judges — drift between the skill's lens table and the persona body is IMPORTANT.\n` +
    `5. A single source of truth for each rule set — two files both claiming authority over the same rules is a finding.\n` +
    `6. Hook-vs-skill routing — a procedure that fires on a tool event belongs in hooks, not a skill; the documented recognizer is a rule the model keeps ignoring, which escalates to deterministic hook enforcement rather than louder prose.\n` +
    `7. Model selection stated or correctly inherited for judgment work.\n\n` +
    `For every finding: evidence = file:line + quote (name which file); why = the orchestration failure a real run hits; proposed_fix = exact change.`,
    { label: 'lens:orchestration', schema: FINDINGS }),

  () => agent(
    `${FENCE}\n\nYou are the surprise lens on ${skill}` +
    (refs.length || scripts.length ? `, plus the files it ships: ${[...refs, ...scripts].join(', ')}` : '') +
    `. Judge whether anything the skill does would surprise a user who read only its description.\n\n` +
    `Work through every numbered check below in order; skip none.\n` +
    `1. Undisclosed behavior — anything the body or a bundled script does that the description does not admit: writes outside the skill's own work area, network calls, data leaving the machine, state changes beyond the stated job.\n` +
    `2. External fetches — a script or step pulling content from an external URL is the documented high-risk case; flag each with what it fetches and where the result lands.\n` +
    `3. Destructive operations — deletes, overwrites, force flags, resets — without an explicit user confirm in the procedure.\n` +
    `4. Credentials — tokens, passwords, or key material read, echoed, or written anywhere a transcript or commit could capture them.\n` +
    `5. Dynamic-context triggers — a literal bang-backtick command pattern in any shipped file fires the loader's preprocessor the moment the skill loads; flag any occurrence the skill does not clearly intend as injection (harness_claim: true).\n\n` +
    `For every finding: evidence = file:line + quote (name which file); why = what the user did not sign up for; proposed_fix = exact change. An empty findings list is a valid result.`,
    { label: 'lens:surprise', schema: FINDINGS }),

  () => agent(
    `${FENCE}\n\nRead ${skill}` +
    (personas.length ? ` and the persona files it dispatches (${personas.join(', ')})` : '') +
    ` and propose up to 5 improvements the author probably did not consider — a curated menu, not a findings list.\n\n` +
    `Kinds: alternative framings, adjacent problems worth folding in, harness tools the skill could use but doesn't, scope adjustments, lifecycle gaps, output-shape rethinks, persona-lens reframings, cross-cutting refactors. Shared assets you may propose without reading them: the voice registry at .github/skills/_shared/voices/ (registered prose voices with writing samples — a fit when the skill emits substantial prose whose register matters); the probe runner at .github/skills/_shared/run_trigger_evals.py (a fit when the skill's routing matters but no trigger-evals.json exists); the decision-page picker at .github/skills/_shared/picker/ (render_picker.py + serve_picker.py: cards with per-item options and notes, submit loops back to the session — a fit whenever a user decision carries per-item evidence or notes, not only past AskUserQuestion's 4-option cap). Ground every idea in something the files actually say (anchor = file:line or section). At most ONE idea may be wild (loosened plausibility — mark it). For each, set recommended_action: apply-inline for a narrow single-file edit; apply-with-edits when wording needs the author; discuss-first for wild ideas and anything touching goal-bearing prose (description, opening paragraph, Done-when, a blindness contract).\n\n` +
    `Stay out of the checklist lanes: propose a tool or behavior only when its ABSENCE is not a defect a checklist would flag — an upgrade beyond the bar, not a missing requirement. Fewer, better ideas beat a padded menu; an empty menu is a valid result.`,
    { label: 'lens:ideas', schema: IDEAS_OUT }),

  () => agent(
    `You are the outward research lens on ${skill}. Read that file` +
    (refs.length ? ` and its reference files (${refs.join(', ')})` : '') +
    `, and no other skill or persona in the repository — your value is bringing in what those files cannot contain.\n\n` +
    `Work three lanes:\n` +
    `1. PRIOR ART — web-search for tools, workflows, and published practice that do the job this skill's goal names. Anthropic's public skills repo (https://github.com/anthropics/skills) carries officially-maintained skills worth diffing against when one does a comparable job. What does the prior art do that this skill doesn't? Source = the URL you actually read.\n` +
    `2. VISION — before comparing anything, sketch what the ideal tool with this goal would do end to end. Diff the sketch against the actual file; a capability in the sketch but absent from the skill is an idea. Source = the word "vision" plus a one-clause rationale.\n` +
    `3. TOOLSET — check the live Claude Code docs (start at https://code.claude.com/docs) and Anthropic's public GitHub (the claude-code repo's changelog and the claude-cookbooks patterns) for harness capabilities the skill could exploit but doesn't: tools, frontmatter fields, hooks, subagent and workflow affordances. Source = the doc or repo URL. Upgrades beyond the current bar only — a step doing manually what a tool plainly does better is a defect another lens already flags.\n\n` +
    `Up to 5 ideas total across the lanes, best first, each naming what changes if it lands. Skip anything derivable from the skill files alone — that is the inward ideas lens's lane. An empty menu is a valid result when the search and the sketch surface nothing the skill misses.`,
    { label: 'lens:research', agentType: 'general-purpose', schema: RESEARCH_OUT }),
])

const lenses = { loader, cold, craft, orchestration, surprise, ideas, research }
const missing = Object.entries(lenses).filter(([, value]) => !value).map(([name]) => name)
if (missing.length) log(`lens(es) returned nothing after retries: ${missing.join(', ')} — director must note the missing lens in the report`)
return lenses
