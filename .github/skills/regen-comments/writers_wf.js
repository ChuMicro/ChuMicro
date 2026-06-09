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

// The writer (converged rounds 7-31): the SUMMARIZER's own framing -- "explain in plain English what the code
// does; each symbol's purpose + non-obvious behavior". Round31 CUT the prompt from 772 words back to ~230: a
// head-to-head on the SAME ledger showed the lean version reads BETTER ([[summarizer-key]] -- more prompt
// degrades the comments, so the writer is kept near the summarizer's size and calm, near-caps-free tone).
// Keeps the BEHAVIOR-not-mechanism spine (docstring = what it does + the caller's contract; a line-level
// mechanic -- an inclusive boundary, a sign, a stand-in substitution -- rides ONLY as an inline `#` comment)
// plus the three round26-proven extras (anti-jargon, don't-restate-self-evident, no back-refs). Two siblings
// carry what the lean prompt drops: the triage_wf.js citation fix keeps a behavioral fact off a data record at
// the source, and flag_legibility.py flags the rare convoluted roll for the human. Voice is OPTIONAL and
// round32 made it FORWARD: VOICE_PARA empty -> the plain-English register (the default); non-empty -> the
// voice REPLACES that register and runs free (no "yields to clarity" restraint), the one limit being a clear,
// usable docstring. The SELECTOR picks the RICHEST, best-worded pass, not the flattest (flat is wrong);
// legibility is its only floor, correctness its secondary one -- a garbled or backwards pass still loses.
function genPrompt(n) {
  const voiced = VOICE_PARA.trim()
  const voiceBlock = voiced
    ? (VOICE_PARA + ' Write the docstrings and comments FULLY in that voice -- let it come through in word '
       + 'choice, rhythm, and attitude, do not hold it back. The one limit is that each docstring stays a '
       + 'clear, usable docstring a caller could rely on, never garbled or obscure.\n\n')
    : ''
  const register = voiced ? 'in that voice' : 'in plain English'
  const wordChoice = voiced
    ? 'Keep it clear and do not let dense jargon slip in to sound precise (say "a cache that remembers what '
      + 'it already computed", not "a memoization layer"). '
    : 'Use plain, ordinary words, not a denser technical label (say "a cache that remembers what it already '
      + 'computed", not "a memoization layer"). '
  return voiceBlock
    + 'Read the code at ' + FILE + ' and the nuance ledger at ' + LEDGER + ' together. The ledger holds the '
    + 'non-obvious behavior a plain reading of the code misses.\n\n'
    + 'Explain ' + register + ' what the code does. For the module, what the file does in the real world. For '
    + 'each class, function, and method, its purpose and any non-obvious behavior: what it does and the '
    + 'contract a caller relies on, not how a particular line computes. ' + wordChoice + 'Do not restate '
    + 'what the code already shows, like an enum\'s members when their names already '
    + 'say it, do not point the reader to other symbols by name, and do not invent.\n\n'
    + 'A line-level mechanic, such as an inclusive boundary, a value compared one way and not another, or a '
    + 'stand-in substitution, rides as a short `#` comment on its own line above that line, not in the '
    + 'docstring. State each fact once.\n\n'
    + 'If a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, use it for cross-file context and '
    + 'shared vocabulary.\n\n'
    + 'Give Args and Returns (or Raises) for the functions and methods that have them, each a short plain '
    + 'description. No em-dashes or semicolons or the words `canonical` or `shape`. Wrap code expressions in '
    + 'double backticks and keep lines to 100 characters. Add docstrings and comments only.\n\n'
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
    + 'YOUR PRIMARY JOB IS HOW THE COMMENTS READ. Pick the file whose comments are the RICHEST and '
    + 'best-worded -- the most alive, vivid, and characterful, the one a reader would actually enjoy. Do NOT '
    + 'pick the flattest or most bare option because it feels safe: flat is wrong, richness wins. A file with '
    + 'character, varied wording, and well-turned sentences beats a thin, generic one. The ONLY floor is '
    + 'legibility: every sentence must still read clearly as a proper docstring a caller could use. A '
    + 'sentence that is garbled, so dense or comma-ridden it confuses, or contorted past being understood is '
    + 'not rich, it is broken, and it loses -- but a vivid metaphor or a strong turn of phrase that reads '
    + 'clearly IS richness, and it wins.\n\n'
    + 'Correctness is a SECONDARY sanity check, not a completeness test. Among the well-written files, reject '
    + 'one that MISLEADS about what the code does: a comment that states the opposite of the code, pins a '
    + 'result on the wrong thing, or garbles a non-obvious behavior into a statement that cannot hold '
    + 'together. But do NOT punish a rich file for leaving out a minor detail. When two files read about '
    + 'equally well, prefer the one that gets the non-derivable traps right.\n\n'
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
