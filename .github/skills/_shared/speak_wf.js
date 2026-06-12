export const meta = {
  name: 'speak-ledger',
  description: 'Rewrite a merged audit ledger into cold-reader prose, voiceless or in a registry voice',
  phases: [{ title: 'Speak' }],
}

// args: { ledgerPath, ids: [], voice, persona, samplePath }
// The ledger is a picker-spec-shaped JSON file whose item wording is raw lens
// shorthand. Agents read it from disk; only the id list rides in args, so a
// 60-item ledger does not bloat the call. Accept both an object and a
// JSON-encoded string — stringified args reach the script as one string, and
// reading .ledgerPath off a string silently yields undefined.
const input = typeof args === 'string' ? JSON.parse(args) : (args || {})
const ledgerPath = input.ledgerPath
const ids = (input.ids || []).map(String)
const voice = input.voice || 'plain'
const persona = input.persona || ''
const samplePath = input.samplePath || ''
if (!ledgerPath || typeof ledgerPath !== 'string' || ledgerPath === 'undefined') {
  throw new Error(`ledger unresolved: ledgerPath=${JSON.stringify(ledgerPath)} — pass args {ledgerPath, ids, voice, persona, samplePath}`)
}
if (!ids.length) throw new Error('ids is empty — pass every item id the speaker must render')

// The speaker prompt stays lean on purpose: a register line, an optional real-text
// sample, and four rules. Every extra rule measurably degrades the prose. A picked
// voice replaces the plain register outright — no restraint clause layered on top,
// and the rules below are structural floors (facts, ordering, pass-through), never
// style: style instructions would fight the voice.
const REGISTER = persona
  ? `Write in the register of this persona: "${persona}" — the register is fully yours, the facts are the ledger's. It is a way of writing, not content; never quote or mention it.` +
    (samplePath ? ` First read ${samplePath} once as a sample of the register; use only its prose, skip headings and attribution.` : '') + '\n\n'
  : 'Write plain, neutral English.\n\n'

const CHARTER =
  `Read ${ledgerPath}, a JSON ledger of audit findings written in the auditing lens's shorthand. You speak the entries; you do not judge them.\n\n` +
  `Rewrite each entry named below for the person deciding what to do about it — they have not opened the audited files, and they read each card alone. Rules:\n` +
  `- Every fact comes from the entry itself; add nothing, soften nothing.\n` +
  `- Introduce a thing the first time you name it ("invariant 2, the rule naming who reads the commented file") — never as already-known.\n` +
  `- Keep every file:line, number, and name.\n` +
  `- Text meant to be applied — replacement wording, commands, quoted lines — passes through character-for-character.\n\n` +
  `Per entry return: title — one line naming the defect; summary — what is wrong and where; why — the consequence, or "" when the entry states none; fix — what to change, or "" when the change lives in the entry's diff field.\n`

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

phase('Speak')

const CHUNK = 12
const chunks = []
for (let i = 0; i < ids.length; i += CHUNK) chunks.push(ids.slice(i, i + CHUNK))

const renderChunk = (chunkIds, retry) => agent(
  REGISTER + CHARTER + `\nEntries to render, by id: ${chunkIds.join(', ')}. Return one items[] element per id, ids as strings.`,
  { label: `speak:${chunkIds[0]}-${chunkIds[chunkIds.length - 1]}${retry ? ':retry' : ''}`, phase: 'Speak', schema: ITEMS_OUT })

// Barrier on purpose: coverage of every id is checked across ALL chunk results
// before the retry round, and the page prose is part of the same return value.
const [page, ...chunkResults] = await parallel([
  () => agent(
    REGISTER + CHARTER +
    `\nDo not render entries. Return the page-level prose instead: intro_html for the decision page; option_help one-liners for apply / discuss / skip (apply = make the proposed change, a note adjusts its wording; discuss = no change yet, talk it through in chat first; skip = leave as is — keep those meanings, in your words); and the gate wording for the mode question fired after the report opens (three fixed choices: apply findings by number, hand the skill to a from-scratch re-author, stop at the report).`,
    { label: 'speak:page', phase: 'Speak', schema: PAGE_OUT }),
  ...chunks.map(chunkIds => () => renderChunk(chunkIds, false)),
])

const rendered = {}
for (const result of chunkResults.filter(Boolean)) {
  for (const item of result.items || []) rendered[String(item.id)] = item
}
let missing = ids.filter(id => !rendered[id])
if (missing.length) {
  log(`retrying ${missing.length} unrendered id(s): ${missing.join(', ')}`)
  const retried = await renderChunk(missing, true)
  for (const item of (retried && retried.items) || []) rendered[String(item.id)] = item
  missing = ids.filter(id => !rendered[id])
}
if (missing.length) log(`unrendered after retry — these ship in ledger wording with a warning: ${missing.join(', ')}`)
if (!page) log('page prose returned nothing — director falls back to mechanical intro and gate wording')

return { voice, page, items: rendered, unrendered: missing }
