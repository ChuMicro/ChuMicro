// audit-code EVALUATION workflow. Run inside ONE `claude -p` from the run room (clean: no project
// CLAUDE.md by cwd-ancestry, file access bounded to the room). It deeply evaluates ONE source file from
// four angles, produces a patch for every finding, and (optionally) voices the prose.
//
// Inputs in the room (the launcher places them):
//   stripped.py       executable code, comments + docstrings removed -- the code lenses judge from THIS, so
//                     a stale or misleading comment cannot anchor them into the wrong reading.
//   commented.py      the original file WITH its comments -- the drift lens AND the patcher read this (the
//                     patcher's before-snippets must match the REAL file exactly so a patch applies).
//   tests.py          the file's located tests, concatenated (or a NO-TESTS marker) -- the coverage lens.
//   voice_persona.txt the chosen voice persona (only when VOICED == 'yes'); the voicer reads it.
//   LIBRARY_FACTS.md  optional cross-file context (domain + contracts + glossary) in library mode.
//
// Shape: a summarizer + FOUR lenses run in parallel on the code; a merger consolidates every finding into a
// telegraphic FACT LEDGER (defect / bite / fix as un-pasteable FRAGMENTS, never finished sentences) and
// assigns a STABLE integer id (the apply-by-number); a fixture-agnostic validator re-checks every finding +
// fix against the code and drives a merger re-run loop until clean or the cap. Then, in parallel: a WRITER
// composes the reader prose (title / consequence / problem / fix) FRESH from the fragments in the chosen
// register (plain, or a voice that REPLACES the plain register -- never a rewrite of an already-fluent
// draft, which echoes and flattens), and a PATCHER emits an apply-ready before/after per finding. The voice
// is composed at write time from facts; that is the whole reason the merger emits fragments, not prose.
// Writes summary.json, eval.json (the fact ledger), validation.json, written.json (the reader prose),
// patches.json, findings/*.json. The orchestrator substitutes __RUNDIR__.

export const meta = {
  name: 'audit-code-eval',
  description: 'Evaluate one source file from four angles, validate the facts, then write the prose in voice and patch every finding.',
  phases: [
    { title: 'Read', detail: 'summarizer + 4 lenses (correctness / drift / coverage / clarity)' },
    { title: 'Merge', detail: 'consolidate into a fact ledger, assign stable fix numbers' },
    { title: 'Validate', detail: 'fixture-agnostic re-check of every finding + fix; merger re-run loop' },
    { title: 'Compose', detail: 'writer composes the prose in voice + patcher patches every finding' },
  ],
}

const RUNDIR = '__RUNDIR__'
const STRIPPED = RUNDIR + '/stripped.py'
const COMMENTED = RUNDIR + '/commented.py'
const TESTS = RUNDIR + '/tests.py'
const FINDINGS = RUNDIR + '/findings'

// ---------- shared scales + the fact-fragment finding shape ----------
// Lenses and the merger emit FRAGMENTS, not sentences. A later writer composes the reader prose; if it is
// handed a fluent sentence it pastes yours and the writing goes flat (the regen-comments lesson). So every
// finding carries three telegraphic fact fragments -- defect / bite / fix -- with no grammar to paste.
const SCALES =
  'For each finding, record THREE telegraphic FACT FRAGMENTS -- never finished sentences. A later writer '
  + 'composes the reader prose; hand it a fluent sentence and it pastes yours and the writing goes flat. Use '
  + 'arrows (->), colons, shorthand -- no grammar to paste:\n'
  + '- defect: WHAT is wrong (e.g. `save() sets _corrupt=False at end unconditionally; force_corrupt had set it True`).\n'
  + '- bite: the CONSEQUENCE -- who/what is hurt, WHEN, how bad (e.g. `caller marked data corrupt to block '
  + 'reads -> next save silently clears it -> reads succeed, no error, safety state gone`).\n'
  + '- fix: the change (e.g. `drop the _corrupt=False line in save(); only reset_corrupt() clears corruption`).\n'
  + 'Keep them precise but un-pasteable. Score three scales: severity (high = correctness bug / silently '
  + 'wrong / data loss / a caller misled; med = real hazard or likely-misuse; low = polish), effort '
  + '(small / medium / large), confidence (high / med / low -- a guess is low, do not inflate).\n'
  + 'LOCATING A FINDING: set `symbol` to the enclosing qualname (e.g. `Buffer.push`, or `<module>`) and '
  + '`site` to a SHORT QUOTE of the exact code line(s). The code you read is a COMMENT-STRIPPED copy, so raw '
  + 'line numbers will NOT match the real file -- the symbol plus quoted code is what locates it.\n'

const CROSSFILE =
  '\nCROSS-FILE: if a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, consult it to interpret '
  + 'shared types, contracts, and domain terms -- but judge only THIS file. Do not report a cross-file '
  + 'contract the library ledger already documents as if it were a defect here.\n'

const FINDING = {
  type: 'object', additionalProperties: false,
  properties: {
    angle: { type: 'string', enum: ['trap', 'drift', 'coverage', 'clarity'] },
    symbol: { type: 'string' },
    site: { type: 'string' },
    severity: { type: 'string', enum: ['high', 'med', 'low'] },
    effort: { type: 'string', enum: ['small', 'medium', 'large'] },
    confidence: { type: 'string', enum: ['high', 'med', 'low'] },
    defect: { type: 'string' },
    bite: { type: 'string' },
    fix: { type: 'string' },
  },
  required: ['angle', 'symbol', 'site', 'severity', 'effort', 'confidence', 'defect', 'bite', 'fix'],
}
const LENS_OUT = {
  type: 'object', additionalProperties: false,
  properties: { lens: { type: 'string' }, findings: { type: 'array', items: FINDING }, path: { type: 'string' } },
  required: ['lens', 'findings', 'path'],
}

// ---------- LENS 1: correctness / traps (stripped code) ----------
const trapPrompt =
  'You are the CORRECTNESS lens. Read the code and find where it is, or could be, WRONG -- not stylistically, '
  + 'but in behavior. The file has NO comments and NO docstrings: the code is the only source of truth. Do '
  + 'NOT trust what a name suggests; trust what the code does.\n\nCODE: ' + STRIPPED + '\n\n'
  + 'Hunt specifically for:\n'
  + '- INVERSIONS: a boolean, guard, or returned flag that means the OPPOSITE of the naive reading.\n'
  + '- BOUNDARY / off-by-one: `<=` vs `<`, inclusive vs exclusive, fencepost, a loop one too many/few, a '
  + 'slice bound.\n'
  + '- MIS-REFERENT / cross-method: a returned value or stored attribute whose meaning depends on WHICH '
  + 'branch or argument produced it -- trace it across methods and state which entity it really refers to.\n'
  + '- SWAPPED / wrong args, sign errors, a value that plays two roles and gets confused between them.\n'
  + '- SWALLOWED errors / silent failure, a resource opened but never closed, state assumed persisted that '
  + 'is not, a side effect (I/O, hardware, allocation) hidden in a constructor or property.\n'
  + '- RUN IT IN YOUR HEAD: pick representative inputs INCLUDING edges (empty, zero, negative, the max, the '
  + 'exact boundary, None, a duplicate, a wrap-around) and simulate by hand. When an edge gives a surprising '
  + 'or wrong result, put the concrete trace (inputs -> what the code computes -> why wrong) in the `defect` '
  + 'fragment.\n\n'
  + SCALES + CROSSFILE
  + '\nReport ONLY genuine behavior problems or real latent risks. Set angle="trap". Write JSON '
  + '{lens:"trap", findings, path} to ' + FINDINGS + '/trap.json and return it.'

// ---------- LENS 2: code-vs-claim drift (reads the COMMENTED file + code) ----------
const DRIFT_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    lens: { type: 'string' },
    findings: { type: 'array', items: FINDING },
    domain_facts: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { fact: { type: 'string' }, source_site: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'med', 'low'] } },
      required: ['fact', 'source_site', 'confidence'] } },
    path: { type: 'string' },
  },
  required: ['lens', 'findings', 'domain_facts', 'path'],
}
const driftPrompt =
  'You are the DRIFT lens. You read the file WITH its comments and docstrings (' + COMMENTED + ') and the '
  + 'CODE is the only source of truth -- a comment, docstring, or name is a CLAIM that is true only if the '
  + 'code confirms it. You produce TWO separate results:\n\n'
  + '(1) DRIFT FINDINGS -- every place a name, comment, or docstring says one thing while the code does '
  + 'another: a docstring promising behavior the code lacks, a comment describing the opposite of the actual '
  + 'condition, a stale parameter doc, a method named for an effect it does not have, a docstring example '
  + 'that would not run, a "returns X" that returns Y. In `defect` quote the claim + what the code does; in '
  + '`fix` say which side to correct. Set angle="drift".\n\n'
  + '(2) DOMAIN FACTS -- valuable knowledge a comment carries that the code ALONE cannot reveal: a domain '
  + 'constraint, a hardware quirk, a real "why", an author rationale. Paraphrase each telegraphically with its '
  + 'source_site and a confidence. NOT defects -- context. Cap to the few that matter; often none. A comment '
  + 'that merely restates the code is NOT a domain fact.\n\n'
  + 'These are deliberately two reads of the same comments: one treats them as suspect claims, the other '
  + 'mines them for irreplaceable context.\n\n'
  + SCALES + CROSSFILE
  + '\nWrite JSON {lens:"drift", findings, domain_facts, path} to ' + FINDINGS + '/drift.json and return it.'

// ---------- LENS 3: test coverage (stripped code + tests) ----------
const coveragePrompt =
  'You are the COVERAGE lens. You read the code (' + STRIPPED + ') and its tests (' + TESTS + ', which may '
  + 'be a NO-TESTS marker). The code is the source of truth. Judge what the tests DO and DO NOT verify.\n\n'
  + 'Hunt for:\n'
  + '- BEHAVIORS NOT EXERCISED: a public method, error path, branch, or edge case (empty / boundary / '
  + 'failure) no test drives. Name the specific untested behavior.\n'
  + '- HOLLOW TESTS: a test that sets up an input but never ASSERTS on its effect (you could change the input '
  + 'and it would still pass), an assertion too loose to fail, a test that only checks "did not raise".\n'
  + '- TESTS THAT BLESS A BUG: a test whose expected value encodes wrong behavior, so the suite is green but '
  + 'the behavior is incorrect. Do not trust a passing test -- re-derive the correct expected result from the '
  + 'code\'s intent and the domain; if the test asserts otherwise, flag it.\n'
  + '- MISSING REGRESSION COVER for any correctness risk visible in the code.\n\n'
  + 'When tests.py is the NO-TESTS marker, do NOT emit one finding per method -- emit a few high-value '
  + 'findings naming the most important UNVERIFIED behaviors (the ones whose breakage hurts most).\n\n'
  + 'For a coverage finding, the `fix` fragment names the test to ADD or EDIT (what to call, what input, '
  + 'what to assert). Set angle="coverage".\n\n'
  + SCALES + CROSSFILE
  + '\nWrite JSON {lens:"coverage", findings, path} to ' + FINDINGS + '/coverage.json and return it.'

// ---------- LENS 4: clarity / craft (stripped code) ----------
const clarityPrompt =
  'You are the CLARITY lens. Read the code (' + STRIPPED + ') and find what makes it harder to read, '
  + 'maintain, or less standard than it should be. This lens is about CRAFT, not correctness.\n\n'
  + 'Hunt for:\n'
  + '- CONFUSING NAMING: an identifier whose name fights its meaning, a generic name doing load-bearing work, '
  + 'two names for one thing, one name for two.\n'
  + '- COULD BE TIGHTER: needless duplication, a loop a comprehension says better, a hand-rolled stdlib call, '
  + 'dead branches, a flag parameter that should be two functions, deep nesting an early return would flatten.\n'
  + '- COULD BE MORE STANDARD / IDIOMATIC: reinventing a stdlib or language feature, a non-pythonic pattern, '
  + 'an unusual structure where a conventional one reads at a glance, inconsistent style within the file.\n'
  + '- HARD TO FOLLOW: a function doing too many things, confusing control flow, a magic number with no name, '
  + 'an implicit coupling a reader would miss.\n\n'
  + 'Be a thoughtful reviewer, not a linter: report what genuinely costs a reader, and give a concrete '
  + 'tighter / clearer / more-standard form in the `fix` fragment. Keep severity honest -- most clarity '
  + 'findings are low or med. Set angle="clarity".\n\n'
  + SCALES + CROSSFILE
  + '\nWrite JSON {lens:"clarity", findings, path} to ' + FINDINGS + '/clarity.json and return it.'

// ---------- SUMMARIZER (independent per-method understanding, code-only) ----------
const SUMMARY_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    module_summary: { type: 'string' },
    symbols: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { qualname: { type: 'string' }, signature: { type: 'string' }, summary: { type: 'string' } },
      required: ['qualname', 'signature', 'summary'] } },
  },
  required: ['module_summary', 'symbols'],
}
const summaryPrompt =
  'You are the SUMMARIZER. Read the code (' + STRIPPED + ') and explain, in plain English, WHAT IT DOES -- '
  + 'independently, from the behavior, so a human can check the findings against a description nobody on the '
  + 'team wrote. The file has no comments; do not guess from names, read the code.\n\n'
  + '- module_summary: a short paragraph -- what this file/class is, what real-world job it does, and when a '
  + 'caller reaches for it.\n'
  + '- symbols: for EVERY top-level class, method, and function, one entry: qualname (e.g. `Buffer.push`), '
  + 'signature, and a 1-3 sentence summary of what it does and the contract a caller relies on (the '
  + 'non-obvious behavior, not a restatement of the name). True to the code.\n\n'
  + CROSSFILE
  + '\nWrite JSON {module_summary, symbols} to ' + RUNDIR + '/summary.json and return it.'

// ---------- MERGER (consolidate -> stable numbered findings + domain facts) ----------
const EVAL_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    findings: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: {
        id: { type: 'integer' },
        angle: { type: 'string', enum: ['trap', 'drift', 'coverage', 'clarity'] },
        symbol: { type: 'string' }, site: { type: 'string' },
        severity: { type: 'string', enum: ['high', 'med', 'low'] },
        effort: { type: 'string', enum: ['small', 'medium', 'large'] },
        confidence: { type: 'string', enum: ['high', 'med', 'low'] },
        defect: { type: 'string' }, bite: { type: 'string' }, fix: { type: 'string' },
      },
      required: ['id', 'angle', 'symbol', 'site', 'severity', 'effort', 'confidence', 'defect', 'bite', 'fix'] } },
    domain_facts: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { fact: { type: 'string' }, source_site: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'med', 'low'] } },
      required: ['fact', 'source_site', 'confidence'] } },
  },
  required: ['findings', 'domain_facts'],
}
function mergePrompt(lensDump, domainFacts, feedback, prior) {
  return 'You are the MERGER. Consolidate findings from four code-evaluation lenses (correctness, drift, '
    + 'coverage, clarity) over ONE file into a single FACT LEDGER. You output telegraphic FRAGMENTS, not '
    + 'reader prose -- a later writer composes the prose from your fragments, so keep them un-pasteable.\n\n'
    + 'RULES:\n'
    + '- DEDUP: when two lenses report the SAME underlying problem, merge into one (keep the sharpest defect, '
    + 'the clearest bite, the most actionable fix, and the higher severity). Do not drop a distinct problem '
    + 'just because it touches the same symbol.\n'
    + '- Keep each finding\'s `angle` (if merged across angles, pick the primary).\n'
    + '- ASSIGN a STABLE integer `id` to every finding, starting at 1, no gaps. This id is the number the '
    + 'human types to apply that fix.\n'
    + '- Keep the THREE fact fragments (defect / bite / fix) telegraphic per the rules below. Do NOT write '
    + 'sentences -- the writer needs fragments, not prose to paste.\n'
    + '- Carry the domain_facts through (dedup them too); they are context, not findings.\n'
    + '- Do not invent findings the lenses did not raise. You consolidate; you do not hunt.\n\n'
    + SCALES + '\n'
    + (feedback
      ? 'A VALIDATOR checked your PREVIOUS ledger against the code and tests and flagged the items below. '
        + 'Produce a CORRECTED ledger: REMOVE every finding listed as NOT-REAL, and for every finding listed '
        + 'as FIX-UNSOUND or OVERSTATED, correct its defect / bite / fix / severity per the note (keeping '
        + 'them fragments). KEEP every other finding UNCHANGED, INCLUDING ITS id (do not renumber survivors). '
        + 'Your previous ledger and the feedback:\n\nPREVIOUS LEDGER:\n' + prior + '\n\nVALIDATOR FEEDBACK:\n' + feedback + '\n\n'
      : '')
    + 'LENS FINDINGS:\n' + lensDump + '\n\n'
    + 'DOMAIN FACTS (from the drift lens):\n' + (domainFacts || '(none)') + '\n\n'
    + 'Write the fact ledger as pretty JSON {findings, domain_facts} to ' + RUNDIR + '/eval.json and return it.'
}

// ---------- VALIDATOR (fixture-agnostic; re-checks each finding + its fix; drives the merger loop) ----------
const VALIDATE_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    findings: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { id: { type: 'integer' }, real: { type: 'boolean' }, fix_sound: { type: 'boolean' }, note: { type: 'string' } },
      required: ['id', 'real', 'fix_sound', 'note'] } },
    any_unreal: { type: 'boolean' }, any_fix_unsound: { type: 'boolean' }, verdict: { type: 'string' },
  },
  required: ['findings', 'any_unreal', 'any_fix_unsound', 'verdict'],
}
const validatePrompt =
  'You validate a FACT LEDGER against the CODE and TESTS. You have NO list of expected problems and no prior '
  + 'knowledge of this file -- reason only from the code (' + STRIPPED + ') and the tests (' + TESTS + '). Do '
  + 'NOT trust that a passing test means the behavior is correct; re-derive from the code.\n\n'
  + 'LEDGER TO CHECK: ' + RUNDIR + '/eval.json -- each finding has a `defect` (what is wrong), a `bite` (the '
  + 'consequence), and a `fix`, all as fragments.\n\n'
  + 'For EACH finding, answer two things:\n'
  + '- real: is the `defect` ACTUALLY TRUE against the code/tests, AND is the `bite` accurate (not '
  + 'overstated -- it must not claim an impact the code cannot produce)? A correctness/drift finding is real '
  + 'only if the code genuinely does what the defect claims. A coverage finding is real only if the tests '
  + 'genuinely do not exercise that behavior. A clarity finding is real if the readability cost is genuine '
  + '(be lenient -- mark real unless the claim is factually false). Mark real=false when it misreads the code '
  + 'or the bite is overstated.\n'
  + '- fix_sound: would the `fix` actually fix the defect WITHOUT breaking behavior or being factually '
  + 'wrong? Mark fix_sound=false for a fix that introduces a bug, misses a case, or mischaracterizes the '
  + 'change. Put the correction in `note`.\n'
  + 'Record a short `note` for every finding. Set any_unreal if any has real=false; any_fix_unsound if any '
  + 'has fix_sound=false.\n\n'
  + 'Write JSON {findings, any_unreal, any_fix_unsound, verdict} to ' + RUNDIR + '/validation.json. After '
  + 'writing, reply DONE.'
function buildFeedback(v) {
  const lines = []
  for (const f of (v.findings || [])) {
    if (!f.real) lines.push('- NOT-REAL id=' + f.id + ': ' + f.note)
    else if (!f.fix_sound) lines.push('- FIX-UNSOUND id=' + f.id + ': ' + f.note)
  }
  return lines.join('\n')
}

// ---------- PATCHER (apply-ready before/after per finding; reads the REAL file) ----------
const PATCH_OUT = {
  type: 'object', additionalProperties: false,
  properties: { patches: { type: 'array', items: { type: 'object', additionalProperties: false,
    properties: {
      id: { type: 'integer' },
      kind: { type: 'string', enum: ['replace', 'add', 'manual'] },
      before: { type: 'string' }, after: { type: 'string' },
      location_hint: { type: 'string' }, note: { type: 'string' },
    },
    required: ['id', 'kind', 'before', 'after', 'location_hint', 'note'] } } },
  required: ['patches'],
}
const patchPrompt =
  'You are the PATCHER. For EACH finding in the fact ledger, produce the concrete code change that fixes its '
  + '`defect` (guided by the `fix` fragment), as an apply-ready before/after. You read the REAL file WITH its '
  + 'comments (' + COMMENTED + ') so your `before` matches it EXACTLY.\n\nLEDGER: ' + RUNDIR + '/eval.json\n'
  + 'FILE: ' + COMMENTED + '\nTESTS: ' + TESTS + '\n\n'
  + 'For each finding id, emit one patch:\n'
  + '- kind "replace": a surgical edit to existing code. `before` = the exact text to replace, copied '
  + 'VERBATIM from the file including indentation and enough surrounding lines to be UNIQUE (a unique anchor). '
  + '`after` = the replacement text. Keep the patch MINIMAL -- only the lines this finding changes.\n'
  + '- kind "add": new code with nothing to replace (a coverage finding that adds a test, a new guard). '
  + '`before` = "", `after` = the code to insert, `location_hint` = where it goes (which file + after what).\n'
  + '- kind "manual": the fix is too structural or ambiguous to express as a single before/after. `before` = '
  + '"", `after` = "", and `note` = clear guidance on what to do by hand.\n'
  + 'Rules: emit EXACTLY ONE patch per finding id, no duplicates, no extra ids. Each patch addresses ONLY '
  + 'its finding. If two findings would touch overlapping lines, still emit '
  + 'each independently against the ORIGINAL text and say so in `note` ("overlaps #N"). For a coverage patch, '
  + '`after` is the actual test function, and it must assert the CORRECT expected behavior (from the '
  + 'finding\'s reasoning), never just whatever the current code returns. Do not change executable code in a '
  + 'clarity-only patch beyond what the finding states.\n\n'
  + 'Write JSON {patches} to ' + RUNDIR + '/patches.json and return it.'

// ---------- WRITER (compose the reader prose FRESH from the fact fragments, in the chosen register) ----------
// Voice is composed here, at write time, from fragments -- never as a rewrite of an already-fluent draft
// (which echoes and flattens). A picked voice REPLACES the plain register; it is not layered on top.
const WRITTEN_OUT = {
  type: 'object', additionalProperties: false,
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false,
    properties: { id: { type: 'integer' }, title: { type: 'string' }, consequence: { type: 'string' }, problem: { type: 'string' }, suggested_fix: { type: 'string' } },
    required: ['id', 'title', 'consequence', 'problem', 'suggested_fix'] } } },
  required: ['findings'],
}
const writerPrompt =
  'You are the WRITER. Compose the reader-facing prose for each finding FRESH, from its fact fragments and '
  + 'the code. Do NOT paste the fragments -- they are notes; you write the prose.\n\n'
  + 'LEDGER (fragments: defect / bite / fix per finding): ' + RUNDIR + '/eval.json\n'
  + 'CODE (for accuracy + the quoted line): ' + STRIPPED + '\n\n'
  + 'REGISTER: read ' + RUNDIR + '/voice_persona.txt. If it is EMPTY, write in a clear, plain, direct '
  + 'register. If it holds a persona ("A [role] who ..."), write FULLY in that voice -- the voice REPLACES '
  + 'the plain register (do not write a plain draft and then flavor it), and it runs free. The ONE floor: '
  + 'the `consequence` must stay understandable in a single read.\n\n'
  + 'For EACH finding id, write four fields:\n'
  + '- title: one short line naming the issue concretely (under ~12 words).\n'
  + '- consequence: the "why it bites" -- a non-author must grasp WHO/WHAT is hurt, WHEN, and how bad in one '
  + 'read. Lead with the stakes; this is the line they act on.\n'
  + '- problem: the SHORT mechanism -- how the code produces it, 1-3 tight sentences, quoting the key line. '
  + 'Not a paragraph.\n'
  + '- suggested_fix: the change, 1-2 sentences.\n'
  + 'Preserve every FACT in the fragments and add no claim they do not make. No em-dashes, no semicolons.\n\n'
  + 'Write JSON {findings:[{id, title, consequence, problem, suggested_fix}]} to ' + RUNDIR
  + '/written.json and return it.'

// ---------- run ----------
phase('Read')
const reads = await parallel([
  () => agent(summaryPrompt, { label: 'summarizer', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: SUMMARY_OUT }).then((r) => ({ kind: 'summary', r })),
  () => agent(trapPrompt, { label: 'lens:trap', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: LENS_OUT }).then((r) => ({ kind: 'lens', r })),
  () => agent(driftPrompt, { label: 'lens:drift', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: DRIFT_OUT }).then((r) => ({ kind: 'drift', r })),
  () => agent(coveragePrompt, { label: 'lens:coverage', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: LENS_OUT }).then((r) => ({ kind: 'lens', r })),
  () => agent(clarityPrompt, { label: 'lens:clarity', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: LENS_OUT }).then((r) => ({ kind: 'lens', r })),
]).then((xs) => xs.filter(Boolean))

const drift = (reads.find((x) => x.kind === 'drift') || {}).r || { findings: [], domain_facts: [] }
const lensResults = reads.filter((x) => x.kind === 'lens').map((x) => x.r).concat([{ lens: 'drift', findings: drift.findings }])
const allFindings = lensResults.flatMap((r) => (r.findings || []).map((f) => ({ ...f, _lens: r.lens })))
const domainFacts = drift.domain_facts || []
log('lenses done: ' + allFindings.length + ' raw findings (' + lensResults.map((r) => r.lens + ':' + (r.findings || []).length).join(', ') + '), ' + domainFacts.length + ' domain facts')

const lensDump = allFindings.map((f) =>
  '- [' + f.angle + '/' + f.severity + '/' + f.effort + '/conf:' + f.confidence + '] (' + f.symbol + ' @ ' + f.site + ')'
  + '\n    defect: ' + f.defect + '\n    bite: ' + f.bite + '\n    fix: ' + f.fix
).join('\n')
const domainDump = domainFacts.map((d) => '- [' + d.confidence + '] ' + d.fact + ' (' + d.source_site + ')').join('\n')

phase('Merge')
let evalResult = await agent(mergePrompt(lensDump, domainDump), { label: 'merger', phase: 'Merge', model: 'opus', agentType: 'general-purpose', schema: EVAL_OUT })

phase('Validate')
const MAX_ATTEMPTS = 4
let validation = await agent(validatePrompt, { label: 'validate', phase: 'Validate', model: 'opus', agentType: 'general-purpose', schema: VALIDATE_OUT })
let attempt = 1
while ((validation.any_unreal || validation.any_fix_unsound) && attempt < MAX_ATTEMPTS) {
  log('validator flagged issues (attempt ' + attempt + '/' + MAX_ATTEMPTS + '); re-running merger with feedback')
  const prior = JSON.stringify(evalResult.findings, null, 1)
  evalResult = await agent(mergePrompt(lensDump, domainDump, buildFeedback(validation), prior), { label: 'merger:retry' + attempt, phase: 'Merge', model: 'opus', agentType: 'general-purpose', schema: EVAL_OUT })
  validation = await agent(validatePrompt, { label: 'validate:retry' + attempt, phase: 'Validate', model: 'opus', agentType: 'general-purpose', schema: VALIDATE_OUT })
  attempt++
}
const converged = !(validation.any_unreal || validation.any_fix_unsound)
log(converged ? 'eval validated clean after ' + attempt + ' attempt(s): ' + (evalResult.findings || []).length + ' findings'
  : 'eval still flagged after ' + attempt + ' attempts; the report will mark the unconfirmed findings')

// Compose: the WRITER composes the reader prose from the validated fragments in the chosen register, and the
// PATCHER emits an apply-ready before/after per finding. Both read the converged eval.json and are
// independent (the writer composes prose by id, the patcher reads code by id), so they run in parallel.
phase('Compose')
const comp = (await parallel([
  () => agent(writerPrompt, { label: 'writer', phase: 'Compose', model: 'opus', agentType: 'general-purpose', schema: WRITTEN_OUT }).then((r) => ({ kind: 'written', r })),
  () => agent(patchPrompt, { label: 'patcher', phase: 'Compose', model: 'opus', agentType: 'general-purpose', schema: PATCH_OUT }).then((r) => ({ kind: 'patch', r })),
])).filter(Boolean)
const written = (comp.find((x) => x.kind === 'written') || {}).r || { findings: [] }
const patches = (comp.find((x) => x.kind === 'patch') || {}).r || { patches: [] }
log('compose: ' + (written.findings || []).length + ' written findings, ' + (patches.patches || []).length + ' patches')

return { findings: evalResult.findings, domain_facts: evalResult.domain_facts, converged, attempts: attempt, n_written: (written.findings || []).length, n_patches: (patches.patches || []).length }
