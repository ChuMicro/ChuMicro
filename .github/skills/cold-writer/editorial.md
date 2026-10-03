# Editorial direction

## Voice

The voice is defined once, in
[style-guide.md § Documentation tone](../../../docs/contributing/style-guide.md#documentation-tone),
with its audience and register. This file adds the craft a writer applies on top
of it: reading order, page format, composition, and layout. The isolated writer
receives a short positive instruction set; reviewers judge the draft against the
style guide section and the owner verdicts in [labels/](labels/). A registry
excerpt (`--voice chumicro-docs`) is an experiment, not the default.

Put architecture rationale in an explanation page when it helps the reader make
a decision. Use affirmative instructions where possible. Necessary prohibitions
remain explicit at the point of risk.

## Write in reading order

A reader proceeds top-down with only their starting knowledge and what the page
has supplied. Plan for that first reading.

- Introduce, then refer. Name an unfamiliar thing and explain its role on first
  use. A later definition cannot repair an earlier instruction that depends on it.
- Use “the” for an established or immediately identifiable referent. Introduce a
  new instance with “a” or “an”; use ordinary article-free forms for brand names.
  Judge each noun in context. Deleting articles mechanically damages fluency.
- Given before new. Begin a sentence from something the reader already holds and
  place the new fact where it can lead into the next sentence.
- Open a paragraph with its claim and use the remaining sentences to develop it.
  Keep one claim per paragraph, with enough connected prose to explain it.
- Put facts where a reader needs them. Reorder paragraphs when an earlier one
  depends on a later explanation. Research order does not determine reading order.
- Put action in the verb. Describe what a subject does. Use definitions when a
  category matters; repeated subject-plus-“is” sentences usually hide a process.

Use consistent names across explanation, code, diagrams, and expected output.

## Select the format

| Reader's need | Page format | What earns space |
|---|---|---|
| Get a first working result | Quickstart | Prerequisites, one supported path, unfamiliar concepts, meaningful success check |
| Learn by building | Tutorial | Outcome, parts, setup, connected steps, observations that explain a mechanism |
| Complete a known task | How-to | Preconditions, procedure, success check, relevant recovery |
| Look up an exact detail | Reference | Consistent entries, signatures, values, constraints, examples |
| Understand a mechanism | Explanation | Concrete scenario, mechanism, diagram, consequences, tradeoffs |
| Find a starting point | Landing page or README | Short purpose, a few task choices, working example, next links |

A tutorial's central sequence can link to parameter tables and architectural
background on other pages. Keep information required to succeed in the sequence.
For a mixed existing page, record where each retained topic will live before
splitting it. Preserve inbound links or update their known consumers.

Cover the task completely at the reader's level. Spend words on decisions,
unfamiliar behavior, and consequential risks. General Python or terminal lessons
belong only where the audience needs them. A verified fact earns page space when
it helps this reader act, understand the project's behavior, or make a choice.

## Page composition

- Open with what the reader will make or observe. State prerequisites before the
  first action that needs them. Avoid guessed completion times.
- Use headings that name tasks. Keep ordered steps for dependent actions and
  bullets for genuinely parallel items.
- Show expected output where it distinguishes success from a plausible failure.
  Related commands can share one checkpoint. Preserve variable fields such as
  device identifiers and label illustrative output.
- Show complete runnable examples when the page promises copy-and-run behavior.
  Label partial examples and supply their dependencies or a complete linked file.
- Keep commands separate from output. Establish the working directory and whether
  execution happens on the laptop, board, or REPL; restate only when it changes.
- Introduce one supported default path. Place alternatives at the point where
  users need them, with their applicability stated.
- End at the promised result, with a focused next link when useful. Include an
  experiment only when it teaches something the page promises.
- Group related instructions into readable paragraphs. Use a heading, list, or
  callout when it helps navigation or conveys structure, rather than for every fact.
- Put a concise recovery instruction beside a likely, actionable failure. Link
  broader troubleshooting instead of repeating generic error advice at each step.

## Pictures, callouts, and layout

Use a wiring diagram for connections, a photo for locating a physical part, and a
screenshot for recognizing a UI state. Add arrows or labels only when they answer
a specific question. Give diagrams a caption, readable labels, and useful alt
text. Text and symbols must carry any meaning also conveyed by color.

For circuits, confirm pin names, voltage, polarity, resistor values, board
variant, and orientation from the verified setup. Use circuit-drawing tools for
schematics. A generated illustration can decorate a page, but it cannot establish
electrical correctness.

Use a tip for an optional shortcut, a warning for a consequential risk, and a
troubleshooting note for a recognizable failure. Place each beside the relevant
step. A page covered in callouts needs a simpler sequence.

Use the destination site's existing components and image conventions. Review
desktop and narrow layouts for wide code blocks, tables, navigation, image labels,
and heading order. Keep essential commands selectable as text. Provide an ordinary
link when a specialized component lacks a supported rendering path.

## Use references for specific decisions

ChuMicro's audience and task set the voice. Use external documentation to answer
a concrete question about sequencing, navigation, or layout. Adafruit Learn can
inform a diagram or physical setup sequence; it supplies no default voice or
requirement for encouragement. A page may need no external model.

The launcher gives the writer a short positive instruction set. Source prose,
style complaints, and phrase-ban catalogs stay with reviewers. Reviewers assess focus and fluency together: removing necessary
connections makes prose shorter without making it easier to read.
