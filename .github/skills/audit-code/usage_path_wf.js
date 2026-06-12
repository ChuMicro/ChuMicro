// audit skills — the USAGE-PATH lens. Runs IN-SESSION via the Workflow tool, on purpose: no clean
// room, no stripping. The clean-room lenses are the unbiased base; this lens trades blindness for
// reach — it follows the audited symbols' real call chains outward (callers of callers, optionally
// into consumer repos) on full commented code with project context, and judges what only the
// transitive path shows. A feature-mapper runs first so every finding lands in feature terms: not
// just "X breaks at hop 3" but "X breaks the reconnect feature via this chain".
//
// args: {
//   pathsFile:  absolute path to usage_trace.py's output (edges / files / stops / seeds / roots)
//   roomDir:    the run room — agents read eval.json there to avoid re-filing ledger findings,
//               and voice_persona.txt for the compose register
//   seeds:      the seed symbol names to fan out over (one judge agent per seed)
// }
// Returns { features, findings } — the orchestrator Writes it to a file and runs
// `usage_trace.py merge <roomDir> <file>`, then re-renders the page.

export const meta = {
  name: 'usage-path-lens',
  description: 'Judge the audited symbols\' transitive usage paths on full commented code (in-session, no clean room), in feature terms.',
  phases: [
    { title: 'Map', detail: 'feature mapper — what the traced code serves, per repo' },
    { title: 'Judge', detail: 'one agent per seed walks its chains for behavior-affecting issues' },
    { title: 'Compose', detail: 'writer composes the prose in the room voice' },
  ],
}

const input = typeof args === 'string' ? JSON.parse(args) : (args || {})
const PATHS = input.pathsFile
const ROOM = input.roomDir
const SEEDS = input.seeds || []
if (!PATHS || !ROOM || !SEEDS.length) {
  throw new Error('usage-path lens needs args {pathsFile, roomDir, seeds[]} — got ' + JSON.stringify(input))
}

const FRAGMENT_RULES =
  'Record THREE telegraphic FACT FRAGMENTS per finding -- never finished sentences (a later writer '
  + 'composes the prose; fluent input gets pasted and goes flat). Use arrows (->), colons, shorthand:\n'
  + '- defect: WHAT is wrong along the path.\n'
  + '- bite: the CONSEQUENCE -- who/what is hurt, WHEN, how bad, named at the level where it surfaces.\n'
  + '- fix: the change.\n'
  + 'Score severity (high / med / low), effort (small / medium / large), confidence (high / med / '
  + 'low). LOCATING: `file` = the repo-relative path the fix would edit, `symbol` = the enclosing '
  + 'qualname, `site` = a SHORT QUOTE of the exact line(s). `feature` = the feature from the map '
  + 'this finding affects ("" when none). '

const FINDING = {
  type: 'object', additionalProperties: false,
  properties: {
    file: { type: 'string' }, symbol: { type: 'string' }, site: { type: 'string' },
    feature: { type: 'string' },
    severity: { type: 'string', enum: ['high', 'med', 'low'] },
    effort: { type: 'string', enum: ['small', 'medium', 'large'] },
    confidence: { type: 'string', enum: ['high', 'med', 'low'] },
    defect: { type: 'string' }, bite: { type: 'string' }, fix: { type: 'string' },
  },
  required: ['file', 'symbol', 'site', 'feature', 'severity', 'effort', 'confidence', 'defect', 'bite', 'fix'],
}
const JUDGE_OUT = {
  type: 'object', additionalProperties: false,
  properties: { seed: { type: 'string' }, findings: { type: 'array', items: FINDING } },
  required: ['seed', 'findings'],
}
const MAP_OUT = {
  type: 'object', additionalProperties: false,
  properties: { features: { type: 'array', items: { type: 'object', additionalProperties: false,
    properties: {
      name: { type: 'string' },
      summary: { type: 'string' },
      entry_points: { type: 'array', items: { type: 'string' } },
      touched_by: { type: 'array', items: { type: 'string' } },
    },
    required: ['name', 'summary', 'entry_points', 'touched_by'] } } },
  required: ['features'],
}
const PROSE_OUT = {
  type: 'object', additionalProperties: false,
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false,
    properties: { index: { type: 'integer' }, title: { type: 'string' }, consequence: { type: 'string' }, problem: { type: 'string' }, suggested_fix: { type: 'string' } },
    required: ['index', 'title', 'consequence', 'problem', 'suggested_fix'] } } },
  required: ['findings'],
}

phase('Map')
const featureMap = await agent(
  'You are the FEATURE MAPPER for a usage-path audit. Read the trace at ' + PATHS + ' (its `files` '
  + 'list names every traced file as root:relpath; `seeds` are the audited symbols; `edges` are the '
  + 'call-graph hops). Read the traced files and each root\'s natural entry docs (a README, a docs/ '
  + 'guide, package __init__ docstrings) and produce the FEATURE MAP: the user-facing feature sets '
  + 'this code serves. For each feature: name (short, domain terms), summary (what a user gets from '
  + 'it, 1-2 sentences), entry_points (the files/symbols where the feature lives), touched_by (which '
  + 'of the seeds\' chains reach it -- seed names from the trace). Only features the TRACED code '
  + 'actually serves; an empty list is valid for pure plumbing. Return {features}.',
  { label: 'feature-map', model: 'opus', agentType: 'general-purpose', schema: MAP_OUT },
) || { features: [] }
log('feature map: ' + featureMap.features.length + ' feature(s): ' + featureMap.features.map((f) => f.name).join(', '))

phase('Judge')
const judgePrompt = (seed) =>
  'You are the USAGE-PATH lens, judging seed symbol `' + seed + '`. The traced call graph is at '
  + PATHS + ' (edges: {callee, caller_qual, caller_file, root, depth}; `stops` names where the '
  + 'walk hit its caps -- judge only what was traced, never guess past a stop). Reconstruct this '
  + 'seed\'s chains outward -- direct callers, then theirs -- and READ THE REAL FILES along them, '
  + 'comments included; you may read any traced file in any listed root.\n\n'
  + 'Hunt what only the TRANSITIVE path shows:\n'
  + '- an assumption a caller two or more hops out makes that the seed\'s behavior breaks -- name '
  + 'the level where it surfaces, not just where it starts\n'
  + '- an error raised at the seed that a mid-chain caller swallows, so the top of the chain '
  + 'proceeds on garbage\n'
  + '- lifecycle and state misuse across hops (a handle closed at one level and reused above it; '
  + 'ordering one caller establishes and a sibling path violates)\n'
  + '- a unit, default, or sentinel mismatch that compounds as it propagates\n'
  + '- KNOWN-FEATURE IMPACT -- the highest-value find of this lens: where the seed\'s behavior '
  + 'changes what a mapped feature visibly does for its user. The feature map:\n'
  + JSON.stringify(featureMap.features) + '\n\n'
  + 'The clean-room ledger at ' + ROOM + '/eval.json already covers the seed itself and its DIRECT '
  + 'callers -- do not re-file what it carries; your lane is beyond the first hop.\n\n'
  + FRAGMENT_RULES + 'Return {seed, findings} -- an empty findings list is a valid clean read.'

const judged = (await parallel(SEEDS.map((seed) => () =>
  agent(judgePrompt(seed), { label: 'path:' + seed, phase: 'Judge', model: 'opus', agentType: 'general-purpose', schema: JUDGE_OUT })
))).filter(Boolean)
const fragments = judged.flatMap((j) => j.findings || [])
log('judged ' + judged.length + '/' + SEEDS.length + ' seeds: ' + fragments.length + ' path finding(s)')

if (!fragments.length) return { features: featureMap.features, findings: [] }

phase('Compose')
const dump = fragments.map((f, i) =>
  '#' + i + ' [' + f.severity + '/' + f.effort + '/conf:' + f.confidence + '] (' + f.file + ' :: ' + f.symbol + ' @ ' + f.site + ')'
  + (f.feature ? ' feature:' + f.feature : '')
  + '\n  defect: ' + f.defect + '\n  bite: ' + f.bite + '\n  fix: ' + f.fix
).join('\n')
const prose = await agent(
  'You are the WRITER. Compose reader-facing prose for each numbered finding FRESH from its '
  + 'fragments -- do not paste them. REGISTER: read ' + ROOM + '/voice_persona.txt; empty means a '
  + 'clear plain register, otherwise write FULLY in that voice (the one floor: the consequence '
  + 'stays understandable in a single read). Per finding: title (under ~12 words), consequence '
  + '(stakes first; name the affected feature when the fragment carries one), problem (the '
  + 'mechanism along the call path, 1-3 tight sentences), suggested_fix (1-2 sentences). No '
  + 'em-dashes, no semicolons. Return {findings:[{index, title, consequence, problem, '
  + 'suggested_fix}]} covering EVERY index.\n\nFRAGMENTS:\n' + dump,
  { label: 'path-writer', model: 'opus', agentType: 'general-purpose', schema: PROSE_OUT },
) || { findings: [] }
const proseByIndex = {}
for (const p of (prose.findings || [])) proseByIndex[p.index] = p

const findings = fragments.map((f, i) => ({ ...f, ...(proseByIndex[i] || {}) }))
log('composed prose for ' + (prose.findings || []).length + '/' + fragments.length + ' findings')
return { features: featureMap.features, findings }
