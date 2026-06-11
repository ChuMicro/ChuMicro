export const meta = {
  name: 'audit-skill-lenses',
  description: 'Five blind audit lenses over one SKILL.md, schema-validated findings',
  phases: [{ title: 'Audit' }],
}

// args: { skillPath, referenceFiles: [], personaFiles: [], triggerMessages: [] }
const skill = args.skillPath
const refs = args.referenceFiles || []
const personas = args.personaFiles || []
const triggers = args.triggerMessages || []

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

const [loader, cold, craft, orchestration, ideas] = await parallel([
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
    `Judge: (1) every user-input fork uses AskUserQuestion with multiSelect where the user picks M of K, and previews where alternatives need visual comparison; (2) THE QUESTION RULE — any step that asks the user to decide must place the finding's evidence, consequence, and exact proposed change in front of them in the same message; a question answerable only by trusting the asker is IMPORTANT (cryptic chip-label approval prompts are the recognizer); (3) defaults carry escape hatches, silent picks where the user might override are IMPORTANT; (4) scope: does the skill deliver to its stated goal or stop at the minimum (playing small and goal-drifting expansion are both findings); (5) mashed phases that lose fresh-eyes value when one context drafts AND self-reviews; (6) repeated work that should be a bundled script — a step describing multi-line mechanical work in prose that every run would reproduce identically; (7) weak directives ("handle appropriately", "as needed") that gesture instead of instruct.\n\n` +
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
    `Kinds: alternative framings, adjacent problems worth folding in, harness tools the skill could use but doesn't, scope adjustments, lifecycle gaps, output-shape rethinks, persona-lens reframings, cross-cutting refactors. Ground every idea in something the files actually say (anchor = file:line or section). At most ONE idea may be wild (loosened plausibility — mark it). For each, set recommended_action: apply-inline for a narrow single-file edit; apply-with-edits when wording needs the author; discuss-first for wild ideas and anything touching goal-bearing prose (description, opening paragraph, Done-when, a blindness contract).\n\n` +
    `Stay out of the checklist lanes: propose a tool or behavior only when its ABSENCE is not a defect a checklist would flag — an upgrade beyond the bar, not a missing requirement. Fewer, better ideas beat a padded menu; an empty menu is a valid result.`,
    { label: 'lens:ideas', schema: IDEAS_OUT }),
])

const lenses = { loader, cold, craft, orchestration, ideas }
const missing = Object.entries(lenses).filter(([, value]) => !value).map(([name]) => name)
if (missing.length) log(`lens(es) returned nothing after retries: ${missing.join(', ')} — director must note the missing lens in the report`)
return lenses
