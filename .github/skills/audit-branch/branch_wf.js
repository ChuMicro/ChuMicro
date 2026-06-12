// audit-branch EVALUATION workflow. Run inside ONE `claude -p` from the run room (clean: no project
// CLAUDE.md by cwd-ancestry, file access bounded to the room). It deeply evaluates ONE change-set —
// a branch, revision range, or staged/working-tree diff — from six angles, produces a patch for
// every finding, and (optionally) voices the prose.
//
// Inputs in the room (branch_phase1.py places them):
//   diff.patch            the unified diff vs the merge base -- every lens's scoping map.
//   manifest.json         mode, refs, and the changed-file list.
//   head/<path>           changed files, head side, WITH comments -- the intent/craft lenses and the
//                         patcher read these (the patcher's before-snippets must match them exactly).
//   head_stripped/<path>  comment-stripped head side -- the code lenses judge from THESE, so a stale
//                         or persuasive comment cannot anchor them into the wrong reading.
//   base_stripped/<path>  comment-stripped base side -- what the integration lens diffs contracts against.
//   usages/<path> + usage_map.json   comment-stripped files that reference the changed symbols, and the
//                         map of which name each references (plus what was dropped over the staging cap).
//   changed_symbols.json  per-file qualnames the diff touches, plus removed: top-level names (mechanical).
//   tests.py              the changed modules' located tests, concatenated (or a NO-TESTS marker).
//   intent.txt            the branch's commit messages + any user-stated intent -- the intent record.
//   FEATURE_FACTS.md      optional pre-change context (feature / contracts / glossary) from phase 0.
//   voice_persona.txt     the chosen voice persona (empty for plain); the writer reads it.
//
// Shape: a summarizer + SIX lenses run in parallel; a merger consolidates every finding into a
// telegraphic FACT LEDGER (defect / bite / fix as un-pasteable FRAGMENTS, never finished sentences)
// and assigns a STABLE integer id (the apply-by-number); a fixture-agnostic validator re-checks every
// finding + fix and drives a merger re-run loop until clean or the cap. Then, in parallel, a WRITER
// composes the reader prose fresh from the fragments in the chosen register and a PATCHER emits an
// apply-ready before/after per finding, each naming the file it edits. The orchestrator substitutes
// __RUNDIR__.

export const meta = {
  name: 'audit-branch-eval',
  description: 'Evaluate one change-set from six angles, validate the facts, then write the prose in voice and patch every finding.',
  phases: [
    { title: 'Read', detail: 'summarizer + 6 lenses (trap / integration / usage / intent / coverage / craft)' },
    { title: 'Merge', detail: 'consolidate into a fact ledger, assign stable fix numbers' },
    { title: 'Validate', detail: 'fixture-agnostic re-check of every finding + fix; merger re-run loop' },
    { title: 'Compose', detail: 'writer composes the prose in voice + patcher patches every finding' },
  ],
}

const RUNDIR = '__RUNDIR__'
const DIFF = RUNDIR + '/diff.patch'
const MANIFEST = RUNDIR + '/manifest.json'
const HEAD = RUNDIR + '/head'
const HEAD_STRIPPED = RUNDIR + '/head_stripped'
const BASE_STRIPPED = RUNDIR + '/base_stripped'
const USAGES = RUNDIR + '/usages'
const USAGE_MAP = RUNDIR + '/usage_map.json'
const SYMBOLS = RUNDIR + '/changed_symbols.json'
const TESTS = RUNDIR + '/tests.py'
const INTENT = RUNDIR + '/intent.txt'
const FINDINGS = RUNDIR + '/findings'

// ---------- shared scales + the fact-fragment finding shape ----------
// Lenses and the merger emit FRAGMENTS, not sentences. A later writer composes the reader prose; if
// it is handed a fluent sentence it pastes yours and the writing goes flat. So every finding carries
// three telegraphic fact fragments -- defect / bite / fix -- with no grammar to paste.
const SCALES =
  'For each finding, record THREE telegraphic FACT FRAGMENTS -- never finished sentences. A later writer '
  + 'composes the reader prose; hand it a fluent sentence and it pastes yours and the writing goes flat. Use '
  + 'arrows (->), colons, shorthand -- no grammar to paste:\n'
  + '- defect: WHAT is wrong (e.g. `retry() re-opens the socket without closing the old one; old fd leaks`).\n'
  + '- bite: the CONSEQUENCE -- who/what is hurt, WHEN, how bad (e.g. `every reconnect leaks one fd -> '
  + 'long-lived device exhausts fds after ~hours -> all I/O fails with no clear error`).\n'
  + '- fix: the change (e.g. `close the old socket before reopening in retry()`).\n'
  + 'Keep them precise but un-pasteable. Score three scales: severity (high = correctness bug / breaks a '
  + 'caller / silently wrong / data loss; med = real hazard or likely-misuse; low = polish), effort '
  + '(small / medium / large), confidence (high / med / low -- a guess is low, do not inflate).\n'
  + 'LOCATING A FINDING: set `file` to the repo-relative path the fix would EDIT (a changed file, or a '
  + 'caller file for a usage finding), `symbol` to the enclosing qualname (e.g. `Buffer.push`, or '
  + '`<module>`), and `site` to a SHORT QUOTE of the exact code line(s). Stripped copies do not keep the '
  + 'real line numbers -- the file + symbol + quoted code is what locates it.\n'

// What deterministic gates already cover. This repo runs a preflight (ruff lint, the pytest suite,
// coverage thresholds) on every commit, so re-flagging its lanes only adds noise -- the lenses hunt
// what automated checks CANNOT detect.
// REPO-SPECIFIC (ChuMicro): the gate NAMES below (ruff / pytest / preflight) are this repo's;
// convert them to the target repo's gates when porting. The concept itself ports as-is.
const CHECKS_AWARE =
  '\nDO NOT flag what this repo\'s deterministic gates already catch: lint/style/formatting/naming/'
  + 'import-order, a test that currently fails, or coverage percentages -- a preflight runs ruff and the '
  + 'whole pytest suite on every commit. Hunt only what no automated check detects: wrong logic, broken '
  + 'contracts, misled callers, hollow tests, misleading prose.\n'

const CONTEXT =
  '\nCONTEXT: if ' + RUNDIR + '/FEATURE_FACTS.md exists, consult it to interpret the surrounding '
  + 'packages, shared types, and domain terms -- but judge only this change-set. Do not report a '
  + 'pre-existing defect in UNCHANGED code as if the branch introduced it; pre-existing problems the '
  + 'change makes WORSE or newly reachable do count.\n'

const FINDING = {
  type: 'object', additionalProperties: false,
  properties: {
    angle: { type: 'string', enum: ['trap', 'integration', 'usage', 'intent', 'coverage', 'craft'] },
    file: { type: 'string' },
    symbol: { type: 'string' },
    site: { type: 'string' },
    severity: { type: 'string', enum: ['high', 'med', 'low'] },
    effort: { type: 'string', enum: ['small', 'medium', 'large'] },
    confidence: { type: 'string', enum: ['high', 'med', 'low'] },
    defect: { type: 'string' },
    bite: { type: 'string' },
    fix: { type: 'string' },
  },
  required: ['angle', 'file', 'symbol', 'site', 'severity', 'effort', 'confidence', 'defect', 'bite', 'fix'],
}
const LENS_OUT = {
  type: 'object', additionalProperties: false,
  properties: { lens: { type: 'string' }, findings: { type: 'array', items: FINDING }, path: { type: 'string' } },
  required: ['lens', 'findings', 'path'],
}

// ---------- LENS 1: trap / correctness of the changed code (stripped head) ----------
const trapPrompt =
  'You are the TRAP lens on a change-set. Read the changed code and find where the CHANGE makes behavior '
  + 'wrong -- or could. The files under ' + HEAD_STRIPPED + ' are the changed files at head, with NO '
  + 'comments: the code is the only source of truth. ' + SYMBOLS + ' lists which symbols the diff '
  + 'touched and ' + DIFF + ' is the diff itself -- use them to scope, but judge with the WHOLE file in '
  + 'view (a one-line change can break an invariant three methods away).\n\n'
  + 'Hunt specifically for:\n'
  + '- INVERSIONS / BOUNDARY: a flipped guard, `<=` vs `<`, an off-by-one the edit introduced or moved.\n'
  + '- MIS-REFERENT / cross-method: a changed value whose meaning depends on WHICH branch produced it; '
  + 'trace it across methods and state what it really refers to now.\n'
  + '- SWALLOWED errors, a resource opened but no longer closed on some path, state assumed persisted '
  + 'that no longer is, a side effect the edit added or dropped.\n'
  + '- HOSTILE-INPUT / TIMING hazards the change creates: an allocation sized by a peer-controlled field '
  + 'with no cap, untrusted data newly reaching exec/subprocess/a path/a query, a check-then-act gap, '
  + 'state a re-entered call observes half-updated.\n'
  + '- RUN IT IN YOUR HEAD: drive the changed code with representative inputs INCLUDING edges (empty, '
  + 'zero, negative, the max, the exact boundary, None, a duplicate, a wrap-around) and simulate by '
  + 'hand. Put a concrete trace (inputs -> what the code computes -> why wrong) in `defect`.\n\n'
  + 'Report ONLY genuine behavior problems or real latent risks the change introduces or worsens. Set '
  + 'angle="trap".\n\n'
  + SCALES + CHECKS_AWARE + CONTEXT
  + '\nWrite JSON {lens:"trap", findings, path} to ' + FINDINGS + '/trap.json and return it.'

// ---------- LENS 2: integration / contract compatibility (stripped base vs head) ----------
// Adapted from a Kotlin binary/behavioral/source-compatibility review skill: the three classes of
// break carry over to Python as call, behavior, and contract-evolution compatibility.
const integrationPrompt =
  'You are the INTEGRATION lens on a change-set. Compare each changed file\'s PUBLIC surface (no '
  + 'leading underscore) before and after: base side under ' + BASE_STRIPPED + ', head side under '
  + HEAD_STRIPPED + ', the diff at ' + DIFF + ', removed names in ' + SYMBOLS + ', the changed-file '
  + 'list in ' + MANIFEST + '. Both sides are comment-stripped; judge contracts from code.\n\n'
  + 'Three compatibility classes -- check each public change against all three:\n'
  + '- CALL COMPATIBILITY: an existing call written against the base signature fails at head. Removed '
  + 'or renamed public symbol; a parameter added without a default; parameters reordered (positional '
  + 'callers silently bind wrong); a renamed keyword; a default-bearing parameter inserted before '
  + 'existing ones.\n'
  + '- BEHAVIOR COMPATIBILITY: the signature survives but the semantics moved. A changed default value; '
  + 'a different return shape or element order; a new exception type raised where callers catch the old '
  + 'one; an enum/constant value change; a dataclass/tuple field reorder that breaks destructuring; a '
  + 'method that used to be safe to call twice and no longer is.\n'
  + '- CONTRACT EVOLUTION: a return type narrowed or widened against what callers can rely on; an '
  + 'invariant the base code maintained (sorted output, non-None field, closed handle) the head code '
  + 'drops.\n\n'
  // REPO-SPECIFIC (ChuMicro): the VERSION-bump rule below is this repo's release policy — delete
  // or convert this paragraph when porting (e.g. a Kotlin repo's version-catalog / API-dump check).
  + 'Also check the VERSION contract: this repo requires a VERSION bump in the same change-set for any '
  + 'public-API or behavior change to a library. ' + MANIFEST + ' lists every changed file -- if a '
  + 'library\'s public surface changed and no VERSION file under that library changed with it, flag it '
  + '(file = the library\'s VERSION path, severity med, effort small).\n\n'
  + 'A break the change-set itself migrates is NOT a finding when every staged caller was updated in '
  + 'the same diff -- cross-check ' + USAGE_MAP + ' and say so in `defect` if partially migrated. Set '
  + 'angle="integration".\n\n'
  + SCALES + CHECKS_AWARE + CONTEXT
  + '\nWrite JSON {lens:"integration", findings, path} to ' + FINDINGS + '/integration.json and return it.'

// ---------- LENS 3: usage / every traced call site (stripped callers + head) ----------
const usagePrompt =
  'You are the USAGE lens on a change-set. ' + USAGE_MAP + ' maps each changed symbol to the repo files '
  + 'that reference it; those files are staged (comment-stripped) under ' + USAGES + '. The changed code '
  + 'at head is under ' + HEAD_STRIPPED + ' and the touched symbols are listed in ' + SYMBOLS + '.\n\n'
  + 'For EVERY staged caller of EVERY changed symbol, judge whether the call still holds at head:\n'
  + '- an assumption the caller makes (return shape, ordering, units, sentinel values, when None) the '
  + 'change broke,\n'
  + '- an exception the head code newly raises on a path the caller does not handle,\n'
  + '- a default the caller relied on that changed out from under it,\n'
  + '- a call sequence (open-then-use, check-then-act) whose contract the change reordered,\n'
  + '- a removed or renamed name the caller still references.\n\n'
  + 'Set `file` to the file the FIX would edit -- usually the caller; the changed file when the right '
  + 'fix is reverting/adjusting the change instead of touching every caller. Judge ONLY what you can '
  + 'read: usage_map.json names files dropped over the staging cap -- do not guess about them (the '
  + 'orchestrator surfaces the cap separately). Set angle="usage".\n\n'
  + SCALES + CHECKS_AWARE + CONTEXT
  + '\nWrite JSON {lens:"usage", findings, path} to ' + FINDINGS + '/usage.json and return it.'

// ---------- LENS 4: intent / alignment with the stated purpose (commented head + diff + intent) ----------
// The intent record is a CLAIM, exactly as comments are to a drift lens: true only if the diff
// confirms it. The two-gate policy below is adapted from a production PR-review bot: it suppresses
// the noisy "doesn't match the ticket" class while keeping real drift loud.
const INTENT_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    lens: { type: 'string' },
    findings: { type: 'array', items: FINDING },
    intent_facts: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { fact: { type: 'string' }, source_site: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'med', 'low'] } },
      required: ['fact', 'source_site', 'confidence'] } },
    path: { type: 'string' },
  },
  required: ['lens', 'findings', 'intent_facts', 'path'],
}
const intentPrompt =
  'You are the INTENT lens on a change-set. You read the intent record (' + INTENT + ': the branch\'s '
  + 'commit messages plus any user-stated intent), the diff (' + DIFF + '), and the changed files WITH '
  + 'their comments under ' + HEAD + '. The DIFF is the only source of truth about what the change-set '
  + 'does; the intent record is a set of CLAIMS.\n\n'
  + 'You produce TWO separate results:\n\n'
  + '(1) INTENT FINDINGS -- apply BOTH gates before flagging scope/alignment drift:\n'
  + '    Gate 1: the diff demonstrably diverges from the stated intent (does less, does more, or does '
  + 'something different).\n'
  + '    Gate 2: the intent record does NOT acknowledge the deviation. A note like "only handling X '
  + 'here, Y in a follow-up" or "switched from approach A to B because ..." counts as acknowledgement '
  + 'and SUPPRESSES the finding. Narrowing, expanding, or re-approaching that the author states is '
  + 'accepted scope, not drift.\n'
  + '    Past the gates, also hunt:\n'
  + '    - ROOT CAUSE vs SYMPTOM: when the intent claims a bug fix, re-derive the bug\'s mechanism from '
  + 'the code and judge whether the change removes the CAUSE or masks the symptom (a guard above an '
  + 'unfixed corruption, a retry around a race). Masking is a finding -- name the actual mechanism in '
  + '`defect`.\n'
  + '    - UNRELATED RIDERS: a hunk serving no stated purpose of the change-set (a drive-by refactor, '
  + 'an unrelated behavior change riding along unannounced).\n'
  + '    - A commit message that misdescribes its own diff (claims X, diff does Y).\n'
  + '    Set angle="intent".\n\n'
  + '(2) INTENT FACTS -- the claims worth showing the reviewer: what the change-set says it does, why, '
  + 'and any stated follow-ups or known gaps. Telegraphic, each with source_site (which commit) and '
  + 'confidence. Context, not defects.\n\n'
  + SCALES + CHECKS_AWARE + CONTEXT
  + '\nWrite JSON {lens:"intent", findings, intent_facts, path} to ' + FINDINGS + '/intent.json and return it.'

// ---------- LENS 5: coverage of the NEW behavior (stripped head + tests + diff) ----------
const coveragePrompt =
  'You are the COVERAGE lens on a change-set. You read the changed code (' + HEAD_STRIPPED + '), the '
  + 'diff (' + DIFF + '), and the changed modules\' tests (' + TESTS + ', which may be a NO-TESTS '
  + 'marker). Judge ONLY the coverage of what the change-set ADDS or ALTERS -- pre-existing gaps in '
  + 'untouched behavior are out of scope (a whole-file audit owns those).\n\n'
  + 'Hunt for:\n'
  + '- NEW BEHAVIOR NO TEST EXERCISES: a branch, error path, or edge case the diff introduces that no '
  + 'test drives.\n'
  + '- CHANGED BEHAVIOR NO TEST PINS: the diff alters what a function returns or raises and no test '
  + 'would fail if the alteration regressed -- the change can silently un-happen.\n'
  + '- TESTS THAT BLESS THE OLD BEHAVIOR: a test asserting the pre-change result that was updated to '
  + 'pass (or deleted) without the expectation being re-derived -- green suite, unverified change.\n'
  + '- HOLLOW NEW TESTS: a test added by the change-set that asserts nothing that would fail.\n\n'
  + 'For a coverage finding, the `fix` fragment names the test to ADD or EDIT (what to call, what '
  + 'input, what to assert) and asserts the CORRECT expected behavior re-derived from the code\'s '
  + 'intent, never just what the current code returns. Set `file` to the test file to edit (or the '
  + 'changed module\'s natural test path when none exists). Set angle="coverage".\n\n'
  + SCALES + CHECKS_AWARE + CONTEXT
  + '\nWrite JSON {lens:"coverage", findings, path} to ' + FINDINGS + '/coverage.json and return it.'

// ---------- LENS 6: craft of the new code (commented head + diff) ----------
const craftPrompt =
  'You are the CRAFT lens on a change-set. You read the changed files WITH their comments under '
  + HEAD + ' and the diff at ' + DIFF + '. Judge ONLY the regions the diff touches -- this is not a '
  + 'whole-file audit.\n\n'
  + 'Hunt for:\n'
  + '- PROSE THE CHANGE BROKE: a docstring or comment (in the changed file or elsewhere in the diff) '
  + 'that described the OLD behavior and now misleads; a comment the change made stale; a docstring '
  + 'example that would no longer run; a doc file in the diff contradicting the code.\n'
  + '- NEW CODE THAT READS WRONG: a name fighting its meaning, a magic number with no name, control '
  + 'flow an early return would flatten, duplication the change introduces, a non-idiomatic form where '
  + 'a standard one reads at a glance.\n'
  + '- INCONSISTENCY WITH ITS SURROUNDINGS: the new code solves a problem the surrounding file already '
  + 'solves another way (a second timestamp idiom, a hand-rolled version of a helper three lines up).\n\n'
  + 'Be a thoughtful reviewer, not a linter: report what genuinely costs a reader. Keep severity '
  + 'honest -- most craft findings are low or med. Set angle="craft".\n\n'
  + SCALES + CHECKS_AWARE + CONTEXT
  + '\nWrite JSON {lens:"craft", findings, path} to ' + FINDINGS + '/craft.json and return it.'

// ---------- SUMMARIZER (independent what-does-this-change-set-do; intent-blind) ----------
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
  'You are the SUMMARIZER. Read the diff (' + DIFF + '), the base side (' + BASE_STRIPPED + '), and '
  + 'the head side (' + HEAD_STRIPPED + ') and explain, in plain English, WHAT THIS CHANGE-SET '
  + 'ACTUALLY DOES -- independently, from the code delta alone. Do NOT read ' + INTENT + ' -- the human '
  + 'compares your read against the branch\'s own claims, so yours must owe nothing to them.\n\n'
  + '- module_summary: a short paragraph -- what the change-set changes, in behavior terms, and what '
  + 'it means for callers.\n'
  + '- symbols: one entry PER CHANGED FILE: qualname = the repo-relative path, signature = a terse '
  + 'delta marker (e.g. `modified`, `added`, `deleted`, `+2 methods`), summary = 1-3 sentences on what '
  + 'changed in that file and the contract impact. True to the diff.\n\n'
  + CONTEXT
  + '\nWrite JSON {module_summary, symbols} to ' + RUNDIR + '/summary.json and return it.'

// ---------- MERGER (consolidate -> stable numbered findings + intent facts) ----------
const EVAL_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    findings: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: {
        id: { type: 'integer' },
        angle: { type: 'string', enum: ['trap', 'integration', 'usage', 'intent', 'coverage', 'craft'] },
        file: { type: 'string' }, symbol: { type: 'string' }, site: { type: 'string' },
        severity: { type: 'string', enum: ['high', 'med', 'low'] },
        effort: { type: 'string', enum: ['small', 'medium', 'large'] },
        confidence: { type: 'string', enum: ['high', 'med', 'low'] },
        defect: { type: 'string' }, bite: { type: 'string' }, fix: { type: 'string' },
      },
      required: ['id', 'angle', 'file', 'symbol', 'site', 'severity', 'effort', 'confidence', 'defect', 'bite', 'fix'] } },
    domain_facts: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { fact: { type: 'string' }, source_site: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'med', 'low'] } },
      required: ['fact', 'source_site', 'confidence'] } },
  },
  required: ['findings', 'domain_facts'],
}
function mergePrompt(lensDump, intentFacts, feedback, prior) {
  return 'You are the MERGER. Consolidate findings from six change-set lenses (trap, integration, usage, '
    + 'intent, coverage, craft) over ONE change-set into a single FACT LEDGER. You output telegraphic '
    + 'FRAGMENTS, not reader prose -- a later writer composes the prose from your fragments, so keep them '
    + 'un-pasteable.\n\n'
    + 'RULES:\n'
    + '- ACTIONABILITY GATE: every finding must name something to CHANGE. Drop any lens finding that merely '
    + 'validates, praises, or affirms the change, that asks the author to "check" / "verify" / "confirm" '
    + 'something, or that has no file + symbol + quoted site to anchor it -- a finding that cannot be '
    + 'located is a guess, not a finding.\n'
    + '- DEDUP: when two lenses report the SAME underlying problem (an integration break and the usage '
    + 'finding at its call site often are), merge into one -- keep the sharpest defect, the clearest bite, '
    + 'the most actionable fix, and the higher severity. Do not drop a distinct problem just because it '
    + 'touches the same symbol.\n'
    + '- Keep each finding\'s `angle` (if merged across angles, pick the primary) and its `file`.\n'
    + '- ASSIGN a STABLE integer `id` to every finding, starting at 1, no gaps. This id is the number the '
    + 'human types to apply that fix.\n'
    + '- Keep the THREE fact fragments (defect / bite / fix) telegraphic per the rules below. Do NOT write '
    + 'sentences -- the writer needs fragments, not prose to paste.\n'
    + '- Carry the intent facts through as domain_facts (dedup them too); they are context, not findings.\n'
    + '- Do not invent findings the lenses did not raise. You consolidate; you do not hunt.\n\n'
    + SCALES + '\n'
    + (feedback
      ? 'A VALIDATOR checked your PREVIOUS ledger against the code, diff, and tests and flagged the items '
        + 'below. Produce a CORRECTED ledger: REMOVE every finding listed as NOT-REAL, and for every finding '
        + 'listed as FIX-UNSOUND, correct its defect / bite / fix / severity per the note (keeping them '
        + 'fragments). KEEP every other finding UNCHANGED, INCLUDING ITS id (do not renumber survivors). '
        + 'Your previous ledger and the feedback:\n\nPREVIOUS LEDGER:\n' + prior + '\n\nVALIDATOR FEEDBACK:\n' + feedback + '\n\n'
      : '')
    + 'LENS FINDINGS:\n' + lensDump + '\n\n'
    + 'INTENT FACTS (from the intent lens):\n' + (intentFacts || '(none)') + '\n\n'
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
  'You validate a FACT LEDGER against a CHANGE-SET. You have NO list of expected problems and no prior '
  + 'knowledge of this code -- reason only from the diff (' + DIFF + '), the base side (' + BASE_STRIPPED
  + '), the head side (' + HEAD_STRIPPED + '), the staged callers (' + USAGES + ' + ' + USAGE_MAP + '), '
  + 'the tests (' + TESTS + '), and the intent record (' + INTENT + ', for intent findings only). Do NOT '
  + 'trust that a passing test means the behavior is correct; re-derive from the code.\n\n'
  + 'LEDGER TO CHECK: ' + RUNDIR + '/eval.json -- each finding has a `defect`, a `bite`, and a `fix`, all '
  + 'as fragments.\n\n'
  + 'For EACH finding, answer two things:\n'
  + '- real: is the `defect` ACTUALLY TRUE against the diff and code, AND is the `bite` accurate (not '
  + 'overstated)? A trap/integration/usage finding is real only if the code genuinely does what the defect '
  + 'claims at head. An intent finding is real only if BOTH drift gates hold (the diff diverges AND the '
  + 'intent record does not acknowledge it). A coverage finding is real only if no staged test exercises '
  + 'that behavior. A craft finding is real if the readability cost is genuine (be lenient -- mark real '
  + 'unless the claim is factually false). Mark real=false when it misreads the code, flags a pre-existing '
  + 'problem the change did not introduce or worsen, or overstates the bite.\n'
  + '- fix_sound: would the `fix` actually fix the defect WITHOUT breaking behavior or other callers? '
  + 'Mark fix_sound=false for a fix that introduces a bug, misses a case, or mischaracterizes the change. '
  + 'Put the correction in `note`.\n'
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

// ---------- PATCHER (apply-ready before/after per finding; reads the REAL head files) ----------
const PATCH_OUT = {
  type: 'object', additionalProperties: false,
  properties: { patches: { type: 'array', items: { type: 'object', additionalProperties: false,
    properties: {
      id: { type: 'integer' },
      file: { type: 'string' },
      kind: { type: 'string', enum: ['replace', 'add', 'manual'] },
      before: { type: 'string' }, after: { type: 'string' },
      location_hint: { type: 'string' }, note: { type: 'string' },
      repro: { type: 'string' },
    },
    required: ['id', 'file', 'kind', 'before', 'after', 'location_hint', 'note', 'repro'] } } },
  required: ['patches'],
}
const patchPrompt =
  'You are the PATCHER. For EACH finding in the fact ledger, produce the concrete code change that fixes '
  + 'its `defect` (guided by the `fix` fragment), as an apply-ready before/after. The REAL changed files '
  + 'WITH their comments are under ' + HEAD + ' -- your `before` must match the named file EXACTLY. A '
  + 'usage finding\'s file may be a caller staged only as a stripped copy under ' + USAGES + '; for those, '
  + 'emit kind "manual" with precise guidance (the orchestrator edits the real caller in-session) unless '
  + 'the change is a pure addition.\n\nLEDGER: ' + RUNDIR + '/eval.json\nFILES: ' + HEAD + '\nTESTS: '
  + TESTS + '\n\n'
  + 'For each finding id, emit one patch with `file` = the finding\'s repo-relative file:\n'
  + '- kind "replace": a surgical edit to existing code. `before` = the exact text to replace, copied '
  + 'VERBATIM from the file including indentation and enough surrounding lines to be UNIQUE. `after` = '
  + 'the replacement. Keep the patch MINIMAL -- only the lines this finding changes. A structural rewrite '
  + 'confined to ONE contiguous region is still "replace".\n'
  + '- kind "add": new code with nothing to replace (a coverage finding\'s test, a new guard). '
  + '`before` = "", `after` = the code to insert, `location_hint` = where it goes (which file + after what).\n'
  + '- kind "manual": ONLY when the change spans multiple disjoint regions, lives in a file staged only '
  + 'as a stripped copy, or genuinely needs a human judgment call -- never merely because the edit is '
  + 'large. `before` = "", `after` = "", and `note` = clear guidance naming each region it touches.\n'
  + '- repro: for a trap, usage, or integration finding whose defect a RUNNABLE test can demonstrate, also '
  + 'fill `repro` with a MINIMAL self-contained pytest file body -- imports included, importing the module '
  + 'under test by its real import path derived from the finding\'s repo-relative `file` (src-layout: the '
  + 'dotted path after `src/`) -- that FAILS at head and PASSES once the fix is applied. The orchestrator '
  + 'runs it in-session before the edit (red demonstrates the defect) and after (green proves the fix). No '
  + 'fixtures beyond stdlib + the package under test. Set repro to "" for every other finding (a coverage '
  + 'finding is already a test; intent and craft have nothing to execute).\n'
  + 'Rules: emit EXACTLY ONE patch per finding id, no duplicates, no extra ids. Each patch addresses ONLY '
  + 'its finding. If two findings would touch overlapping lines, emit each independently against the '
  + 'ORIGINAL text and say so in `note` ("overlaps #N"). For a coverage patch, `after` is the actual test '
  + 'function asserting the CORRECT expected behavior (from the finding\'s reasoning), never just whatever '
  + 'the current code returns.\n\n'
  + 'Write JSON {patches} to ' + RUNDIR + '/patches.json and return it.'

// ---------- WRITER (compose the reader prose FRESH from the fact fragments, in the chosen register) ----------
// Voice is composed here, at write time, from fragments -- never as a rewrite of an already-fluent
// draft (which echoes and flattens). A picked voice REPLACES the plain register.
const WRITTEN_OUT = {
  type: 'object', additionalProperties: false,
  properties: { findings: { type: 'array', items: { type: 'object', additionalProperties: false,
    properties: { id: { type: 'integer' }, title: { type: 'string' }, consequence: { type: 'string' }, problem: { type: 'string' }, suggested_fix: { type: 'string' } },
    required: ['id', 'title', 'consequence', 'problem', 'suggested_fix'] } } },
  required: ['findings'],
}
const writerPrompt =
  'You are the WRITER. Compose the reader-facing prose for each finding FRESH, from its fact fragments '
  + 'and the code. Do NOT paste the fragments -- they are notes; you write the prose.\n\n'
  + 'LEDGER (fragments: defect / bite / fix per finding): ' + RUNDIR + '/eval.json\n'
  + 'CODE (for accuracy + the quoted line): ' + HEAD_STRIPPED + '\n\n'
  + 'REGISTER: read ' + RUNDIR + '/voice_persona.txt. If it is EMPTY, write in a clear, plain, direct '
  + 'register. If it holds a persona ("A [role] who ..."), write FULLY in that voice -- the voice REPLACES '
  + 'the plain register (do not write a plain draft and then flavor it), and it runs free. The ONE floor: '
  + 'the `consequence` must stay understandable in a single read.\n\n'
  + 'For EACH finding id, write four fields:\n'
  + '- title: one short line naming the issue concretely (under ~12 words).\n'
  + '- consequence: the "why it bites" -- a non-author must grasp WHO/WHAT is hurt, WHEN, and how bad in '
  + 'one read. Lead with the stakes; this is the line they act on.\n'
  + '- problem: the SHORT mechanism -- how the change produces it, 1-3 tight sentences, quoting the key '
  + 'line. Not a paragraph.\n'
  + '- suggested_fix: the change, 1-2 sentences.\n'
  + 'Preserve every FACT in the fragments and add no claim they do not make. No em-dashes, no semicolons.\n\n'
  + 'Write JSON {findings:[{id, title, consequence, problem, suggested_fix}]} to ' + RUNDIR
  + '/written.json and return it.'

// ---------- run ----------
phase('Read')
const reads = await parallel([
  () => agent(summaryPrompt, { label: 'summarizer', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: SUMMARY_OUT }).then((r) => ({ kind: 'summary', r })),
  () => agent(trapPrompt, { label: 'lens:trap', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: LENS_OUT }).then((r) => ({ kind: 'lens', r })),
  () => agent(integrationPrompt, { label: 'lens:integration', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: LENS_OUT }).then((r) => ({ kind: 'lens', r })),
  () => agent(usagePrompt, { label: 'lens:usage', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: LENS_OUT }).then((r) => ({ kind: 'lens', r })),
  () => agent(intentPrompt, { label: 'lens:intent', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: INTENT_OUT }).then((r) => ({ kind: 'intent', r })),
  () => agent(coveragePrompt, { label: 'lens:coverage', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: LENS_OUT }).then((r) => ({ kind: 'lens', r })),
  () => agent(craftPrompt, { label: 'lens:craft', phase: 'Read', model: 'opus', agentType: 'general-purpose', schema: LENS_OUT }).then((r) => ({ kind: 'lens', r })),
]).then((xs) => xs.filter(Boolean))

const intent = (reads.find((x) => x.kind === 'intent') || {}).r || { findings: [], intent_facts: [] }
const lensResults = reads.filter((x) => x.kind === 'lens').map((x) => x.r).concat([{ lens: 'intent', findings: intent.findings }])
const allFindings = lensResults.flatMap((r) => (r.findings || []).map((f) => ({ ...f, _lens: r.lens })))
const intentFacts = intent.intent_facts || []
log('lenses done: ' + allFindings.length + ' raw findings (' + lensResults.map((r) => r.lens + ':' + (r.findings || []).length).join(', ') + '), ' + intentFacts.length + ' intent facts')

const lensDump = allFindings.map((f) =>
  '- [' + f.angle + '/' + f.severity + '/' + f.effort + '/conf:' + f.confidence + '] (' + f.file + ' :: ' + f.symbol + ' @ ' + f.site + ')'
  + '\n    defect: ' + f.defect + '\n    bite: ' + f.bite + '\n    fix: ' + f.fix
).join('\n')
const intentDump = intentFacts.map((d) => '- [' + d.confidence + '] ' + d.fact + ' (' + d.source_site + ')').join('\n')

phase('Merge')
let evalResult = await agent(mergePrompt(lensDump, intentDump), { label: 'merger', phase: 'Merge', model: 'opus', agentType: 'general-purpose', schema: EVAL_OUT })

phase('Validate')
const MAX_ATTEMPTS = 4
let validation = await agent(validatePrompt, { label: 'validate', phase: 'Validate', model: 'opus', agentType: 'general-purpose', schema: VALIDATE_OUT })
let attempt = 1
while ((validation.any_unreal || validation.any_fix_unsound) && attempt < MAX_ATTEMPTS) {
  log('validator flagged issues (attempt ' + attempt + '/' + MAX_ATTEMPTS + '); re-running merger with feedback')
  const prior = JSON.stringify(evalResult.findings, null, 1)
  evalResult = await agent(mergePrompt(lensDump, intentDump, buildFeedback(validation), prior), { label: 'merger:retry' + attempt, phase: 'Merge', model: 'opus', agentType: 'general-purpose', schema: EVAL_OUT })
  validation = await agent(validatePrompt, { label: 'validate:retry' + attempt, phase: 'Validate', model: 'opus', agentType: 'general-purpose', schema: VALIDATE_OUT })
  attempt++
}
const converged = !(validation.any_unreal || validation.any_fix_unsound)
log(converged ? 'eval validated clean after ' + attempt + ' attempt(s): ' + (evalResult.findings || []).length + ' findings'
  : 'eval still flagged after ' + attempt + ' attempts; the report will mark the unconfirmed findings')

// Compose: the WRITER composes the reader prose from the validated fragments in the chosen register,
// and the PATCHER emits an apply-ready before/after per finding. Independent by id, so they run in
// parallel.
phase('Compose')
const comp = (await parallel([
  () => agent(writerPrompt, { label: 'writer', phase: 'Compose', model: 'opus', agentType: 'general-purpose', schema: WRITTEN_OUT }).then((r) => ({ kind: 'written', r })),
  () => agent(patchPrompt, { label: 'patcher', phase: 'Compose', model: 'opus', agentType: 'general-purpose', schema: PATCH_OUT }).then((r) => ({ kind: 'patch', r })),
])).filter(Boolean)
const written = (comp.find((x) => x.kind === 'written') || {}).r || { findings: [] }
const patches = (comp.find((x) => x.kind === 'patch') || {}).r || { patches: [] }
log('compose: ' + (written.findings || []).length + ' written findings, ' + (patches.patches || []).length + ' patches')

return { findings: evalResult.findings, domain_facts: evalResult.domain_facts, converged, attempts: attempt, n_written: (written.findings || []).length, n_patches: (patches.patches || []).length }
