---
name: cold-writer
description: Writes focused user documentation from verified facts with a fresh writer that cannot read existing prose. Use when replacing a dense page, rebuilding a tutorial or quickstart, or requesting a clean-room rewrite. Produces a reviewed draft and evidence record. Do NOT use for critique-only audits (audit-docs), routine library-guide updates (guide-generation), source-comment audits (audit-comments), creating skills, or isolated typo fixes. May fetch selected public documentation examples for editorial research. Requires an authenticated Claude CLI and sends the complete reviewed brief for remote generation, using Opus by default; retains inputs, response, diagnostics, and receipt under repository .scratch/.
---

# Cold writer

Produce a readable documentation page through research, brief review, isolated
writing, and independent review. The deliverable includes Markdown, evidence for
its technical claims, and a record of the writer's inputs. Run the writer through
[scripts/write.py](scripts/write.py), which sends a reviewed brief to the user's
authenticated Claude CLI. The default model is `opus`.

## Invocation and scope

`/cold-writer docs/start-here.md` replaces that page within the user's requested
scope. Add `draft only` to keep the candidate in `.scratch/` for discussion.
An ordinary request to use the skill has the same effect. If the user names a
section, work on that section and inspect its neighbors for context.

Use this for quickstarts, tutorials, how-to guides, explanations, landing pages, and manually
written reference pages. A tutorial serves one learning outcome; a how-to serves
one practical task. Generated API pages remain owned by their generator.

The voice is defined once, in
[style-guide.md § Documentation tone](../../../docs/contributing/style-guide.md#documentation-tone).
Read [editorial.md](editorial.md) for reading order, page format, and composition.
Read [reference-library.md](reference-library.md) when selecting real examples of
instruction, navigation, or layout when the page needs a concrete design reference.

## Context boundaries

| Role | Reads | Produces |
|---|---|---|
| Researcher | Source, tests, commands, old docs, selected external references | Evidence ledger and factual brief |
| Brief reviewer | Brief, ledger, source evidence, user requirements | Readiness report |
| Writer | Approved brief and the short writer prompt | One fresh draft |
| Technical reviewer | Draft, ledger, source evidence | Accuracy and coverage findings |
| Reader reviewer | Draft, audience, outcome, editorial criteria; original page only after recording a first-read verdict | Comprehension, voice, and regression findings |

The writer receives no old page, previous draft, conversation transcript, review
quotations, repository instructions, or access to browsing and file tools. Keep
code, commands, necessary error strings, and link targets exact. Express every
other fact as a telegraphic note, never a finished sentence: the writer relays
finished sentences, and the page then inherits the researcher's register. The
writer's only register input is the excerpt in
`_shared/voices/voice_samples/chumicro-docs.md`, which the launcher sends.

The orchestrator retains repository rules and responsibility for verification,
permissions, file changes, and delivery. Its familiarity with the sources biases
its reading. Independent reader findings outrank orchestrator observations.
Present those findings first and label any orchestrator disagreement. Resolve
disputed findings through cited evidence or a fresh independent review;
orchestrator preference alone cannot dismiss them.

## Process

### 1. Define the page

Record the target path, what the reader already knows, what ChuMicro introduces,
one observable outcome,
documentation type, runtime/board assumptions, and draft-only or apply scope.
Use the user's choices and available context. Ask only about missing choices
that would change the result. Keep existing URLs, anchors, and publication
requirements in a preservation list. Legacy inbound anchor IDs stay with the
orchestrator so old heading wording does not enter the writer's context.

In Claude Code, use `AskUserQuestion` for missing choices, with `multiSelect` when
several options may apply and previews when comparison is visual. In another
host, use its available question tool or a self-contained question in chat.

For ChuMicro's first-run pages, assume basic Python and ordinary terminal use,
then identify the unfamiliar board and project concepts the page must explain at
first use. Choose a quickstart when
the reader needs a first working project; use a tutorial when teaching a mechanism
is itself the goal. State where commands run once, then mark changes of location.

**Success criteria:** the page's outcome and prerequisites are concrete, and the
chosen scope covers the user's request without silently expanding to other pages.

### 2. Research and prepare evidence

Follow [research-and-brief.md](research-and-brief.md). Create a unique directory
under `.scratch/cold-writer/` and keep all run artifacts there. A research agent
may inspect the existing page. Verify its claims against current sources before
carrying them forward. Read the code on both sides of cross-package behavior.

Record every retained fact, command, example, and required warning with its
source, applicable version/runtime, and verification level. Confirm command
spellings with `--help`. Distinguish source inspection, host execution, and board
observation. Use existing evidence or an explicitly authorized device session
for hardware claims. External tutorials inform design; ChuMicro sources establish
ChuMicro behavior.

Keep reference prose outside the writer's inputs. For frequently changing pages,
prepare the optional maintenance index in [research-and-brief.md](research-and-brief.md).

**Success criteria:** each required claim has evidence, uncertainty is visible,
and every necessary safety or data-loss condition is preserved.

### 3. Review the brief before writing

Draft `brief.md` using [brief-template.md](brief-template.md). Send a fresh review
agent only the brief, evidence ledger, named source files, and user requirements.
Use the brief-review contract in [review.md](review.md). Give it the SHA-256 of
the exact brief bytes and save its response as `brief-review.json`.

The reviewer checks factual accuracy, essential coverage, reader sequence, and independence
from old prose. It resolves source discrepancies or reports blocking gaps. Correct
the brief and re-review when necessary. A research summary alone cannot verify
a claim; re-read the cited source or run the smallest relevant check.

**Success criteria:** the independent review approves all four checks, has no
blocking findings, and identifies the exact brief hash. An incomplete brief stays
in research.

### 4. Write in isolation

Read [execution.md](execution.md). From the repository root with its virtual
environment active, run `python .github/skills/cold-writer/scripts/write.py --help`.
Use that same script path with `--brief`, `--review`, and a new `--run-dir` beneath
`.scratch/` for the drafting call. `--voice` defaults to `chumicro-docs`, the
register excerpt the writer matches; `--voice plain` sends no excerpt and exists
for control runs only.
Use a background execution handle for the model call and continue independent
work while it runs. Report progress when a stage changes.

The script checks the review hash, confirms the required CLI flags, saves the
exact prompt and response stream, and rejects tools, loaded extensions, failed
responses, and empty output. Read its receipt before treating `draft.md` as a
candidate. Infrastructure failure returns to execution diagnosis, not writing.

**Success criteria:** a new draft and receipt exist, the receipt records a
successful response with no tools or extensions, the saved system prompt holds
only the writer instructions and the register excerpt, and the run's `brief.md`
matches the reviewed bytes.

### 5. Review the draft independently

Run the echo gate first:
`python .github/skills/cold-writer/scripts/echo_check.py --brief <brief> --draft <draft>`.
It counts the prose sentences that share a run of words with the brief and exits
1 above its threshold. A failing draft goes back to the brief, whose echoed notes
need to be more telegraphic, and then to a fresh writer; it is not a mechanical
repair.

Dispatch the technical reviewer and reader reviewer in parallel with their
separate input sets from [review.md](review.md). Run command and example checks
appropriate to the page. Review supported runtime differences, relative links,
anchors, navigation, and images in the destination renderer.

Restore required inbound anchors as markup beside the corresponding sections or
links. Retain a mapping and diff, preserve the writer's prose, and check that each
ID resolves to its intended content without duplicate IDs.

Have the reader reviewer assess the draft top-down before seeing the original.
Then compare coverage, length, and fluency against the original using
[review.md](review.md). A tutorial can also receive a simulated task rehearsal.

Keep the review criteria outside the writer's context. A reviewer may flag
tombstones, litotes, invented vocabulary, or repetitive explanations. It must
also check introduced referents, given-before-new transitions, paragraph claims,
useful context, and task completion. Extra detail must meet a reader need. Word
counts locate expansion; they cannot establish readability or justify lost context.

For substantive failures, repair the brief using factual requirements and start
a fresh writer. Keep rejected drafts out of the new input. Allow at most two
fresh redrafts per page. After two fresh redrafts, present each remaining blocker
with its cited evidence, consequence for the reader, and exact proposed brief or
page change in the same message as the decision request. Recommend one option.
For missing evidence, identify the precise fact or observation the user must supply.
Mechanical repairs to links or markup can be made directly, with a recorded
diff and another check of the affected output. A user-requested sentence edit
can be performed directly and reviewed at that scope.

**Success criteria:** the echo gate passed; accuracy and reader reviews have no
unresolved blockers;
required claims, commands, warnings, and links remain present; comparison finds
no unexplained loss of focus or fluency; verification records state what ran.

### 6. Apply and deliver

For draft-only runs, show the candidate and review findings from `.scratch/`.
For an authorized rewrite, apply the accepted draft with file-editing tools.
Re-read the target first to preserve concurrent changes. Update navigation,
inbound anchors, and templates only where the changed page requires it. Follow
repository gates and task-checkpoint requirements for the changed unit.

Show the result, important structural choices, tests performed, and any remaining
hardware or human checks. Link the maintenance index when one was produced.
Commit, push, and publish only with the required user
authorization. The writer process itself never edits the destination document.

**Success criteria:** the requested draft or applied page is reviewable, its
evidence and run receipt are locatable, and the user can distinguish completed
verification from outstanding work.

## Done when

- The requested page or draft supports its stated reader and outcome.
- Technical and reader findings are resolved or explicitly disclosed as blockers.
- Writer input isolation is recorded, its actual tool list is empty, and the echo
  gate passed.
- Required behavior, warnings, public links, and publication structure survive.
- The final handoff links the artifact and states its verification limits.

Run [TESTPLAN.md](TESTPLAN.md) when changing the launcher or workflow. Routing
cases live in [trigger-evals.json](trigger-evals.json).
