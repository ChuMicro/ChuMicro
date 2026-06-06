// exp13 WORKFLOW A — full grounding/triage stage of the regen-comments skill (--with-comment-triage ON).
// 3 code lenses read the STRIPPED code; the comment lens reads the RAW commented file and routes every
// comment to ledger/preserve/discard; the (validated) ledger-writer merges the code findings + the
// comment LEDGER-lane facts into ONE telegraphic, non-copyable ledger with per-fact confidence.
// Returns: ledger facts (w/ confidence) + the preserve lane + discard (instrumentation) + domain.
// The orchestrator then runs the human picker on low/med facts before writers (Workflow B).
// Output: exp13/findings/*.json , exp13/ledger_provisional.md

export const meta = {
  name: 'exp13-triageA',
  description: 'Full triage: 3 code lenses + comment lens -> ledger-writer. Produces the provisional ledger + preserve lane.',
  phases: [
    { title: 'Lenses', detail: '3 code lenses (stripped) + 1 comment lens (raw)' },
    { title: 'Ledger', detail: 'merge -> telegraphic ledger w/ confidence' },
  ],
}

const RUNDIR = '__RUNDIR__'
const STRIPPED = RUNDIR + '/stripped.py'
const COMMENTED = RUNDIR + '/commented.py'
const EXP = RUNDIR

// ---------- 3 CODE LENSES (validated exp10 prompts: fragment preamble) ----------
const PREAMBLE =
  'You are reading a Python file to triage facts that a per-symbol docstring writer would get WRONG '
  + 'or MISS. The file has NO comments and NO docstrings -- the code is the only source of truth. '
  + 'Do not invent meaning a name merely suggests.\n'
  + 'Record each fact as a TELEGRAPHIC FRAGMENT -- symbols, arrows (->), shorthand -- never a grammatical '
  + 'sentence a writer could paste. A precise fact (an inversion, a referent, a boundary) must stay '
  + 'unambiguous but must NOT read as English prose.\n'
  + 'Also capture the HUMAN-SCALE reading of any raw constant that encodes a real-world quantity (a '
  + 'duration in ms/ns, a size in bytes, a count or frequency): it is computable but not glanceable, so a '
  + 'reader needs it stated (e.g. a large byte value as about-N-kilobytes, a big millisecond span as '
  + 'about-N-hours-or-days).\n\n'
  + 'CROSS-FILE CONTEXT: if a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, consult it for the '
  + 'library contracts, domain, and shared glossary to interpret cross-file references (what a shared type '
  + 'or term means, what contract this file implements or uses). The per-file CODE remains the source of '
  + 'truth for THIS file. Do not import other files internal facts.\n\n'
  + 'CODE: ' + STRIPPED + '\n\n'

const FINDING = {
  type: 'object', additionalProperties: false,
  properties: {
    fact: { type: 'string' }, sites: { type: 'string' },
    cross_method: { type: 'boolean' }, confidence: { type: 'string', enum: ['high', 'med', 'low'] },
  },
  required: ['fact', 'sites', 'cross_method', 'confidence'],
}
const LENS_OUT = {
  type: 'object', additionalProperties: false,
  properties: { lens: { type: 'string' }, domain_purpose: { type: 'string' }, findings: { type: 'array', items: FINDING }, path: { type: 'string' } },
  required: ['lens', 'domain_purpose', 'findings', 'path'],
}

const CODE_LENSES = [
  { key: 'trap', out: EXP + '/findings/trap.json', body:
    'LENS: gotcha-finder. Find every place where the OBVIOUS reading of the code is subtly WRONG -- where '
    + 'a careful person writing a docstring would state something false. Look for: surprising operators '
    + '(`>=` vs `>`, inclusive vs exclusive boundaries), a value that plays more than one role, a count vs '
    + 'an identity, a condition that looks like it considers something it does not, a tie or default that '
    + 'breaks one way and not the other. For each: telegraphic fact, site, single-method vs cross-method, '
    + 'confidence. Do NOT restate plainly-correct behavior. Emit only surprises. Leave domain_purpose empty.' },
  { key: 'trace', out: EXP + '/findings/trace.json', body:
    'LENS: cross-method value tracer. For EVERY value produced in one place and consumed in another -- a '
    + 'returned field, a stored attribute, a flag/boolean handed back, an argument passed down -- trace '
    + 'where it is produced and consumed, and state WHAT IT REFERS TO at the point of consumption. Pay '
    + 'special attention to a returned flag/field whose meaning depends on WHICH branch produced it or '
    + 'WHICH argument became the result: state explicitly WHICH entity it acts on. A value fully clear '
    + 'within one method is NOT your job. Emit only cross-method or non-obvious-referent facts. Leave '
    + 'domain_purpose empty.' },
  { key: 'naming', out: EXP + '/findings/naming.json', body:
    'LENS: naming-vs-behavior and domain. (1) State in domain_purpose, one plain sentence, what this module '
    + 'actually DOES in the real world -- inferred from behavior, not wishful name-reading. (2) Find every '
    + 'place an identifier NAME promises or implies something the behavior does NOT deliver, or is '
    + 'misleading about WHICH thing it acts on. For each: the name, what it implies, what the code does, '
    + 'site, confidence. Do not invent domain facts the code does not support.' },
]
function codeLensPrompt(l) {
  return PREAMBLE + l.body + '\n\nWrite your structured result as pretty JSON to ' + l.out
    + ' and return it. Set lens to "' + l.key + '" and path to that file.'
}

// ---------- COMMENT LENS (validated exp12 3-lane prompt + placement on preserve) ----------
const COMMENT_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    lens: { type: 'string' },
    ledger: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { fact: { type: 'string' }, why_non_derivable: { type: 'string' }, source_site: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'med', 'low'] } },
      required: ['fact', 'why_non_derivable', 'source_site', 'confidence'] } },
    preserve: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { line: { type: 'string' }, placement: { type: 'string', enum: ['header-top', 'inline'] }, orig_site: { type: 'string' }, reason: { type: 'string' } },
      required: ['line', 'placement', 'orig_site', 'reason'] } },
    discard: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { gist: { type: 'string' }, category: { type: 'string', enum: ['stale-archaeology', 'redundant-with-code', 'wrong-contradicts-code', 'decorative', 'banter', 'other'] } },
      required: ['gist', 'category'] } },
    path: { type: 'string' },
  },
  required: ['lens', 'ledger', 'preserve', 'discard', 'path'],
}
const commentPrompt =
  'You are the COMMENT-TRIAGE lens. You read a Python file\'s EXISTING comments and docstrings, which are '
  + 'SUSPECT -- stale, wrong, redundant, or misplaced. The CODE is the only source of truth; a comment is a '
  + 'hint until the code confirms it.\n\nFILE: ' + COMMENTED + '\n\n'
  + 'Triage EVERY comment/docstring (account for all) into EXACTLY ONE lane:\n'
  + '(1) LEDGER -- a valuable BEHAVIOR/DOMAIN fact the code alone cannot reveal (a domain constraint, '
  + 'author intent, a real why). Paraphrase telegraphically; NEVER lift wording. VERIFY against code; if '
  + 'contradicted, it is DISCARD (wrong-contradicts-code). Cap 1-2, often ZERO. Judge on CONTENT not '
  + 'position. Record source_site.\n'
  + '(2) PRESERVE -- provenance/legal/tracking metadata kept VERBATIM, never reworded or fed to a writer: '
  + 'copyright, license, author, live TODO / issue-tracker refs. For each set placement = "header-top" '
  + '(copyright/author/license) or "inline" (a directive/TODO tied to a code location) and orig_site.\n'
  + '(3) DISCARD -- everything else w/ a category: stale-archaeology, redundant-with-code, '
  + 'wrong-contradicts-code, decorative, banter, other.\n'
  + 'Be skeptical. Do not promote a redundant or wrong comment into the ledger.\n\n'
  + 'Write JSON to ' + EXP + '/findings/comments.json and return it. lens = "comments", path = that file.'

// ---------- LEDGER-WRITER (validated exp10 v3: STUB STYLE + no-invented-examples) ----------
const LEDGER_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    facts: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { stub: { type: 'string' }, sites: { type: 'string' }, source_lenses: { type: 'array', items: { type: 'string' } }, confidence: { type: 'string', enum: ['high', 'med', 'low'] } },
      required: ['stub', 'sites', 'source_lenses', 'confidence'] } },
    domain_purpose: { type: 'string' }, ledger_path: { type: 'string' },
  },
  required: ['facts', 'domain_purpose', 'ledger_path'],
}
function ledgerPrompt(codeResults, commentLedger, domain) {
  const dump = codeResults.map((r) =>
    '### lens: ' + r.lens + '\n' + r.findings.map((f) => `- [${f.confidence}${f.cross_method ? ',xm' : ''}] ${f.fact}  (${f.sites})`).join('\n')
  ).join('\n\n')
  const cdump = commentLedger.length
    ? '\n\n### lens: comments (from existing comments; treat as facts, paraphrase further if needed)\n'
      + commentLedger.map((f) => `- [${f.confidence}] ${f.fact}  (${f.source_site})`).join('\n')
    : '\n\n### lens: comments\n(no comment-derived ledger facts)'
  return 'You are the ledger-writer. Merge findings from code-reading lenses and a comment-triage lens over '
    + 'one Python file into ONE terse nuance ledger of facts a per-symbol docstring writer would get WRONG '
    + 'or could NOT derive.\n\n'
    + 'RULES:\n'
    + '- STUB STYLE (critical): every line is a TELEGRAPHIC FRAGMENT, never a grammatical sentence a writer '
    + 'could paste. Use arrows (->), colons, shorthand. Render the mechanism as symbols, not a fluent clause '
    + '-- ESPECIALLY for precise, correctness-critical facts (a returned flag\'s referent, an inversion, a '
    + 'boundary): those are exactly what a writer copies verbatim when handed a ready-made sentence, which '
    + 'collapses voice. Stay unambiguous, do NOT write prose.\n'
    + '    GOOD: `flushed=True -> kept=cache_path (no live socket); the dropped socket is the REJECTED net_path, never kept`\n'
    + '    BAD:  `the flag signals closing the rejected path socket, not the kept path socket`\n'
    + '- Dedup: same fact from two lenses -> one stub, list both source lenses.\n'
    + '- Keep every DISTINCT grounded fact. Bias toward keeping a real fact.\n'
    + '- Do not introduce domain wording the lenses did not ground in the code.\n'
    + '- NO INVENTED EXAMPLES. Do not fabricate a numeric/illustrative example. A concrete example is allowed '
    + 'ONLY if it uses actual values from the code\'s COMPONENTS/constants AND verified true against the '
    + 'formula by reading the code. When unsure, give NO example.\n'
    + '- COMMENT-DERIVED facts (source lens "comments") are NON-CODE-DERIVABLE BY DESIGN: they come from '
    + 'now-stripped comments and are NOT in the code you verify against. Carry each as a CLEAN paraphrased '
    + 'domain-rule stub at the confidence the comment lens gave it. Do NOT try to ground it in the code, do '
    + 'NOT cite code line numbers for it, and NEVER add meta-commentary like "[UNVERIFIABLE]", "cannot '
    + 'ground", or "absent in file". If it is implausible as a domain rule, DROP it silently instead of '
    + 'annotating doubt.\n'
    + '- For each fact: a telegraphic stub, code sites, source lens keys, a confidence.\n\n'
    + 'CODE (verify against it): ' + STRIPPED + '\n\n'
    + 'LENS FINDINGS:\n' + dump + cdump + '\n\n'
    + 'Write the merged ledger as a terse markdown stub list (one `- ` line per fact, sites in parens; every '
    + 'line a fragment per STUB STYLE) to ' + EXP + '/ledger_provisional.md, set ledger_path to it, return '
    + 'the structured result. Set domain_purpose to: "' + (domain || '') + '".'
}

// ---------- run ----------
phase('Lenses')
const lensResults = await parallel([
  ...CODE_LENSES.map((l) => () => agent(codeLensPrompt(l), { label: 'lens:' + l.key, phase: 'Lenses', model: 'opus', agentType: 'general-purpose', schema: LENS_OUT }).then((r) => ({ kind: 'code', r }))),
  () => agent(commentPrompt, { label: 'lens:comments', phase: 'Lenses', model: 'opus', agentType: 'general-purpose', schema: COMMENT_OUT }).then((r) => ({ kind: 'comment', r })),
])
const code = lensResults.filter(Boolean).filter((x) => x.kind === 'code').map((x) => x.r)
const comment = (lensResults.filter(Boolean).find((x) => x.kind === 'comment') || {}).r || { ledger: [], preserve: [], discard: [] }
const domain = (code.find((r) => r.domain_purpose) || {}).domain_purpose || ''

phase('Ledger')
const ledger = await agent(ledgerPrompt(code, comment.ledger || [], domain), { label: 'ledger-writer', phase: 'Ledger', model: 'opus', agentType: 'general-purpose', schema: LEDGER_OUT })

const questionable = (ledger.facts || []).filter((f) => f.confidence === 'low' || f.confidence === 'med')
return { facts: ledger.facts, domain_purpose: ledger.domain_purpose, ledger_path: ledger.ledger_path, preserve: comment.preserve || [], discard: comment.discard || [], questionable }
