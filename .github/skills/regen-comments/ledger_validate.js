// regen-comments LEDGER VALIDATOR (production, fixture-agnostic). One `claude -p` agent reads the stripped
// code + the provisional ledger and checks: (1) is each ledger fact TRUE against the code; (2) is every
// fact in a correctness-critical CLASS (a returned flag/field's referent, an inversion, a dual-role value,
// a boundary condition) stated UNAMBIGUOUSLY. No trap list, no file-specific knowledge. Orchestrator
// substitutes __RUNDIR__. Reads __RUNDIR__/{stripped.py, ledger_provisional.md}; writes __RUNDIR__/validation.json.

export const meta = {
  name: 'regen-validate',
  description: 'Fixture-agnostic ledger gate: per-fact correctness + explicitness of correctness-critical fact classes.',
  phases: [{ title: 'Validate' }],
}

const RUNDIR = '__RUNDIR__'
const FILE = RUNDIR + '/stripped.py'
const LEDGER = RUNDIR + '/ledger_provisional.md'

const SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    facts: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { fact: { type: 'string' }, correct: { type: 'boolean' }, note: { type: 'string' } }, required: ['fact', 'correct', 'note'] } },
    underspecified: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { fact: { type: 'string' }, why: { type: 'string' } }, required: ['fact', 'why'] } },
    any_wrong: { type: 'boolean' }, any_underspecified: { type: 'boolean' }, verdict: { type: 'string' },
  },
  required: ['facts', 'underspecified', 'any_wrong', 'any_underspecified', 'verdict'],
}

const prompt =
  'You validate a nuance LEDGER against the CODE. You have NO trap list and NO prior knowledge of this '
  + 'file — reason only from the code.\n\nCODE: ' + FILE + '\nLEDGER: ' + LEDGER + '\n\n'
  + '(1) For EACH ledger fact, verify it is TRUE against the code (record correct + a short note; quote the '
  + 'code site when wrong).\n'
  + '(2) Flag any fact in a CORRECTNESS-CRITICAL CLASS that is stated AMBIGUOUSLY (a reader could invert or '
  + 'misread it): a returned flag or field\'s referent (WHICH entity it acts on), an inversion (a value that '
  + 'means the opposite of the naive reading), a dual-role value (one name, two jobs), or a boundary / '
  + 'inclusive-vs-exclusive condition. Under-specified = states only half the fact or leaves the critical '
  + 'half to be inferred.\n\n'
  + 'Write JSON to ' + RUNDIR + '/validation.json with keys facts, underspecified, any_wrong, '
  + 'any_underspecified, verdict. After writing, reply DONE.'

phase('Validate')
const res = await agent(prompt, { label: 'validate', phase: 'Validate', model: 'opus', agentType: 'general-purpose', schema: SCHEMA })
return res
