// regen-comments WRITER PHASE (production, fixture-agnostic). Run inside ONE `claude -p` from the run
// room. PASSES writer passes (clean-room: stripped code + final ledger only; voiceless by default, voice optional), then a GENERIC
// best-of-N SELECTOR that reads all N complete files and picks the single best one BY NUMBER. The
// selector never edits, merges, or rewrites — phase 2 copies the chosen file verbatim, so the output is
// byte-identical to one writer's pass by construction. No trap list, no fixture knowledge. Orchestrator
// substitutes __RUNDIR__, __VOICE_PARA__. Reads __RUNDIR__/{stripped.py, ledger_final.md}; writes
// __RUNDIR__/{runs/run-N.py, pick.json, summary.json}.

export const meta = {
  name: 'regen-write',
  description: 'N passes (voiceless default, voice optional), then pick the single best whole file, clean-room. Fixture-agnostic.',
  phases: [{ title: 'Generate', detail: 'N passes' }, { title: 'Select', detail: 'best of N whole files' }],
}

const RUNDIR = '__RUNDIR__'
const FILE = RUNDIR + '/stripped.py'
const LEDGER = RUNDIR + '/ledger_final.md'
const PASSES = 4
const VOICE_PARA = "__VOICE_PARA__"

const GEN_SCHEMA = { type: 'object', additionalProperties: false, properties: { path: { type: 'string' } }, required: ['path'] }

// The writer (converged rounds 7-24): the SUMMARIZER's own framing -- "explain what the file does in the real
// world; each symbol's purpose + non-obvious behavior" -- which introduces-not-catalogs on its own, so the
// explicit cold-reader block was DROPPED as redundant (round24 confirmed no cataloging without it). Reads code
// + ledger TOGETHER in one pass (no two-step), keeps the DOCSTRING tight (purpose + the caller's contract, a
// one-or-two-sentence body), and puts a LINE-LEVEL gotcha as a `#` comment on its own line ABOVE the line it
// concerns. Comments only the non-obvious (never restates self-evident code like enum members), states each
// fact once, stands alone (no pointers to other symbols). Voice is OPTIONAL: VOICE_PARA empty -> voiceless
// (the default, reads cleanest); non-empty -> a persona layered on, yielding to clarity.
function genPrompt(n) {
  const voiceBlock = VOICE_PARA.trim()
    ? ('Write in the following voice. Let it shape your word choice and rhythm, but the first-time reader\'s '
       + 'understanding always wins: if the voice would cram or obscure, the voice yields.\n\nTHE VOICE: '
       + VOICE_PARA + '\n\n')
    : ''
  return voiceBlock
    + 'Read the code at ' + FILE + ' and the nuance ledger at ' + LEDGER + ' together. The ledger holds the '
    + 'non-obvious behavior a plain reading of the code misses, read it as part of understanding the '
    + 'code.\n\n'
    + 'Then explain what the code does. For the module, what the file does in the real world. For each '
    + 'class, function, and method, its purpose and the contract a caller needs, in a clear summary and at '
    + 'most a one or two sentence body. Keep the docstring tight. Comment only what a reader cannot already '
    + 'see in the code: never restate self-evident names or values, such as re-listing an enum\'s members '
    + 'when their names already say what they are. For something like that, add only the non-obvious part, '
    + 'or nothing if there is none.\n\n'
    + 'Put a LINE-LEVEL gotcha as a short `#` comment on its OWN LINE ABOVE the line it concerns, not '
    + 'trailing it. A subtle implementation detail, like a boundary that is inclusive, a value compared one '
    + 'way and not another, or a stand-in substitution, belongs as a comment right at that code line where a '
    + 'reader meets it. Comment only the genuinely non-obvious lines, never narrate ordinary code. State '
    + 'each fact once, in one place, the docstring or a comment, never both.\n\n'
    + 'If a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, use it for cross-file context and '
    + 'shared vocabulary.\n\n'
    + 'Each comment stands on its own, so say what a symbol does in plain terms rather than pointing the '
    + 'reader to other symbols by name or to its caller. Do not invent, state only what the code and the '
    + 'ledger support.\n\n'
    + 'Write each docstring with Args and Returns (or Raises) for the functions and methods that have them. '
    + 'No em-dashes or semicolons or the words `canonical` or `shape`. Wrap code expressions in double '
    + 'backticks and keep lines to 100 characters. Add docstrings and comments only.\n\n'
    + 'Write the marked-up file to ' + RUNDIR + '/runs/run-' + n + '.py. After writing, reply DONE.'
}

const SELECT_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { winner: { type: 'integer' }, why: { type: 'string' }, concern: { type: 'string' } },
  required: ['winner', 'why', 'concern'],
}
function selectPrompt() {
  const runs = Array.from({ length: PASSES }, (_, i) => '  ' + (i + 1) + ': ' + RUNDIR + '/runs/run-' + (i + 1) + '.py').join('\n')
  return 'You are a SELECTOR (fixture-agnostic — no trap list, no prior knowledge of this file). '
    + PASSES + ' candidate commented versions of the SAME file were written in one voice, each a COMPLETE '
    + 'file. Read all of them, plus the stripped code ' + FILE + ' and the nuance ledger ' + LEDGER + ' for '
    + 'context. Pick the ONE best complete file by its number. You do NOT edit, merge, rewrite, or combine '
    + 'files — you only choose one. The chosen file is taken exactly as written.\n\n'
    + 'Candidates (number: path):\n' + runs + '\n\n'
    + 'If a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, use it as a vocabulary reference: '
    + 'prefer a file that uses the shared terms correctly.\n\n'
    + 'YOUR PRIMARY JOB IS HOW THE COMMENTS READ. Pick the file whose comments READ BEST — the clearest, '
    + 'most natural prose, the one an engineer would most want to read. Plain flowing sentences win. '
    + 'Do NOT reward a file for being more thorough, more precise, or carrying more facts when it reads '
    + 'worse: a dense, comma-ridden, compressed, or enumerated file LOSES to a clean flowing one even when '
    + 'the dense one is more complete. Readability is the goal.\n\n'
    + 'Correctness is a SECONDARY sanity check, not your main goal and NOT a completeness test. Among the '
    + 'well-written files, only avoid one that says something flatly false or backwards — a comment that '
    + 'states the opposite of what the code does, or pins a result on the wrong thing, misleads the reader '
    + 'and should not win on flow alone. But do NOT punish a fluent file for leaving out a minor detail or '
    + 'being less exhaustive: a readable file with a small gap beats a clunky complete one. When two files '
    + 'read about equally well, prefer the one that gets the non-derivable traps right.\n\n'
    + 'Write {winner, why, concern} to ' + RUNDIR + '/pick.json — winner = the chosen number from 1 to '
    + PASSES + ', why = one or two sentences on why it reads best, concern = any correctness issue you '
    + 'noticed in the chosen file (so a human can double-check it), or "" if none. Return the same object. '
    + 'Do not write any other file. Reply only after pick.json is written.'
}

// Independent summarizer: plain-English purpose per symbol, read from the CODE only (never the generated
// comments), so the HTML report gives the human a higher-level description to sanity-check the comments
// against — one they did not write. Runs alongside the writer passes (it shares nothing with them).
const SUMMARY_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: {
    module_summary: { type: 'string' },
    symbols: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { symbol: { type: 'string' }, purpose: { type: 'string' } }, required: ['symbol', 'purpose'] } },
    path: { type: 'string' },
  },
  required: ['module_summary', 'symbols', 'path'],
}
function summaryPrompt() {
  return 'You are a code SUMMARIZER. Read ONLY the stripped code at ' + FILE + ' (it has no comments or '
    + 'docstrings) and, if it exists, the library ledger at ' + RUNDIR + '/LIBRARY_FACTS.md for cross-file '
    + 'context. Explain in PLAIN ENGLISH what the code does, INDEPENDENT of any documentation -- this lets a '
    + 'human sanity-check generated comments against a higher-level description they did not write. '
    + 'module_summary: 1-3 sentences on what this file does in the real world. symbols: for EACH top-level '
    + 'class and function, and each method, one plain sentence on its purpose and any non-obvious behavior '
    + '(symbol = a qualified name like "ClassName.method" or "func"). Do NOT invent; state only what the '
    + 'code supports. Write JSON {module_summary, symbols, path} to ' + RUNDIR + '/summary.json (path = that '
    + 'file) and reply DONE.'
}

phase('Generate')
const genTasks = Array.from({ length: PASSES }, (_, i) => i + 1).map((n) => () =>
  agent(genPrompt(n), { label: 'gen#' + n, phase: 'Generate', model: 'opus', agentType: 'general-purpose', schema: GEN_SCHEMA }))
genTasks.push(() => agent(summaryPrompt(), { label: 'summarize', phase: 'Generate', model: 'opus', agentType: 'general-purpose', schema: SUMMARY_SCHEMA }))
await parallel(genTasks)
phase('Select')
const pick = await agent(selectPrompt(), { label: 'select', phase: 'Select', model: 'opus', agentType: 'general-purpose', schema: SELECT_SCHEMA })
return pick
