# Review contracts

Use fresh reviewers without the author's conversation history. Assign the exact
files each may read. The brief reviewer and technical reviewer can inspect named
source evidence. The reader reviewer receives only its listed reader-review inputs.
Use `model: "opus"` for Claude judgment agents. In another host, use its supported
judgment model and record the actual model rather than pretending it is Opus.

## Brief review

Ask the reviewer to verify every required claim, command, example, warning, and
publication constraint against the evidence. It must re-open cited sources or
inspect captured command outputs. A missing prerequisite, an unsupported claim,
copied old prose, or a fact note written as a finished sentence blocks readiness.
Trace every retained ID to the ledger.

Check that required content serves the outcome at the reader's knowledge level.
Distinguish supporting evidence from material that must appear in the page. Trace
concept dependencies in reading order. Flag requirements that force duplicated
explanations, gratuitous checkpoints, or general lessons the reader already knows.

Give the reviewer the brief's SHA-256 digest, computed from its bytes. Request
one JSON object with these fields:

| Field | Value |
|---|---|
| `brief_sha256` | Supplied SHA-256 digest of the reviewed file |
| `reviewer` | Nonempty string identifying the actual reviewer role and model or human name |
| `status` | `ready` or `blocked` |
| `checks` | Object with boolean `accuracy`, `coverage`, `reader_sequence`, `prose_independence` |
| `blocking_findings` | Array of concrete unresolved findings |
| `notes` | Nonempty string describing evidence inspected and nonblocking observations |

`ready` requires all four checks to be true and an empty blocking-findings list.
This record ties a review to input bytes. It is not a cryptographic identity or
proof of the reviewer's diligence. Inspect the actual evidence and report.

## Technical review

Inputs: draft, brief, ledger, required-topic disposition, publication constraints,
and named technical sources. Exclude rejected prose drafts and stylistic critiques.

Check the following:

- Every required fact, warning, example, and prerequisite is present or linked at
  the correct point. Compare retained IDs with the draft in both directions.
- Every new technical claim in the draft has evidence. Fluency cannot supply a
  missing guarantee, version number, board behavior, or timing estimate.
- Commands and code match checked artifacts, use public APIs, and state where
  they run. Re-run affected checks if the writer changed technical contents.
- Dependencies and supported runtimes match the intended audience.
- Relative links, headings, anchors, images, and navigation resolve in the
  destination renderer. Preserve required metadata and footer elements.

Return findings with location, quoted evidence, consequence, and a factual
requirement for resolution. Mark each as blocking or advisory. Include a coverage
map from required IDs to sections and identify verification that needs hardware.

## Reader review

Inputs: draft, audience, outcome, the voice definition in
[style-guide.md § Documentation tone](../../../docs/contributing/style-guide.md#documentation-tone),
the register excerpt in `_shared/voices/voice_samples/chumicro-docs.md`, and the
editorial criteria. Exclude the old page, the evidence ledger, writer
deliberation, and other reviewers' findings.

Read once, top-down, tracking only the audience's starting knowledge and what the
page has supplied. At first mention of an unfamiliar thing, can the reader name
its role? Check definite references, given-before-new transitions, and paragraph
dependencies. Flag a definition that arrives after its use. Check that each
paragraph opens with a claim and develops it, and that verbs carry the actions.

At each step, identify the action, location, and any result the reader needs to
recognize. Request recovery guidance only for a plausible failure with an
actionable remedy; a general troubleshooting link can cover the rest. Check
choice overload, repetition, digressions, and whether optional detail delays the
promised result. Do not turn this review checklist into a required page outline.

For a tutorial, optionally record that walkthrough as a task rehearsal. For each
step, list the reader's starting knowledge, next action and its location, expected
observation, recovery guidance, and any information the reader must guess. Label
the record as a simulated reading exercise; command execution and hardware
observations have their own verification records. Use the uncertain steps to
identify concrete requirements for the next brief.

Assess the voice against the style guide's definition and the register excerpt:
professional, approachable, precise, and fluent. Flag terse fragments that remove
necessary context as well as bloated prose. Judge articles
by their referents; counts of “the” or “is” cannot establish a defect.
Check for historical debris, litotes, unnecessary contrast, invented compound
labels, filler, and repeated explanations. Preserve real warnings and meaningful
technical comparisons. A phrase match is a reason to read the sentence.

Return a short verdict plus blocking and advisory findings with location,
evidence, consequence, and the reader need to satisfy. Suggest corrections to the
brief's requirements instead of sending replacement paragraphs to the next writer.

### Compare after the first-read verdict

For a rewrite, save the independent verdict before giving the reader reviewer
the original page. A fresh comparative reviewer can perform this second pass.
Compare task coverage, reading order, fluency, and unnecessary explanation. Count
words consistently and explain material growth by the specific reader needs it
serves. Required corrections or warnings can justify added length. A shorter page
with less coverage does not establish an improvement.

Block acceptance when added scaffolding, repeated advice, or broken transitions
make the candidate harder to read. Report when the original serves the reader
better, even if both versions pass factual checks. Preserve the original until a
replacement passes; user rejection outranks an agent's approval. Keep this report
and both pages out of all subsequent writer inputs.

## Resolve and recheck

Consolidate the two reports without hiding disagreements. Verify factual findings
against their sources. Fix demonstrated gaps within the user's authorized scope.
Ask the user when the evidence leaves a meaningful content or scope choice.

For a fresh draft, change the brief, obtain a new brief review, and use a new run
directory. The new writer gets neither rejected draft nor reviewer quotations.
Review the replacement independently. For a mechanical edit, check the affected
links or markup and retain the exact diff. Keep all prior artifacts in scratch.
