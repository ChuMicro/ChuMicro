// regen-comments WRITER PHASE (production, fixture-agnostic). Run inside ONE `claude -p` from the run
// room. One voice, PASSES summarizer-spine writer passes (clean-room: stripped code + final ledger only), then a GENERIC
// best-of-N SELECTOR that reads all N complete files and picks the single best one BY NUMBER. The
// selector never edits, merges, or rewrites — phase 2 copies the chosen file verbatim, so the output is
// byte-identical to one writer's pass by construction. No trap list, no fixture knowledge. Orchestrator
// substitutes __RUNDIR__, __VOICE_PARA__. Reads __RUNDIR__/{stripped.py, ledger_final.md}; writes
// __RUNDIR__/{runs/run-N.py, pick.json, summary.json}.

export const meta = {
  name: 'regen-write',
  description: 'One voice x N passes, then pick the single best whole file, clean-room. Fixture-agnostic.',
  phases: [{ title: 'Generate', detail: 'N passes, one voice' }, { title: 'Select', detail: 'best of N whole files' }],
}

const RUNDIR = '__RUNDIR__'
const FILE = RUNDIR + '/stripped.py'
const LEDGER = RUNDIR + '/ledger_final.md'
const PASSES = 4
const VOICE_PARA = "__VOICE_PARA__"

const GEN_SCHEMA = { type: 'object', additionalProperties: false, properties: { path: { type: 'string' } }, required: ['path'] }

// The writer is the SUMMARIZER-SPINE (validated rounds 7-10): it explains the file to a FIRST-TIME reader
// (introduce a thing before referencing it, so no cataloging of names the reader has not met yet), uses the
// ledger ONLY to correct the plain read and add the non-derivable traps, pitches a module/class high and
// methods at the mechanism, and carries the voice as a layer that yields to clarity. Voice (VOICE_PARA) rides
// in every pass. Examples here are FOREIGN on purpose (deadline / registry / cache) — never fixture-derived.
function genPrompt(n) {
  return 'You are explaining a Python file to an engineer who is reading it for the FIRST TIME, top to '
    + 'bottom. This is the thing that matters most: when they reach any docstring they have read only the '
    + 'code ABOVE it, never the whole file at once. So the first time you mention a class, a field, or an '
    + 'idea, DESCRIBE what it is in the same breath. Never refer to something as already known when the '
    + 'reader has not met it yet. Write "a deadline, measured in milliseconds", not "the deadline field"; '
    + 'describe "a registry that maps names to handlers", do not just say "the registry". Introduce, do not '
    + 'catalog the file\'s contents by name.\n\n'
    + 'Write in the following voice. Let it shape your word choice, your rhythm, and what you choose to '
    + 'emphasize. But the first-time reader\'s understanding always wins: if the voice would cram, obscure, '
    + 'or make you reference something not yet introduced, the voice yields. Clarity first, personality on '
    + 'top of it.\n\nTHE VOICE: ' + VOICE_PARA + '\n\n'
    + 'WORK IN TWO STEPS. STEP 1: Read ONLY the code at ' + FILE + '. For each symbol, the module, each '
    + 'class, and each function or method, write a clear, flowing explanation the way you would say it out '
    + 'loud to that first-time reader. Pitch each at its own altitude:\n'
    + '- A MODULE or CLASS says what the thing is and what it is for, and names the parts or dimensions it '
    + 'works with by describing them, not by listing their names. When the real work splits into cases or '
    + 'runs a multi-step rule, only GESTURE at that in a few words (for example "with a separate fast path '
    + 'for already-cached entries") and leave the actual mechanism to the method that implements it. Do not '
    + 'walk the branching logic in a module or class summary. The one detail worth keeping up here is a TRAP '
    + 'that corrects a wrong reading, such as a name that promises more than the code delivers.\n'
    + '- A METHOD or FUNCTION says what the caller gets or what changes, and this is where the real '
    + 'mechanism and its traps belong.\n'
    + 'Explain in plain, natural English. Do not strain and do not perform a style, just be clear and true.\n\n'
    + 'STEP 2: Now read the nuance ledger at ' + LEDGER + '. It holds ONLY the non-derivable traps, the '
    + 'things a plain reading gets wrong or cannot see. Correct your explanation wherever the ledger shows '
    + 'it was wrong, and fold in any trap a first-time reader would need, in your own plain words. Do not '
    + 'copy the ledger\'s wording, pull only the fact. '
    + 'If a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, treat it as a correctness and '
    + 'vocabulary reference: use the right shared terms and do not contradict a library contract. Do NOT '
    + 'restate library-wide facts the code here does not touch. A contract or glossary term belongs in a '
    + 'comment only where a symbol in THIS file actually uses or implements it.\n\n'
    + 'Then turn each explanation into a docstring:\n'
    + '- The SUMMARY carries the explanation. Most symbols need nothing more than a clear summary.\n'
    + '- Reach for a body paragraph only when a real fact genuinely cannot sit in the summary, and keep it '
    + 'to a sentence or two.\n'
    + '- `Args:` for every parameter, named tightly: what it is in a few words, not a re-explanation of what '
    + 'the summary already said. Then `Returns:` / `Raises:` only where they add a constraint the name and '
    + 'type do not. A boolean return needs no `Returns:`.\n'
    + '- Enum members are not parameters: never give an enum an `Args:` block or invent a meaning for a '
    + 'member from its name.\n'
    + '- No em-dashes, no semicolons, and never the words `canonical` or `shape`. Wrap code expressions in '
    + 'double backticks. No diagrams or tables. Keep every line to 100 characters or fewer.\n'
    + '- Add docstrings and comments only. Every line of executable code stays byte-for-byte identical, and '
    + 'keep any directive line (`# noqa`, `# type: ignore`, `# pragma:`) verbatim.\n\n'
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
    + 'YOUR PRIMARY JOB IS VOICE AND FLOW. Pick the file whose comments READ BEST — the clearest, most '
    + 'natural, best-voiced prose, the one an engineer would most want to read. Plain flowing sentences win. '
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
