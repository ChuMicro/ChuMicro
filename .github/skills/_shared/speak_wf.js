export const meta = {
  name: 'speak-ledger',
  description: 'Rewrite a merged audit ledger into cold-reader prose, voiceless or in a registry voice',
  phases: [{ title: 'Speak' }],
}

// args: { ledgerPath, ids: [], voice, persona, sample }
// The ledger is a picker-spec-shaped JSON file whose item wording is raw lens
// shorthand. Agents read it from disk; the id list and the voice-sample excerpt
// ride in args (`sample` is the prose voice_sample.py prints — excerpt only,
// never attribution — injected inline because the proven writer prompts
// substitute the sample text, never a path to go read). Accept both an object
// and a JSON-encoded string — stringified args reach the script as one string,
// and reading .ledgerPath off a string silently yields undefined.
const input = typeof args === 'string' ? JSON.parse(args) : (args || {})
const ledgerPath = input.ledgerPath
const ids = (input.ids || []).map(String)
const voice = input.voice || 'plain'
const persona = (input.persona || '').trim()
const sample = (input.sample || '').trim()
if (!ledgerPath || typeof ledgerPath !== 'string' || ledgerPath === 'undefined') {
  throw new Error(`ledger unresolved: ledgerPath=${JSON.stringify(ledgerPath)} — pass args {ledgerPath, ids, voice, persona, sample}`)
}
if (!ids.length) throw new Error('ids is empty — pass every item id the speaker must render')

// The voiced prompt mirrors the converged regen-comments voiced writer: persona
// sentence leads and the voice is total, the real-prose sample is absorbed in
// own-words framing, the rules stay few and structural, and the discipline layer
// is the mechanical ban line at the end. Adapted to this genre (audit findings
// instead of code comments); do not re-derive the wording — it was benched there.
const sampleBlock = (persona && sample)
  ? 'A sample of that voice, in its own genre rather than audit findings. Absorb the rhythm, attitude, '
    + 'and word choice from it, then write in your own words about these findings -- never reuse its '
    + 'phrases or subject matter, and never its paragraph length or format. Every rule below still '
    + 'applies as written:\n\n' + sample + '\n\n'
  : ''
const REGISTER = persona
  ? persona + ' Every line you return is fully in that voice.\n\n' + sampleBlock
  : 'Write plain, neutral English.\n\n'

const CHARTER =
  `Read ${ledgerPath}, a JSON ledger of audit findings written in the auditing lens's shorthand. ` +
  `You speak the entries; you do not judge them.\n\n` +
  `Rewrite each entry named below for the person deciding what to do about it -- they have not opened ` +
  `the audited files, and they read each card alone. Every fact comes from the entry itself; add ` +
  `nothing, soften nothing. Each fact lands once across the card: the entry's where, evidence, and ` +
  `diff fields render on the card verbatim, so your prose never re-lists what they already show; a ` +
  `location or number stated only in the entry's own prose stays. Introduce a thing the first ` +
  `time you name it, never as already-known. Weave a warning into the sentence that states it, never ` +
  `behind scaffolding like "one thing to know" or "worth noting". Text meant to be applied -- ` +
  `replacement wording, commands, quoted lines -- passes through character-for-character. A short ` +
  `entry stays short${sample ? ', and the sample never adds length' : ''}.\n\n` +
  `Per entry return: title -- one line naming the defect; summary -- what is wrong and what it breaks; ` +
  `why -- the consequence, or "" when the entry states none; fix -- what to change, or "" when the ` +
  `change lives in the entry's diff field.\n\n` +
  'No em-dashes, no " -- ", no semicolons, no `canonical` or `shape`.\n'

const ITEMS_OUT = {
  type: 'object', required: ['items'],
  properties: {
    items: {
      type: 'array',
      items: {
        type: 'object', required: ['id', 'title', 'summary', 'why', 'fix'],
        properties: {
          id: { type: 'string' },
          title: { type: 'string' },
          summary: { type: 'string' },
          why: { type: 'string' },
          fix: { type: 'string' },
        },
      },
    },
  },
}
const PAGE_OUT = {
  type: 'object', required: ['intro_html', 'option_help', 'gate'],
  properties: {
    intro_html: { type: 'string', description: 'one or two short <p> blocks orienting a cold reader: what was audited, what this page is, how to act on it' },
    option_help: {
      type: 'object', required: ['apply', 'discuss', 'skip'],
      properties: { apply: { type: 'string' }, discuss: { type: 'string' }, skip: { type: 'string' } },
    },
    gate: {
      type: 'object', required: ['question', 'apply', 'reauthor', 'report_only'],
      properties: {
        question: { type: 'string', description: 'the mode question asked after the report opens' },
        apply: { type: 'string', description: 'option description: apply findings by number' },
        reauthor: { type: 'string', description: 'option description: hand the skill to a from-scratch re-author' },
        report_only: { type: 'string', description: 'option description: stop at the report' },
      },
    },
  },
}

const PICK_OUT = {
  type: 'object', required: ['pick', 'reason'],
  properties: {
    pick: { type: 'integer', minimum: 1, maximum: 2 },
    reason: { type: 'string', description: 'one sentence on why this pass won' },
  },
}

phase('Speak')

const CHUNK = 12
// 2 passes, not regen-comments' 4: a report is 5-6 chunks where regen writes one
// file, so 4 passes per chunk made a big matrix. Best-of-2 keeps the selector's
// escape from a tic-heavy roll at half the cost.
const PASSES = 2
const chunks = []
for (let i = 0; i < ids.length; i += CHUNK) chunks.push(ids.slice(i, i + CHUNK))

// opus on every speaking agent: the voice work this prompt descends from was
// converged on opus end to end, and register fidelity is the whole job here.
const renderChunk = (chunkIds, tag) => agent(
  REGISTER + CHARTER + `\nEntries to render, by id: ${chunkIds.join(', ')}. Return one items[] element per id, ids as strings.`,
  { label: `speak:${chunkIds[0]}-${chunkIds[chunkIds.length - 1]}:${tag}`, phase: 'Speak', schema: ITEMS_OUT, model: 'opus' })

// Best-of-N per chunk, the converged answer to grounding-induced tics: dense facts
// summon the load-bearing/antithesis register in any single pass, and no prompt rule
// selects it out. The selector picks one whole pass by number and never rewrites or
// merges across passes (a rewrite is unvalidated new text).
const speakChunk = async (chunkIds) => {
  const passLabels = Array.from({ length: PASSES }, (unused, index) => index + 1)
  const passes = (await parallel(passLabels.map(n => () => renderChunk(chunkIds, `p${n}`)))).filter(Boolean)
  if (!passes.length) return null
  if (passes.length === 1) return passes[0]
  const candidates = passes.map((pass, index) => `PASS ${index + 1}:\n${JSON.stringify(pass.items, null, 1)}`).join('\n\n')
  const verdict = await agent(
    `${passes.length} renderings of the same audit-report cards follow. The ledger they were rendered from is at ${ledgerPath}` +
    (persona ? `, and the target voice is: "${persona}"` : '') + `.\n\n` +
    `Pick the one whole pass whose cards read the richest and best-worded${persona ? ', most alive in that voice' : ''}, never the flattest (flat is wrong). Legibility is the only floor and correctness the second: a garbled sentence or a fact the ledger contradicts loses the pass outright. Pick by number; never merge or reword.\n\n` +
    candidates,
    { label: `select:${chunkIds[0]}-${chunkIds[chunkIds.length - 1]}`, phase: 'Speak', schema: PICK_OUT, model: 'opus' })
  const picked = verdict && passes[verdict.pick - 1] ? passes[verdict.pick - 1] : passes[0]
  if (verdict) log(`cards ${chunkIds[0]}-${chunkIds[chunkIds.length - 1]}: pass ${verdict.pick} — ${verdict.reason}`)
  return picked
}

// Barrier on purpose: coverage of every id is checked across ALL chunk results
// before the retry round, and the page prose is part of the same return value.
// The page runs a single pass: its intro and gate text carry few ledger facts,
// which is exactly the regime where one pass already lands the register.
const [page, ...chunkResults] = await parallel([
  () => agent(
    REGISTER + CHARTER +
    `\nDo not render entries. Return the page-level prose instead: intro_html for the decision page; option_help one-liners for apply / discuss / skip (apply = make the proposed change, a note adjusts its wording; discuss = no change yet, talk it through in chat first; skip = leave as is -- keep those meanings, in your words); and the gate wording for the mode question fired after the report opens (three fixed choices: apply findings by number, hand the skill to a from-scratch re-author, stop at the report).`,
    { label: 'speak:page', phase: 'Speak', schema: PAGE_OUT, model: 'opus' }),
  ...chunks.map(chunkIds => () => speakChunk(chunkIds)),
])

const rendered = {}
for (const result of chunkResults.filter(Boolean)) {
  for (const item of result.items || []) rendered[String(item.id)] = item
}
let missing = ids.filter(id => !rendered[id])
if (missing.length) {
  log(`retrying ${missing.length} unrendered id(s): ${missing.join(', ')}`)
  const retried = await renderChunk(missing, 'retry')
  for (const item of (retried && retried.items) || []) rendered[String(item.id)] = item
  missing = ids.filter(id => !rendered[id])
}
if (missing.length) log(`unrendered after retry — these ship in ledger wording with a warning: ${missing.join(', ')}`)
if (!page) log('page prose returned nothing — director falls back to mechanical intro and gate wording')

return { voice, page, items: rendered, unrendered: missing }
