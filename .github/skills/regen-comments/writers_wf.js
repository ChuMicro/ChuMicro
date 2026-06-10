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
// VOICE_SAMPLE is a real-prose excerpt of the chosen voice, substituted as a JSON string literal from
// voice_samples/<key>.md (excerpt text only -- attribution never reaches the prompt). Empty = no sample.
const VOICE_SAMPLE = "__VOICE_SAMPLE__"
// GENRE selects the writer shape: 'code' (default) = behavior + caller contract; 'test'/'functional_test' =
// one-sentence claim docstrings (no Args/Returns); 'example' = dense near-line annotation. Voice still
// applies as a register, but the genre shape leads.
const GENRE = "__GENRE__"
// TIGHT mode (opt-in --tight): summary-only docstrings, 1-2 sentences, no body/sections; a
// self-documenting symbol gets NO docstring. The strict-no-body rule chosen 2026-05-26, as a run mode.
const TIGHT = '__TIGHT__' === '1'
// LESS mode (opt-in --less): the same 1-2 sentence summary discipline as tight, but the Args / Returns /
// Raises sections STAY (short entries, no body paragraphs between summary and sections).
const LESS = '__LESS__' === '1'

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
// usable docstring. round33 added a VOICELESS-ONLY flowing-summary clause (weave a non-obvious behavior into a
// smooth summary instead of over-compressing into a thin body) -- it trims the occasional under-written
// docstring on the baseline and stays off voiced runs so it cannot fight the voice. The SELECTOR picks the
// RICHEST, best-worded pass, not the flattest (flat is wrong);
// legibility is its only floor, correctness its secondary one -- a garbled or backwards pass still loses.
// GENRE writer (test / functional_test / example). The code-genre writer below is unchanged; these genres
// have a different shape entirely -- a test docstring names the claim (no Args/Returns, no body), an example
// is annotated densely line by line -- so genrePrompt is self-contained and genPrompt returns it early.
// Voice still applies as a register (voiceLead), but the genre shape leads.
// sampleBlock() builds the optional voice-sample section of a voiced prompt: VOICE_SAMPLE framed so the
// writer absorbs word choice, rhythm, and attitude from real prose while the genre shape and limits keep
// owning the format. Empty when the run is voiceless or the voice has no sample on file.
function sampleBlock() {
  if (!VOICE_PARA.trim() || !VOICE_SAMPLE.trim()) return ''
  return 'A sample of that voice, in its own genre rather than code comments. Absorb the rhythm, '
    + 'attitude, and word choice from it, then write in your own words about this code -- never reuse '
    + 'its phrases or subject matter, and never its paragraph length or format. Every shape and length '
    + 'rule below still applies as written:\n\n' + VOICE_SAMPLE.trim() + '\n\n'
}

function genrePrompt(genre, n) {
  const out = RUNDIR + '/runs/run-' + n + '.py'
  const voiced = VOICE_PARA.trim()
  const register = voiced ? 'in that voice' : 'in plain English'
  const voiceLead = voiced
    ? (VOICE_PARA + ' Let the voice come through in word choice and rhythm, but keep the genre shape below, '
       + 'and every docstring and comment must stay clear and usable.\n\n' + sampleBlock())
    : ''
  const bans =
    '\n\nNo em-dashes or semicolons or the words `canonical` or `shape`. Wrap code identifiers and literals '
    + 'in double backticks and keep lines to 100 characters. Add docstrings and comments only -- never '
    + 'change code, imports, or signatures.\n\nWrite the marked-up file to ' + out + '. After writing, reply '
    + 'DONE.'
  const head = 'Read the code at ' + FILE + ' and the ledger at ' + LEDGER + ' together.\n\n'
  if (genre === 'example') {
    return voiceLead + head
      + 'This is an EXAMPLE -- tutorial code a reader copies to learn the library. Document it DENSELY '
      + register + '. The ledger gives an annotation plan (what each line does and why it is in the '
      + 'example).\n\n'
      + 'Module docstring: a verb-led summary of what the example demonstrates (user intent, e.g. "Pack and '
      + 'unpack a settings dictionary."), then a short body -- when a reader reaches for this pattern, and '
      + 'how to run it (name what to install or import, but do NOT write a specific script filename in the run '
      + 'command: you are given a stripped copy, not the real filename, so say e.g. "run it with `python`"). '
      + 'Use the ledger\'s use-case and how-to-run facts. Do NOT invent example output.\n\n'
      + 'INLINE COMMENTS, DENSE: put a short comment (one or two sentences, on the line(s) directly above) '
      + 'on NEARLY EVERY meaningful line -- each import, assignment, call, and print. Each comment says WHAT '
      + 'the line does (its real effect in the demo) AND WHY it is in the example (the teaching point, why a '
      + 'caller would do it this way). State effect and intent, NEVER bare syntax: write `# integer keys each '
      + 'encode in a single byte, versus several for a quoted string, so use them when you want maximum '
      + 'compactness`, not `# build the settings dict`. The reader is learning, so `you` is fine in inline '
      + 'comments. If a line needs more than two sentences, the example is doing too much -- keep it short.\n\n'
      + 'Preserve EVERY import exactly (the import block is the contract a reader copies). Do not add '
      + 'functions, classes, or an `if __name__ == "__main__"` guard -- keep it the flat script it is.'
      + bans
  }
  const altitude = genre === 'functional_test'
    ? ' These are functional / end-to-end tests, so each claim is at SCENARIO altitude -- the behavior '
      + 'exercised against the real runtime, device, or socket, not a unit assertion.'
    : ''
  return voiceLead + head
    + 'This is a TEST file. Write docstrings and minimal above-line comments ' + register + '. The ledger '
    + 'gives, per test, the CLAIM it verifies.' + altitude + '\n\n'
    + 'Module docstring: one sentence naming what the file tests (lead with a verb or the subject area). If '
    + 'the ledger notes cross-runtime or a harness, add one short second line for it. No more.\n\n'
    + 'Each test function: ONE summary sentence naming the CLAIM the subject under test verifies -- the '
    + 'behavior, in domain terms, with the subject acting (e.g. "``ticks_diff`` returns the plain gap for a '
    + 'forward difference."). Do NOT narrate the test body (fakes, the assert order, ``raises()``). Do NOT '
    + 'open with "Tests that", "Verifies that", "Ensures", or "Checks that" -- let the subject act. NO Args, '
    + 'NO Returns, NO Raises, and NO body paragraph: a test takes no contract parameters and returns nothing, '
    + 'so the whole docstring is the one-sentence claim.\n\n'
    + 'Above-line comment: add ONE short line ONLY where a setup value\'s meaning is non-obvious (the ledger '
    + 'flags these), e.g. `# one tick before the period`. Default to no comment; never restate the code.\n\n'
    + 'Preserve every decorator, marker, fixture, and harness call (``@pytest.fixture``, ``@pytest.mark.*``, '
    + '``__chumicro_runtimes__``, the harness ``skip``) exactly.'
    + bans
}

// round35: the tight/less writer runs LEAN (~150 words vs the prior ~400). An A/B/C/D bourdain bench
// (2026-06-10, same ledger/selector, all modes) found the accreted rule pile flattened the voice while
// this shape read the most alive, with ZERO ledger-fact misses and ZERO mechanical-ban violations across
// every arm (13-arm audit). n=1 arms vs the measured 57-70% run-noise floor, so directional -- the queued
// variance bench (n>=5, deterministic counts) is the rigorous confirm. Two short guards ride along for
// known failure modes: the above-def `#` block (a live-run bug) and notation-style comments.
function tightPrompt(n) {
  const voiced = VOICE_PARA.trim()
  const voiceBlock = voiced
    ? (VOICE_PARA + ' Every docstring and comment is fully in that voice.\n\n' + sampleBlock())
    : ''
  const register = voiced ? 'in that voice' : 'in plain English'
  return voiceBlock
    + 'Read the code at ' + FILE + ' and the nuance ledger at ' + LEDGER + ' (the non-obvious behavior a '
    + 'plain reading misses). Each class, function, and method: a one-or-two-sentence docstring ' + register
    + ' -- purpose and caller contract, complete sentences only, the first a proper summary line. No body '
    + 'paragraphs. '
    + (LESS
        ? 'Short Args and Returns (or Raises) sections where they apply, each entry a SINGLE short '
          + 'sentence, never padded into prose; omit entries that just restate a name and type. '
        : 'No Args / Returns / Raises sections. ')
    + 'A self-evident symbol gets no docstring; contract text always lives IN the docstring (where '
    + '`help()` sees it), never as a `#` block above the `def`. Every ledger fact lands exactly once: '
    + 'contract facts in the docstring, line facts as `#` sentences above their lines, in the same '
    + 'register -- never notation or `->` arrows. Drop none.\n\n'
    + 'If a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, use it for shared vocabulary.\n\n'
    + 'No em-dashes, semicolons, `canonical`, or `shape`. Code in double backticks, lines under 100 '
    + 'characters. Add docstrings and comments only -- never change code.\n\n'
    + 'Write the marked-up file to ' + RUNDIR + '/runs/run-' + n + '.py. After writing, reply DONE.'
}

// round35 (voiced ONLY): the voiced code-genre writer runs LEAN (~175 words vs the accreted ~490). The
// A/B/C/D bourdain head-to-head (2026-06-10, same ledger/selector) found the instruction pile flattened
// the voice while this shape read the most alive; sampleBlock() carries the register from real prose
// (the own-words framing held n-gram copy-signal at 0 in every arm), and the mechanical audit showed
// zero ledger-fact misses and zero ban violations. n=1 arms vs the 57-70% noise floor -- directional;
// the queued variance bench is the rigorous confirm. The voiceless path below stays on the fuller
// round26-34 wording: benched there, near-parity in today's plain A-vs-D arms (where the lean arm even
// leaked a prompt phrase once), and its two voiceless-only nudges still earn their keep.
function voicedPrompt(n) {
  return VOICE_PARA + ' Every docstring and comment is fully in that voice.\n\n' + sampleBlock()
    + 'Read the code at ' + FILE + ' and the nuance ledger at ' + LEDGER + ' (the non-obvious behavior a '
    + 'plain reading misses). Explain in that voice what the code does: each symbol\'s purpose and the '
    + 'contract a caller relies on, never how a line computes. A line-level mechanic goes as a `#` sentence '
    + 'above its line, in the same register. Each ledger fact lands exactly once; drop none. Length follows '
    + 'the symbol\'s complexity: simple symbols get one sentence, and the sample never adds length.\n\n'
    + 'Keep the FORM a proper docstring: the first line is a complete summary sentence, every sentence is '
    + 'complete (no fragments), and functions and methods get short Args and Returns (or Raises) sections '
    + 'where they apply -- omit a Returns for nothing and entries that just restate a name and type.\n\n'
    + 'If a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, use it for cross-file context and '
    + 'shared vocabulary.\n\n'
    + 'No em-dashes, semicolons, `canonical`, or `shape`. Code in double backticks, lines under 100 '
    + 'characters. Add docstrings and comments only -- never change code.\n\n'
    + 'Write the marked-up file to ' + RUNDIR + '/runs/run-' + n + '.py. After writing, reply DONE.'
}

function genPrompt(n) {
  if (GENRE === 'test' || GENRE === 'functional_test' || GENRE === 'example') return genrePrompt(GENRE, n)
  if (TIGHT || LESS) return tightPrompt(n)
  if (VOICE_PARA.trim()) return voicedPrompt(n)
  // VOICELESS path -- the round26-34 benched wording, kept fuller than voicedPrompt on purpose: with no
  // voice to fill the space the structure still earns its keep.
  // round33: the flowing-summary nudge cut the occasional thin / over-compressed docstring (control
  // under-wrote _resolve_mixed / _rank_key bodies, collapsing them into Returns; flowing kept full
  // bodies). Head-to-head vs lean control: legibility + correctness held, ban arm REJECTED.
  // round34: the module-altitude reword closed the diagnosed MODULE gap (plain crammed the per-method
  // drift rule into the module summary where the summarizer stayed high-level); held correctness.
  return 'Read the code at ' + FILE + ' and the nuance ledger at ' + LEDGER + ' together. The ledger holds the '
    + 'non-obvious behavior a plain reading of the code misses.\n\n'
    + 'Explain in plain English what the code does. For the module, what the file does in the real world '
    + 'and how it is organized. Keep it high-level -- the per-method rules, conditions, and thresholds '
    + 'belong on those methods, not in the module docstring. For '
    + 'each class, function, and method, its purpose and any non-obvious behavior: what it does and the '
    + 'contract a caller relies on, not how a particular line computes. Use plain, ordinary words, not a '
    + 'denser technical label (say "a cache that remembers what it already computed", not "a memoization '
    + 'layer"). Do not restate '
    + 'what the code already shows, like an enum\'s members when their names already '
    + 'say it, do not point the reader to other symbols by name, and do not invent. Write in plain, '
    + 'smooth, flowing sentences, and when a non-obvious behavior can be woven into the '
    + 'summary itself, do that rather than compressing the summary and spilling into a separate body paragraph.\n\n'
    + 'A line-level mechanic, such as an inclusive boundary, a value compared one way and not another, or a '
    + 'stand-in substitution, rides as a short `#` comment on its own line above that line, not in the '
    + 'docstring. State each fact once. An inline comment is a short REAL SENTENCE in the same register as '
    + 'the docstrings -- it speaks, it is not a compressed note: never echo the ledger\'s notation, never '
    + 'splice fragments with colons, never use `->` arrows.\n\n'
    + 'PROPORTION: a docstring\'s length follows the symbol\'s complexity, and most symbols are simple. A '
    + 'pass-through, a delegation, an accessor, or a body of a few plainly-readable lines gets ONE clear '
    + 'sentence and stops. Save body paragraphs for the few symbols whose behavior genuinely needs them. '
    + 'Never narrate a method body line by line: if you catch yourself describing what each line does, the '
    + 'load-bearing mechanic becomes a `#` comment at its line and the rest is cut, not written.\n\n'
    + 'If a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, use it for cross-file context and '
    + 'shared vocabulary.\n\n'
    + 'Give Args and Returns (or Raises) for the functions and methods that have them, each a short plain '
    + 'description. Omit Returns when a function returns nothing, and omit an Args entry whose description '
    + 'would only restate the parameter\'s name and type. No em-dashes or semicolons or the words `canonical` or `shape`. Wrap code expressions in '
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
  const preamble = 'You are a SELECTOR (fixture-agnostic — no trap list, no prior knowledge of this file). '
    + PASSES + ' candidate commented versions of the SAME file were written in one voice, each a COMPLETE '
    + 'file. Read all of them, plus the stripped code ' + FILE + ' and the ledger ' + LEDGER + ' for '
    + 'context. Pick the ONE best complete file by its number. You do NOT edit, merge, rewrite, or combine '
    + 'files — you only choose one. The chosen file is taken exactly as written.\n\n'
    + 'Candidates (number: path):\n' + runs + '\n\n'
    + 'If a library ledger exists at ' + RUNDIR + '/LIBRARY_FACTS.md, use it as a vocabulary reference: '
    + 'prefer a file that uses the shared terms correctly.\n\n'
  const footer = '\n\nWrite {winner, why, concern} to ' + RUNDIR + '/pick.json — winner = the chosen number '
    + 'from 1 to ' + PASSES + ', why = one or two sentences on why it won, concern = any correctness issue '
    + 'you noticed in the chosen file (so a human can double-check it), or "" if none. Return the same '
    + 'object. Do not write any other file. Reply only after pick.json is written.'
  let job
  if ((TIGHT || LESS) && GENRE !== 'test' && GENRE !== 'functional_test' && GENRE !== 'example') {
    job = 'YOUR JOB (' + (LESS ? 'LESS' : 'TIGHT') + ' MODE): pick the file whose one-or-two-sentence '
      + 'summary DOCSTRINGS are the sharpest and most exact. REJECT a file that writes '
      + (LESS
          ? 'a body paragraph anywhere (short Args / Returns / Raises sections are REQUIRED where they '
            + 'apply and are not a violation, but an entry padded into prose is)'
          : 'a body paragraph or an Args / Returns / Raises section anywhere')
      + ', stuffs extra clauses into a sentence to smuggle detail past the limit, replaces a '
      + 'docstring with a `#` comment block above the `def`/`class` line (contract text must be IN the '
      + 'docstring where `help()` sees it), writes `#` comments that read like compressed notes (fragment '
      + 'chains spliced with colons, `->` arrows) instead of short sentences in the file\'s register, '
      + 'or docstrings a symbol with nothing to say. Among the compliant files '
      + 'prefer the one that says the necessary thing in the fewest, best words while keeping the ledger '
      + 'facts placed (in the docstring when they are the contract, else as `#` comments at their lines). '
      + 'Thin is correct here; missing the caller contract is not -- and a pass that reads clipped or '
      + 'amputated loses to one that spends a full second sentence where the contract earns it.'
  } else if (GENRE === 'test' || GENRE === 'functional_test') {
    job = 'YOUR JOB: pick the file whose test docstrings best NAME THE CLAIM each test verifies -- the '
      + 'subject under test acting, in domain terms, in one clean sentence (e.g. "``ticks_diff`` returns the '
      + 'plain gap for a forward difference."), not how the test does it. REJECT a file that narrates the '
      + 'test body (fakes, assert order, ``raises()``), opens with "Tests that / Verifies that / Ensures", '
      + 'adds Args / Returns / Raises or a body paragraph to a test, or misstates what a test actually '
      + 'asserts. Among the clean ones prefer the sharpest, most specific claims and the tightest module '
      + 'docstring; an above-line comment should appear only on a genuinely non-obvious setup value, never '
      + 'restating code.'
  } else if (GENRE === 'example') {
    job = 'YOUR JOB: pick the file that TEACHES best. An example is read to learn the library, so the winner '
      + 'carries a short comment on NEARLY EVERY meaningful line, each giving what the line does AND why it '
      + 'is in the example (the teaching point), plus a verb-led module docstring with a useful when-to-use '
      + 'and how-to-run body. REJECT a file that is sparse or under-annotated (lines left bare), restates '
      + 'syntax ("# build the dict", "# loop over items") instead of giving effect + intent, or invents '
      + 'example output. Among the well-annotated ones prefer the one whose comments most clearly explain why '
      + 'a caller would make each choice, each kept to one or two sentences.'
  } else {
    job = 'YOUR PRIMARY JOB IS HOW THE COMMENTS READ. Pick the file whose comments are the best-WORDED at '
      + 'the right ALTITUDE -- alive, characterful sentences that say each thing once, well, in proportion '
      + 'to the symbol. Richness means quality of wording, NEVER quantity: a file that narrates method '
      + 'bodies line by line, pads a trivial pass-through with body paragraphs, or repeats one fact in '
      + 'several costumes is STUFFED, not rich -- it loses to a file that states the contract cleanly and '
      + 'stops (a docstring visibly longer than its method is a strong stuffing signal). Do NOT pick a '
      + 'flat, thin, generic file either: among the files at the right altitude, the most vivid, '
      + 'best-turned wording wins. The other floor is legibility: every sentence must still read clearly '
      + 'as a proper docstring a caller could use. A sentence that is garbled, so dense or comma-ridden it '
      + 'confuses, or contorted past being understood is not rich, it is broken, and it loses -- but a '
      + 'vivid metaphor or a strong turn of phrase that reads clearly IS good wording, and it wins. The '
      + 'same wording bar covers the inline `#` comments: they are short sentences in the file\'s register; '
      + 'a file whose comments read like compressed notes (fragment chains spliced with colons, `->` '
      + 'arrows) loses to one whose comments speak.\n\n'
      + 'Correctness is a SECONDARY sanity check, not a completeness test. Among the well-written files, reject '
      + 'one that MISLEADS about what the code does: a comment that states the opposite of the code, pins a '
      + 'result on the wrong thing, or garbles a non-obvious behavior into a statement that cannot hold '
      + 'together. But do NOT punish a rich file for leaving out a minor detail. When two files read about '
      + 'equally well, prefer the one that gets the non-derivable traps right.'
  }
  return preamble + job + footer
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
