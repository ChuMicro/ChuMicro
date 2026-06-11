export const meta = {
  name: 'audit-skill-lenses',
  description: 'Five blind audit lenses plus an outward research lens over one SKILL.md, schema-validated output',
  phases: [{ title: 'Audit' }],
}

// args: { skillPath, referenceFiles: [], personaFiles: [], triggerMessages: [] }
// Accept both an object and a JSON-encoded string — stringified args reach the script
// as one string, and reading .skillPath off a string silently yields undefined, which
// would dispatch every lens against the literal path "undefined". The guard below
// makes that failure loud and immediate instead.
const input = typeof args === 'string' ? JSON.parse(args) : (args || {})
const skill = input.skillPath
const refs = input.referenceFiles || []
const personas = input.personaFiles || []
const triggers = input.triggerMessages || []
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

const [loader, cold, craft, orchestration, ideas, research] = await parallel([
  () => agent(
    `${FENCE}\n\nRead ONLY the YAML frontmatter of ${skill} — stop at the closing ---. Do not open the body.\n\n` +
    `Judge whether the skill loader would route each of these user messages to this skill on the description/when_to_use text alone:\n` +
    triggers.map((m, i) => `${i + 1}. "${m}"`).join('\n') +
    `\n\nThen draft one near-miss query — a message sharing this skill's keywords but needing a different tool — and judge whether the description stays silent on it.\n\n` +
    `Frontmatter rules to judge against: description opens third-person with what-it-does, then a "Use when" coda (both halves required); verbs a user would type, not abstract stand-ins (handle, manage); no vague stems ("Tools for…", "Helps with…"); no first or second person; pushy about adjacent phrasings but precise against near-misses; a "Do NOT use" clause when a sibling tool shares the boundary; no implementation leak. Caps: description <= 1024 chars hard, description + when_to_use <= 1536 combined (mark cap findings harness_claim: true — they rest on documented loader behavior). name (or the directory name when name is omitted): <= 64 chars, lowercase/digits/hyphens, not "anthropic" or "claude". allowed-tools should carry prefix-scoped Bash forms, never bare Bash, and include AskUserQuestion when the body asks the user anything.\n\n` +
    `For every finding: evidence = the frontmatter line quoted; why = what misroutes or fails to load in production; proposed_fix = the exact replacement text. Strict marking: a borderline routing call is a miss with the reason stated.`,
    { label: 'lens:loader', schema: LOADER_OUT }),

  () => agent(
    `${FENCE}\n\nCold-walk the body of ${skill} top-to-bottom as a fresh agent about to execute it` +
    (refs.length ? `, plus its reference files (one hop): ${refs.join(', ')}` : ' (the skill directory has no reference files)') + `.\n\n` +
    `Judge: (1) goal-derivability — can you state the skill's goal in one sentence after the read; (2) section ordering — procedure-first, narrative buried; (3) walkability — no step depends on a later step; (4) per-step Success criteria — present on every step past two, observable, and DISCRIMINATING: a clearly-wrong run must fail it ("report generated" passes on an empty report — flag like a missing criterion); (5) a Done-when block distinct from the last step (the last step is what you do; Done-when is what you observe after); (6) every linked reference file exists; (7) body length <= 500 lines target; (8) patterns that fail a cold read: anti-self-assertions, dated phrasing, first-person plural, defensive hedging, moralizing imperatives, voodoo constants, unrun commands, AI-tic vocabulary (canonical, comprehensive, seamless, robust, leverage, intuitive, elegant, battle-tested, worth noting, under the hood, empowers, magic, powerful, and kin); (9) stance — written to a capable practitioner, no apologetic scope notes, no narration of self-evident actions, no over-cautious checkpointing.\n\n` +
    `For every finding: evidence = file:line + a short verbatim quote; why = how a cold execution goes wrong; proposed_fix = exact replacement text, or empty when only the author can draft it. A pattern that appears once and may be load-bearing is AMBIGUOUS, not MINOR. Default to flagging: a false flag costs one confirmation round; a missed one ships unexecutable.`,
    { label: 'lens:cold-walk', schema: COLD_OUT }),

  () => agent(
    `${FENCE}\n\nAudit the craft of ${skill} — how it collaborates with the user and whether its procedure reaches for the right tools.\n\n` +
    `Judge: (1) every user-input fork uses AskUserQuestion with multiSelect where the user picks M of K, and previews where alternatives need visual comparison; (2) THE QUESTION RULE — any step that asks the user to decide must place the finding's evidence, consequence, and exact proposed change in front of them in the same message; a question answerable only by trusting the asker is IMPORTANT (cryptic chip-label approval prompts are the recognizer); (3) defaults carry escape hatches, silent picks where the user might override are IMPORTANT; (4) scope: does the skill deliver to its stated goal or stop at the minimum (playing small and goal-drifting expansion are both findings); (5) mashed phases that lose fresh-eyes value when one context drafts AND self-reviews; (6) repeated work that should be a bundled script — a step describing multi-line mechanical work in prose that every run would reproduce identically; (7) weak directives ("handle appropriately", "as needed") that gesture instead of instruct; (8) harness-affordance fit — flag a step doing the weak-tool version of work the harness does better: a long-running command foregrounded instead of a background Bash task; a running task watched through repeated manual polls or sleeps instead of the Monitor tool or the harness's completion notification; a long-running step that stays silent until it finishes — printing no progress markers mid-run for a Monitor check to surface as a status report — when its work has reportable stages; a report the user must act on printed only to scrollback instead of written to a file and opened; a rich pick — many options, side-by-side candidates, free-form per-item input — crammed into AskUserQuestion's 4-option cap instead of a generated HTML page the skill writes, opens, and collects a submission from; a time-sensitive or product-behavior fact asserted from memory instead of verified (web search for the live web, the claude-code-guide agent for Claude Code behavior); file content written via shell heredocs instead of Write/Edit; a multi-item user pick forced through repeated single questions instead of one multiSelect; independent sub-agent work dispatched one message at a time. Mark findings resting on documented tool behavior harness_claim: true. This lane flags only affordances a step plainly needs; affordances that would merely upgrade the skill belong to an upgrade lens, not yours.\n\n` +
    `For every finding: evidence = file:line + quote; why = what the user experiences when it fires; proposed_fix = exact text or concrete change.`,
    { label: 'lens:craft', schema: FINDINGS }),

  () => agent(
    `${FENCE}\n\nAudit the orchestration of ${skill}` +
    (personas.length ? ` and the persona files it dispatches: ${personas.join(', ')}` : ' (it dispatches no custom persona files)') + `.\n\n` +
    `Judge: (1) multi-agent work is batched — parallel Agent calls in one message, or a Workflow script — never sequential dispatches that serialize; (2) judgment passes the author is biased about go to blind readers, with a director-bias rule stating reader findings outrank director observations; (3) each dispatched lens names exactly what it may read (blindness by named inputs), and lanes are disjoint — two readers judging the same surface from the same angle is a finding, a defect-lens and an upgrade-lens sharing a surface is acceptable only when the boundary is stated; (4) when persona files exist: required frontmatter (name, description), tools limited to the lens's need, body matches what the skill says the persona judges — drift between the skill's lens table and the persona body is IMPORTANT; (5) a single source of truth for each rule set — two files both claiming authority over the same rules is a finding; (6) hook-vs-skill routing — a procedure that fires on a tool event belongs in hooks, not a skill; (7) model selection stated or correctly inherited for judgment work.\n\n` +
    `For every finding: evidence = file:line + quote (name which file); why = the orchestration failure a real run hits; proposed_fix = exact change.`,
    { label: 'lens:orchestration', schema: FINDINGS }),

  () => agent(
    `${FENCE}\n\nRead ${skill}` +
    (personas.length ? ` and the persona files it dispatches (${personas.join(', ')})` : '') +
    ` and propose up to 5 improvements the author probably did not consider — a curated menu, not a findings list.\n\n` +
    `Kinds: alternative framings, adjacent problems worth folding in, harness tools the skill could use but doesn't, scope adjustments, lifecycle gaps, output-shape rethinks, persona-lens reframings, cross-cutting refactors. Shared assets you may propose without reading them: the voice registry at .github/skills/_shared/voices/ (registered prose voices with writing samples — a fit when the skill emits substantial prose whose register matters); the probe runner at .github/skills/_shared/run_trigger_evals.py (a fit when the skill's routing matters but no trigger-evals.json exists); an HTML page the skill writes, opens, and collects a submission from (a fit when a user decision outgrows AskUserQuestion's 4-option cap). Ground every idea in something the files actually say (anchor = file:line or section). At most ONE idea may be wild (loosened plausibility — mark it). For each, set recommended_action: apply-inline for a narrow single-file edit; apply-with-edits when wording needs the author; discuss-first for wild ideas and anything touching goal-bearing prose (description, opening paragraph, Done-when, a blindness contract).\n\n` +
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

const lenses = { loader, cold, craft, orchestration, ideas, research }
const missing = Object.entries(lenses).filter(([, value]) => !value).map(([name]) => name)
if (missing.length) log(`lens(es) returned nothing after retries: ${missing.join(', ')} — director must note the missing lens in the report`)
return lenses
