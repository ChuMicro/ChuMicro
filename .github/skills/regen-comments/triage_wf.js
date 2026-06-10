// regen-comments TRIAGE workflow. Run inside ONE `claude -p` from the run room. 3 code lenses read the
// stripped code; the comment lens reads the raw commented file and routes every comment to
// ledger/preserve/discard; the ledger-writer merges the code findings + the comment LEDGER-lane facts
// into ONE telegraphic, non-copyable ledger with per-fact confidence. A fixture-agnostic validator then
// checks every fact against the code; if any is wrong or a correctness-critical fact is ambiguous, the
// ledger-writer re-runs against the validator's notes (writer-only retry, up to MAX_LEDGER_ATTEMPTS) and
// re-validates. Writes <RUNDIR>/ledger_provisional.md + <RUNDIR>/ledger.json + <RUNDIR>/validation.json +
// <RUNDIR>/findings/*.json. validation.json's any_wrong/any_underspecified after the loop tell the
// orchestrator whether to escalate to the human. The orchestrator runs the picker on the low/med +
// comment-derived facts before the writer phase. Orchestrator substitutes __RUNDIR__.

export const meta = {
  name: 'regen-triage',
  description: 'Full triage: 3 code lenses + comment lens -> ledger-writer. Produces the provisional ledger + preserve lane.',
  phases: [
    { title: 'Lenses', detail: '3 code lenses (stripped) + 1 comment lens (raw)' },
    { title: 'Ledger', detail: 'merge -> telegraphic ledger w/ confidence' },
    { title: 'Validate', detail: 'fixture-agnostic gate + ledger-writer re-run loop' },
  ],
}

const RUNDIR = '__RUNDIR__'
const STRIPPED = RUNDIR + '/stripped.py'
const COMMENTED = RUNDIR + '/commented.py'
const EXP = RUNDIR
// GENRE selects the triage aim: 'code' (default) runs the 3 trap lenses + ledger-writer + validator loop
// below; 'test' / 'functional_test' / 'example' run the lighter genre triage (genreLedgerPrompt) instead.
const GENRE = '__GENRE__'

// ---------- 3 CODE LENSES (fragment-preamble triage prompts) ----------
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
  + 'or term means, what contract this file implements or uses). DEFER to it: do NOT re-surface a fact the '
  + 'library ledger already states. Record only facts SPECIFIC to this file, or this file\'s specific '
  + 'APPLICATION of a library contract. The per-file CODE remains the source of truth for THIS file. Do not '
  + 'import other files\' internal facts.\n\n'
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
    + 'misleading about WHICH thing it acts on. ALWAYS evaluate the top-level CLASS and MODULE name too, not '
    + 'only methods and params: does the type\'s name promise a capability the code has NO mechanism to '
    + 'perform? A name implying an ACTIVE behavior (it produces, sends, schedules, or notifies on its own) '
    + 'when the object can only be queried or configured, or implying it persists or enforces something it '
    + 'never does, is a high-value trap -- record it. For each: the name, what it implies, what the code does, '
    + 'site, confidence. Do not invent domain facts the code does not support.' },
]
function codeLensPrompt(l) {
  return PREAMBLE + l.body + '\n\nWrite your structured result as pretty JSON to ' + l.out
    + ' and return it. Set lens to "' + l.key + '" and path to that file.'
}

// ---------- COMMENT LENS (3-lane: ledger / preserve / discard, with placement) ----------
const COMMENT_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    lens: { type: 'string' },
    ledger: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { fact: { type: 'string' }, why_non_derivable: { type: 'string' }, source_site: { type: 'string' }, confidence: { type: 'string', enum: ['high', 'med', 'low'] } },
      required: ['fact', 'why_non_derivable', 'source_site', 'confidence'] } },
    preserve: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { line: { type: 'string' }, placement: { type: 'string', enum: ['header-top', 'inline'] }, anchor_code: { type: 'string' }, attach: { type: 'string', enum: ['trailing', 'above', 'none'] }, orig_site: { type: 'string' }, reason: { type: 'string' } },
      required: ['line', 'placement', 'anchor_code', 'attach', 'orig_site', 'reason'] } },
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
  + '(2) PRESERVE -- provenance/legal/tracking metadata AND attributed human notes, kept VERBATIM, never '
  + 'reworded or fed to a writer: copyright, license, author; live TODO / issue-tracker refs; and any '
  + 'ATTRIBUTED note carrying human intent, a future plan, or a rationale. The canonical attributed form '
  + 'is "NOTE(<initials>): ..." (e.g. "NOTE(CB): refactor this class when pallas ships"); also recognize '
  + 'looser attributions (other initials-/name-prefixed notes) EVEN WITH NO TODO KEYWORD. An attributed '
  + 'note is a person speaking and is not derivable from code: preserve it verbatim, do NOT voice it, do '
  + 'NOT discard it as banter. For each set placement = "header-top" (copyright/author/license) or '
  + '"inline" (a directive/note/TODO tied to a code location) and orig_site. Store the line VERBATIM '
  + 'INCLUDING its leading # comment marker, exactly as written -- never strip the # down to the inner '
  + 'text, or it reattaches as bare code and breaks the file. For an INLINE item ALSO set anchor_code + '
  + 'attach so it reattaches at the RIGHT line (the finished file has the SAME executable code): anchor_code '
  + '= the exact source text of the code line it belongs to, and attach = "trailing" when the directive '
  + 'rides the end of a code line (a `# noqa` on `x = f()  # noqa` -> anchor_code `x = f()`, attach '
  + '"trailing") or "above" when it is a standalone comment on its own line (anchor_code = the FIRST code '
  + 'line just below it, attach "above"). For a HEADER-TOP item set anchor_code to "" and attach to "none".\n'
  + '(3) DISCARD -- everything else w/ a category: stale-archaeology, redundant-with-code, '
  + 'wrong-contradicts-code, decorative, banter, other.\n'
  + 'Be skeptical. Do not promote a redundant or wrong comment into the ledger.\n\n'
  + 'Write JSON to ' + EXP + '/findings/comments.json and return it. lens = "comments", path = that file.'

// ---------- LEDGER-WRITER (STUB STYLE + no-invented-examples) ----------
const LEDGER_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    facts: { type: 'array', items: { type: 'object', additionalProperties: false,
      properties: { stub: { type: 'string' }, gloss: { type: 'string' }, sites: { type: 'string' }, source_lenses: { type: 'array', items: { type: 'string' } }, confidence: { type: 'string', enum: ['high', 'med', 'low'] } },
      required: ['stub', 'gloss', 'sites', 'source_lenses', 'confidence'] } },
    domain_purpose: { type: 'string' }, ledger_path: { type: 'string' },
  },
  required: ['facts', 'domain_purpose', 'ledger_path'],
}
function ledgerPrompt(codeResults, commentLedger, domain, feedback) {
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
    + '  This applies to DESCRIPTIVE / characterizing facts too, not only mechanism. A quotable adjective '
    + 'phrase (a type that "understates" a contract, a value that is "best-effort", a field "set but never '
    + 'read") gets pasted verbatim and flattens voice just like a mechanism sentence. Fragment those too.\n'
    + '    GOOD: `arg duck-typed -> needs read()+close(); type hint too loose`\n'
    + '    BAD:  `the parameter type understates the protocol the object must implement`\n'
    + '- Dedup: same fact from two lenses -> one stub, list both source lenses.\n'
    + '- Dedup CONCEPTUALLY too: several facts that are different angles on ONE underlying behavior (e.g. '
    + 'several observations of one shared resource or one state machine) collapse into ONE stub. BUT preserve every '
    + 'distinct CALLER-relevant nuance inside that stub and keep ALL the code sites, so nothing is lost and '
    + 'the writer can still place it at the right symbol. Never merge facts with different caller '
    + 'consequences, and never drop a nuance just to shorten.\n'
    + '- Plain words inside the fragment: the un-copyability comes from the fragment having no grammar to '
    + 'paste, NOT from dense vocabulary. Arrows, colons, and `->` shorthand stay (they carry no word to '
    + 'paste), but use ORDINARY words for the rest, never a compressed technical term the writer would echo '
    + 'as jargon. A standard jargon word is just as load-bearing as an invented label: write `remembers what '
    + 'it already computed` not `memoizes`, `safe to call more than once` not `idempotent`, `merges them into '
    + 'one` not `coalesces`. Whenever a short everyday phrase says the same thing as one specialized word, '
    + 'write the phrase, even for a common, ordinary-looking technical term, and when in doubt assume the word '
    + 'is too technical and unpack it. A signed or directional value says its direction in plain words (which '
    + 'side is ahead), not as a bare subtraction. Do not invent a hyphenated compound LABEL either (a writer '
    + 'pastes it). State the '
    + 'behavior plainly and let the writer name it -- `holds items, drops the oldest when full`, not '
    + '`drop-oldest-when-full buffer`.\n'
    + '- Cite each fact at the site where its BEHAVIOR happens (the function or method that does it), NOT at '
    + 'a data declaration the behavior merely reads. A fact about how values are compared, routed, or chosen '
    + 'belongs to the comparing function, even when the value it reads is a field declared on a dataclass. '
    + 'Citing the declaration site sends the writer to explain behavior on a plain data record, which forces '
    + 'awkward prose (a data record has no behavior to describe).\n'
    + '- PROPORTION (worth-a-sentence test): every kept fact costs a sentence in a finished docstring. '
    + 'Before keeping a fact ask: would a competent reader of THIS symbol actually get it wrong? A '
    + 'pass-through, a delegation, an accessor, or a body of a few plainly-readable lines yields NO fact '
    + 'unless it carries a genuine inversion, absence, or cross-method trap -- "this method delegates to X" '
    + 'and "plain += with no clamp" are things the reader SEES. Fact count scales with the file\'s trap '
    + 'density, not its surface area: a small clean file legitimately yields two or three facts total, not '
    + 'a fact per symbol. Several line-level observations of ONE mechanism collapse to the single '
    + 'caller-visible consequence.\n'
    + '- This ledger carries ONLY TRAPS. The writer reads the code and writes a plain, correct explanation '
    + 'on its own FIRST, then uses this ledger to fix what that plain reading got WRONG and to add what the '
    + 'code cannot show. So DROP every fact a careful plain reading already gets right, even when true and '
    + 'important: a guard, validation, or default visible in the symbol; a plainly-correct single-method '
    + 'behavior; the internal data flow of a value, which line assigns or reads it, any step visible in the '
    + 'body. Feeding those back only makes the writer cram and enumerate.\n'
    + '- KEEP ONLY a trap, a fact a careful plain reading gets WRONG or cannot see: (a) an INVERSION or '
    + 'mis-referent -- a returned flag, field, or value that means the opposite of, or attaches to a '
    + 'different entity than, the naive reading (state which entity, which direction); (b) a CROSS-METHOD '
    + 'fact -- a role or relationship that only shows when you trace across methods; (c) an ABSENCE -- what '
    + 'the code does NOT do (a handle never closed, a value not persisted across a restart, an error '
    + 'swallowed), which a writer reading what the code DOES can never recover; (d) a NON-DERIVABLE contract '
    + 'or domain fact, or the human-scale reading of an opaque constant. If a fact is not one of these, '
    + 'DROP it.\n'
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
    + '- For each fact: a telegraphic stub, code sites, source lens keys, a confidence.\n'
    + '- GLOSS (for the human gate, never shown to writers): alongside each stub, write a `gloss` -- ONE '
    + 'complete plain-English sentence a non-expert teammate reads cold and understands: what the fact claims '
    + 'about the code and why a caller would care. Ordinary words, full grammar, no arrows or shorthand, no '
    + 'jargon, no cleverness. The stub is compressed notation for the writer; the gloss is the same fact '
    + 'said straight for a human deciding keep-or-drop. Example: stub `EAGAIN numeric differs by host: 11 '
    + 'linux/MP/CP, 35 macOS` -> gloss `The would-block error number is different on macOS than on Linux and '
    + 'the boards, so tests must match the error name rather than the number.`\n\n'
    + 'CODE (verify against it): ' + STRIPPED + '\n\n'
    + 'LENS FINDINGS:\n' + dump + cdump + '\n\n'
    + (feedback
      ? 'A VALIDATOR reviewed your PREVIOUS ledger and flagged the issues below. Produce a corrected, '
        + 'complete ledger that fixes EACH one — make a wrong fact true against the code, and make an '
        + 'ambiguous correctness-critical fact unambiguous (state which entity / which direction) while '
        + 'keeping it a telegraphic stub, not prose. Keep all the other good facts.\n'
        + 'VALIDATOR FEEDBACK:\n' + feedback + '\n\n'
      : '')
    + 'Write the merged ledger as a terse markdown stub list (one `- ` line per fact, sites in parens; every '
    + 'line a fragment per STUB STYLE; NO glosses in the .md -- writers read it) to ' + EXP + '/ledger_provisional.md. '
    + 'ALSO write the SAME facts as a pretty JSON array (each item {stub, gloss, sites, source_lenses, '
    + 'confidence}) to ' + EXP + '/ledger.json '
    + '(the orchestrator reads this to find the questionable facts for the human picker). Set ledger_path to '
    + 'the .md, return the structured result. Set domain_purpose to: "' + (domain || '') + '".'
}

// ---------- VALIDATOR (fixture-agnostic; gates correctness, drives the re-run loop) ----------
const VALIDATE_OUT = {
  type: 'object', additionalProperties: false,
  properties: {
    facts: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { fact: { type: 'string' }, correct: { type: 'boolean' }, note: { type: 'string' } }, required: ['fact', 'correct', 'note'] } },
    underspecified: { type: 'array', items: { type: 'object', additionalProperties: false, properties: { fact: { type: 'string' }, why: { type: 'string' } }, required: ['fact', 'why'] } },
    any_wrong: { type: 'boolean' }, any_underspecified: { type: 'boolean' }, verdict: { type: 'string' },
  },
  required: ['facts', 'underspecified', 'any_wrong', 'any_underspecified', 'verdict'],
}
const validatePrompt =
  'You validate a nuance LEDGER against the CODE. You have NO trap list and NO prior knowledge of this '
  + 'file — reason only from the code.\n\nCODE: ' + STRIPPED + '\nLEDGER: ' + EXP + '/ledger_provisional.md\n\n'
  + '(1) For EACH ledger fact, verify it is TRUE against the code (record correct + a short note; quote the '
  + 'code site when wrong). EXCEPTION: a comment-derived domain fact is NON-CODE-DERIVABLE by design — it '
  + 'comes from a now-stripped comment and is not in the code. Do NOT mark it wrong merely for being absent '
  + 'from the code; mark it correct unless the code actively CONTRADICTS it.\n'
  + '(2) Flag any fact in a CORRECTNESS-CRITICAL CLASS that is stated AMBIGUOUSLY (a reader could invert or '
  + 'misread it): a returned flag or field\'s referent (WHICH entity it acts on), an inversion (a value that '
  + 'means the opposite of the naive reading), a dual-role value (one name, two jobs), or a boundary / '
  + 'inclusive-vs-exclusive condition. Under-specified = states only half the fact or leaves the critical '
  + 'half to be inferred.\n\n'
  + 'Write JSON to ' + EXP + '/validation.json with keys facts, underspecified, any_wrong, '
  + 'any_underspecified, verdict. After writing, reply DONE.'
function buildFeedback(v) {
  const wrong = (v.facts || []).filter((f) => !f.correct).map((f) => '- WRONG: ' + f.fact + ' -- ' + f.note)
  const under = (v.underspecified || []).map((f) => '- AMBIGUOUS: ' + f.fact + ' -- ' + f.why)
  return wrong.concat(under).join('\n')
}

// ---------- GENRE TRIAGE (test / functional_test / example) ----------
// A test file has no caller-contract traps to converge on, and an example is annotated, not trap-hunted --
// so the genre path skips the 3 trap lenses and the 4x re-run loop. ONE genre-ledger agent writes the same
// ledger.json + ledger_provisional.md shape (so the picker + phase 2 are unchanged), the comment lens still
// runs for the preserve lane, and a single validate pass checks each fact against the code.
function genreLedgerPrompt(genre) {
  const common =
    '\n\nRecord each fact as a TELEGRAPHIC FRAGMENT (symbols, arrows ->, shorthand), never a grammatical '
    + 'sentence a writer could paste. For each fact give stub, sites (the symbol or line it attaches to), '
    + 'source_lenses set to ["' + genre + '"], confidence (high unless genuinely unsure), and a gloss -- ONE '
    + 'complete plain-English sentence for the human gate (ordinary words, full grammar, no shorthand or '
    + 'jargon) saying what the fact claims and why it matters; the stub is for the writer, the gloss is for '
    + 'a non-expert teammate deciding keep-or-drop.\n'
    + 'CROSS-FILE: if a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, use it to name the subject '
    + 'under test or the library API the example uses, but do not re-derive its facts.'
  const tail =
    '\n\nWrite the ledger as a terse markdown stub list (one `- ` line per fact, sites in parens; NO glosses '
    + 'in the .md -- writers read it) to '
    + EXP + '/ledger_provisional.md. ALSO write the SAME facts as a pretty JSON ARRAY (each item '
    + '{stub, gloss, sites, source_lenses, confidence}) to ' + EXP + '/ledger.json -- a bare array, not an object '
    + '(the orchestrator reads this array to find the questionable facts for the picker). Set ledger_path to '
    + 'the .md and return the structured object {facts, domain_purpose, ledger_path}.'
  if (genre === 'example') {
    return 'You are preparing a writer that will DENSELY document a Python EXAMPLE file -- tutorial code a '
      + 'reader copies to learn the library. The file has NO comments; the CODE is the only source of truth. '
      + 'CODE: ' + STRIPPED + '\n\n'
      + 'Produce a DENSE annotation plan:\n'
      + '- ONE module fact: what the example DEMONSTRATES, in user-intent terms (a verb-led idea, e.g. '
      + '`pack+unpack a settings dict`). sites=<module>.\n'
      + '- A USE-CASE fact (when a reader reaches for this pattern) and, when not obvious, a HOW-TO-RUN fact '
      + '(what to import, how to run it). sites=<module>.\n'
      + '- For NEARLY EVERY meaningful line -- each import, assignment, call, and print -- ONE fact giving '
      + 'WHAT the line does (its real effect in the demo, not its syntax) AND WHY it is in the example (the '
      + 'teaching point, why a caller would do it this way). sites=<that line>. '
      + 'GOOD: `int keys -> 1 byte each vs multi-byte string keys; why: max compactness`. '
      + 'BAD: `builds a dict` (syntax restatement, teaches nothing). Skip only a truly trivial line.\n'
      + 'Aim to annotate nearly every line -- denser than ordinary code. Do NOT invent example output. '
      + 'Set domain_purpose to what the example demonstrates.' + common + tail
  }
  const altitude = genre === 'functional_test'
    ? 'These are FUNCTIONAL / end-to-end tests: state each claim at SCENARIO altitude -- the behavior '
      + 'exercised against the real runtime, device, or socket, not a unit assertion.\n'
    : ''
  return 'You are preparing a writer that will docstring a Python TEST file. The file has NO comments; the '
    + 'CODE is the only source of truth. CODE: ' + STRIPPED + '\n\n' + altitude
    + 'Produce a claim ledger:\n'
    + '- ONE module fact: what the file tests (subject + area). If the file declares cross-runtime markers '
    + '(a `__chumicro_runtimes__`, a harness import, pytest), add a fact noting the runtimes. sites=<module>.\n'
    + '- For EACH test function: ONE fact = the CLAIM it verifies, stated as the SUBJECT UNDER TEST doing '
    + 'the asserted behavior in DOMAIN terms (e.g. `ticks_diff -> plain gap for a forward diff`), NOT the '
    + 'test mechanism (fakes, the assert order, raises()). sites=<the test function>.\n'
    + '- For any SETUP VALUE whose meaning is non-obvious (a magic number, an off-by-one such as advancing '
    + 'to one tick before a period), ONE fact = value -> its domain meaning, sites=<that line>, so the '
    + 'writer can add a one-line above comment. Skip obvious setup.\n'
    + 'Do NOT restate assert mechanics. Do NOT produce Args/Returns facts (test functions have none). '
    + 'Set domain_purpose to what the file tests.' + common + tail
}
const genreValidatePrompt =
  'You validate a ledger against the CODE. You have no prior knowledge of this file -- reason only from the '
  + 'code.\n\nCODE: ' + STRIPPED + '\nLEDGER: ' + EXP + '/ledger_provisional.md\n\n'
  + 'For EACH ledger fact, verify it is TRUE against the code (record correct + a short note; quote the code '
  + 'site when wrong). For a TEST file a CLAIM is true when the test really asserts that behavior of that '
  + 'subject -- mark it wrong if it misreads what the test checks. For an EXAMPLE an annotation is true when '
  + 'it correctly states what that line does -- mark it wrong if it misdescribes the effect. A '
  + 'comment-derived fact that is not in the code is NOT wrong merely for being absent. Set any_wrong if any '
  + 'fact is wrong; set any_underspecified to false (genre facts carry no correctness-critical inversion '
  + 'class). Write JSON {facts, underspecified: [], any_wrong, any_underspecified, verdict} to '
  + EXP + '/validation.json. After writing, reply DONE.'

// ---------- run ----------
if (GENRE === 'test' || GENRE === 'functional_test' || GENRE === 'example') {
  phase('Lenses')
  const [ledger, commentRes] = await parallel([
    () => agent(genreLedgerPrompt(GENRE), { label: 'genre-ledger:' + GENRE, phase: 'Ledger', model: 'opus', agentType: 'general-purpose', schema: LEDGER_OUT }),
    () => agent(commentPrompt, { label: 'lens:comments', phase: 'Lenses', model: 'opus', agentType: 'general-purpose', schema: COMMENT_OUT }),
  ])
  const comment = commentRes || { ledger: [], preserve: [], discard: [] }
  phase('Validate')
  const validation = await agent(genreValidatePrompt, { label: 'validate', phase: 'Validate', model: 'opus', agentType: 'general-purpose', schema: VALIDATE_OUT })
  const facts = (ledger && ledger.facts) || []
  const questionable = facts.filter((f) => f.confidence === 'low' || f.confidence === 'med')
  const converged = !validation.any_wrong
  log('genre triage (' + GENRE + ') done: ' + facts.length + ' facts, ' + (converged ? 'validated clean' : 'validator flagged a fact for the human'))
  return { facts, domain_purpose: (ledger && ledger.domain_purpose) || '', ledger_path: (ledger && ledger.ledger_path) || (EXP + '/ledger_provisional.md'), preserve: comment.preserve || [], discard: comment.discard || [], questionable, converged, attempts: 1 }
}

// CODE path (default): 3 trap lenses + comment lens -> ledger-writer -> validator/converge loop
phase('Lenses')
const lensResults = await parallel([
  ...CODE_LENSES.map((l) => () => agent(codeLensPrompt(l), { label: 'lens:' + l.key, phase: 'Lenses', model: 'opus', agentType: 'general-purpose', schema: LENS_OUT }).then((r) => ({ kind: 'code', r }))),
  () => agent(commentPrompt, { label: 'lens:comments', phase: 'Lenses', model: 'opus', agentType: 'general-purpose', schema: COMMENT_OUT }).then((r) => ({ kind: 'comment', r })),
])
const code = lensResults.filter(Boolean).filter((x) => x.kind === 'code').map((x) => x.r)
const comment = (lensResults.filter(Boolean).find((x) => x.kind === 'comment') || {}).r || { ledger: [], preserve: [], discard: [] }
const domain = (code.find((r) => r.domain_purpose) || {}).domain_purpose || ''

phase('Ledger')
let ledger = await agent(ledgerPrompt(code, comment.ledger || [], domain), { label: 'ledger-writer', phase: 'Ledger', model: 'opus', agentType: 'general-purpose', schema: LEDGER_OUT })

// Validate the ledger against the code, and re-run the LEDGER-WRITER ONLY against the validator's notes
// until it converges or we hit the cap. Lenses do not re-run — their findings are fixed; only the merge
// is corrected. validation.json (written by the validator) holds the final verdict for the orchestrator.
const MAX_LEDGER_ATTEMPTS = 4
phase('Validate')
let validation = await agent(validatePrompt, { label: 'validate', phase: 'Validate', model: 'opus', agentType: 'general-purpose', schema: VALIDATE_OUT })
let attempt = 1
while ((validation.any_wrong || validation.any_underspecified) && attempt < MAX_LEDGER_ATTEMPTS) {
  log('validator flagged issues (attempt ' + attempt + '/' + MAX_LEDGER_ATTEMPTS + '); re-running ledger-writer with feedback')
  ledger = await agent(ledgerPrompt(code, comment.ledger || [], domain, buildFeedback(validation)), { label: 'ledger-writer:retry' + attempt, phase: 'Ledger', model: 'opus', agentType: 'general-purpose', schema: LEDGER_OUT })
  validation = await agent(validatePrompt, { label: 'validate:retry' + attempt, phase: 'Validate', model: 'opus', agentType: 'general-purpose', schema: VALIDATE_OUT })
  attempt++
}
const converged = !(validation.any_wrong || validation.any_underspecified)
log(converged ? 'ledger validated clean after ' + attempt + ' attempt(s)' : 'ledger still flagged after ' + attempt + ' attempts; orchestrator must escalate to the human')

const questionable = (ledger.facts || []).filter((f) => f.confidence === 'low' || f.confidence === 'med')
return { facts: ledger.facts, domain_purpose: ledger.domain_purpose, ledger_path: ledger.ledger_path, preserve: comment.preserve || [], discard: comment.discard || [], questionable, converged, attempts: attempt }
