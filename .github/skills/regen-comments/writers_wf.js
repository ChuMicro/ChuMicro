// regen-comments WRITER PHASE (production, fixture-agnostic). Run inside ONE `claude -p` from the run
// room. One voice, PASSES writer passes (clean-room: stripped code + final ledger only), then a GENERIC
// per-symbol consolidation judge (best docstring+comments per module/class/method/function across the
// passes -> one merged file). No trap list, no fixture knowledge. Orchestrator substitutes __RUNDIR__,
// __VOICE_PARA__. Reads __RUNDIR__/{stripped.py, ledger_final.md}; writes __RUNDIR__/{runs/run-N.py,
// merged.py, picks.json}.

export const meta = {
  name: 'regen-write',
  description: 'One voice x N passes + per-symbol consolidation, clean-room. Fixture-agnostic.',
  phases: [{ title: 'Generate', detail: 'N passes, one voice' }, { title: 'Consolidate', detail: 'best per symbol -> merged' }],
}

const RUNDIR = '__RUNDIR__'
const FILE = RUNDIR + '/stripped.py'
const LEDGER = RUNDIR + '/ledger_final.md'
const PASSES = 4
const VOICE_PARA = "__VOICE_PARA__"

function discipline() {
  let s = 'Your voice comes first. Where a rule below would flatten your natural voice, keep the voice and break the rule. Otherwise follow them all.\n\n'
  s += '## Document every parameter\n\nEvery public parameter gets an `Args:` entry describing the input. Never skip one even if it looks obvious.\n'
    + '- Enum members are not parameters. Never give an enum an `Args:` block, and never invent a per-member meaning from its name. If the code gives a member no behavior beyond its value, say only what is true, usually just that the names label the bits and the code counts how many are set.\n\n'
  s += '## Format\n\n- Open a module file with a one to two sentence module docstring for the file as a whole.\n'
    + '- Summary: behavior first, what the thing does, not where it lives. Take as many sentences as it honestly needs, no padding.\n'
    + '- Body: include one when it carries a fact the summary cannot, or a non-derivable nuance. If the summary is enough, skip it.\n'
    + '- Readers of the summary and body have not read the Args yet. Describe a parameter used in them, do not just reference it.\n'
    + '- `Args:` for every parameter, then `Returns:` / `Raises:` where they state a constraint the name and type do not. A boolean return needs no `Returns:`; say what True/False mean when not obvious.\n'
    + '- Section order is always summary, body, `Args:`, `Returns:`, `Raises:`.\n'
    + '- Double-backtick code expressions. No ASCII diagrams or tables; document a transition in sentences or bullets with arrows.\n'
    + '- Keep all lines to 100 chars or fewer.\n\n'
  s += '## Hard rules\n\n- Executable code stays byte-identical. Add docstrings and comments only.\n'
    + '- Keep every directive line verbatim (`# noqa` / `# type: ignore` / `# pragma:` etc.).\n'
    + '- Never invent. State only what the code does. A name is a hint, not a fact. If you cannot derive a claim from the code and the ledger does not carry it, leave it out.\n'
    + '- Every comment stands alone. No "see ``X``", no pointer to another symbol or module, no other package or runtime named for contrast. No license or file-header lines.\n\n'
  s += '## Write correct English\n\n- No em-dashes. A period between two independent clauses, a colon before a list, a comma for a brief aside.\n'
    + '- No semicolons. Two thoughts are two sentences.\n'
    + '- Two words are banned outright: `canonical` and `shape`, in any form, no exceptions.\n'
    + '- Never drop a code identifier or quoted string into a boilerplate frame. No "``X`` is the entry point", no error string restated word for word.\n'
    + '- Never start any sentence with `The`, `That`, `That\'s`, `This`, `These`, or `Those`, no exceptions. Lean on a precise verb and a concrete noun.\n'
    + '- Let the writing breathe. Vary how sentences open and how they are built, so a file does not read like one filled-in template.\n\n'
  return s
}
const DISC = discipline()
const GEN_SCHEMA = { type: 'object', additionalProperties: false, properties: { path: { type: 'string' } }, required: ['path'] }

function genPrompt(n) {
  return 'You will add docstrings and comments to a Python file. Follow this discipline exactly:\n\n' + DISC + '\n'
    + '## Your voice\n\n' + VOICE_PARA + '\n\n'
    + 'Read the nuance ledger at ' + LEDGER + ' for which facts matter (do not copy its wording, pull only the concrete data) and the code at ' + FILE + '. '
    + 'If a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, treat it as a correctness and vocabulary reference: use the right shared terms and do not contradict a library contract. Do NOT restate library-wide facts the code here does not touch. A contract or glossary term belongs in a comment only where a symbol in THIS file actually uses or implements it. The per-file code and ledger remain the source of truth for this file. '
    + 'Add docstrings and comments only. Every line of executable code stays byte-identical. Write the marked-up file to ' + RUNDIR + '/runs/run-' + n + '.py. After writing, reply DONE.'
}

const CONSOL_SCHEMA = {
  type: 'object', additionalProperties: false,
  properties: { merged_path: { type: 'string' }, picks: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { symbol: { type: 'string' }, winner: { type: 'integer' }, why: { type: 'string' } }, required: ['symbol', 'winner', 'why'] } } },
  required: ['merged_path', 'picks'],
}
function consolPrompt() {
  const runs = Array.from({ length: PASSES }, (_, i) => RUNDIR + '/runs/run-' + (i + 1) + '.py').join(' , ')
  return 'You are a PER-SYMBOL consolidation judge (fixture-agnostic — no trap list, no knowledge of this '
    + 'file). You have ' + PASSES + ' candidate commented versions of the SAME file, one voice: ' + runs + '. '
    + 'Plus the stripped code ' + FILE + ' and the nuance ledger ' + LEDGER + '.\n\n'
    + 'If a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, use it as a correctness/vocabulary '
    + 'reference: prefer a candidate that uses shared terms correctly and does not contradict a library '
    + 'contract, and do NOT reward a candidate that dumps library-wide facts where this file\'s code does '
    + 'not touch them.\n\n'
    + 'Produce ONE merged file. FOR EACH SYMBOL separately (the module docstring, each class, each method, '
    + 'each function), take the docstring AND that symbol\'s inline comments from whichever candidate '
    + 'documented THAT symbol best: most correct against the code, carrying any MUST-CARRY ledger fact (a '
    + 'NON-DERIVABLE fact from the ledger) that pertains to it, best written, with no phrase lifted verbatim '
    + 'from the ledger. Mix freely across candidates.\n'
    + 'Keep every line of EXECUTABLE CODE byte-identical to ' + FILE + '. Add only docstrings and comments.\n\n'
    + 'Write the merged file to ' + RUNDIR + '/merged.py and a per-symbol rationale to ' + RUNDIR
    + '/picks.json. Return merged_path = the merged file and picks = [{symbol, winner, why}]. Reply only after both files are written.'
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
phase('Consolidate')
const merged = await agent(consolPrompt(), { label: 'consolidate', phase: 'Consolidate', model: 'opus', agentType: 'general-purpose', schema: CONSOL_SCHEMA })
return merged
