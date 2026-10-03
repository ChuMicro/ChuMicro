# Workstream: docs overhaul through cold-writer

Status: active

## Goal

Organize documentation and teaching material around what the reader wants to do:
run a first program, adapt a project, or build a library. Every user-facing page
under `docs/` (the guides site, excluding `docs/contributing/`) is rewritten
through the cold-writer skill in the register the owner accepted on the start-here
trial: telegraphic brief, independent brief
review, one isolated plain-voice draft, echo gate, blind reader and technical
reviews, then the page applied on `docs/cold-writer` with legacy anchors
restored as markup. Owner reads each page after it lands; a rejection goes back
to the brief, never to a prose edit.

## Scope and order

| Order | Page | Type | Words today |
|---|---|---|---|
| 1 | `docs/start-here.md` | quickstart | 755 |
| 2 | `docs/index.md` | landing | 239 |
| 3 | `docs/install.md` | how-to matrix | 901 |
| 4 | `docs/wiring-wifi-credentials.md` | how-to | 619 |
| 5 | `docs/troubleshooting/README.md` | landing | 516 |
| 6 | `docs/troubleshooting/board-not-found.md` | how-to | 725 |
| 7 | `docs/troubleshooting/firmware-onto-a-new-board.md` | how-to | 511 |
| 8 | `docs/troubleshooting/deploys-and-file-persistence.md` | how-to | 565 |
| 9 | `docs/troubleshooting/wifi-wont-connect.md` | how-to | 684 |
| 10 | `docs/troubleshooting/tls-https-failures.md` | how-to | 557 |
| 11 | `docs/troubleshooting/out-of-memory.md` | how-to | 359 |
| 12 | `docs/troubleshooting/deploy-refused-importerror.md` | how-to | 453 |
| 13 | `docs/troubleshooting/persisting-data.md` | how-to | 440 |
| 14 | `docs/troubleshooting/board-quirks.md` | reference | 693 |
| 15 | `docs/troubleshooting/circuitpython-ringio.md` | explanation | 562 |
| 16 | `docs/troubleshooting/macos-circuitpy.md` | how-to | 1755 |
| 17 | `docs/faq.md` | explanation | 2089 |

The owner's audience requirements also cover the root README, demo introductions,
and library examples. Review their entry points, reading order, and primary
learning task before continuing the page queue. This replaces the earlier root
README exclusion for that framing work. The list above is the original page
queue, not the full inventory of teaching material.

Library implementation changes and wholesale contributor/library-guide rewrites
remain outside this workstream. Existing guide-generation ownership remains;
record cross-page changes needed for a coherent reader route.

## Audience and learning requirements

The owner distinguishes three reader goals. A person may choose a different goal
on a later visit. Each page, example, or demo has one primary goal; it does not
teach all three at once.

| Reader goal | What the reader needs first | Appropriate depth |
|---|---|---|
| Beginner: follow the script | Run a complete program, recognize its output, write or change the visible `while True` loop | One supported path, prerequisites, exact commands, complete code, expected behavior, one concrete change to try. Programming knowledge is learned as needed. |
| Intermediate: stray from the script | Combine libraries, change behavior, replace a component, diagnose the result | Worked variations, configuration, failure handling, project inspection, and dependency injection at the point of use. |
| Advanced: write the script | Understand generator-based cooperative multitasking and build or contribute a library | Loop ownership, suspension and resumption, service and wait contracts, cancellation and cleanup, injected dependencies, runtime behavior, tests, and measured costs. |

- Beginner material exposes the application loop. Generator mechanics, scheduler
  internals, and the async comparison belong in linked advanced material.
- Advanced readers can enter through the generator and library-authoring material
  directly, without completing a beginner project first.
- Intermediate material connects a working example to a deliberate variation.
  It does not repeat the complete setup or require a library-authoring lesson.
- A beginner example gives the reader a complete first result and an ordinary
  place to change it. A specialized generator or benchmark example may have an
  advanced audience; its introduction and discovery path must say what knowledge
  it assumes. Every example need not become a beginner tutorial.
- Demos offer a complete runnable result. Their host automation and assertions
  remain useful for testing; the beginner's program and instructions explain the
  behavior being demonstrated. Protocol internals, harness contracts, and design
  comparisons receive a separate advanced entry point.
- README entry points distinguish running, adapting, and authoring. Shared
  identity and project commitments appear once. Each route then links to the
  material that serves its reader, rather than inserting all three explanations
  into every example.
- Preserve the explicit-loop requirement in Decisions 0122 and 0123. Their
  blanket beginner framing does not make every specialized artifact introductory;
  the owner's primary-audience requirement governs the new material.

## Engineering commitments to explain

These are owner requirements for the documentation. Research distinguishes
implemented capability, enforced policy, measured result, and desired commitment
before turning any item into a factual claim.

| Commitment | Required treatment |
|---|---|
| Cooperative multitasking | The application owns its `while True`; generators express sequential work that cooperates with other jobs. Explain the mechanism first for advanced readers and show the visible loop first for beginners. |
| Respectful async comparison | Separate loop ownership, coroutine syntax, scheduler behavior, runtime implementation, debugging, and allocation costs. Cite the relevant runtime version and evidence. Explain ChuMicro's choices without disparaging async or treating every `yield from` as a guaranteed scheduler handoff. |
| Dependency injection | Demonstrate using a library with supplied sockets, transports, clocks, and timing helpers. MQTT is the concrete standalone example. Distinguish imports at runtime, acquired dependencies, and files deployed; verify each claimed closure independently. |
| Two board runtimes | Explain MicroPython and CircuitPython support and deployment filtering for the selected target. Verify what the file map omits; distinguish runtime-exclusive files from common files that still contain runtime branches. CPython remains the host test seam. |
| Examples and tests from the start | Examples, demos where appropriate, automated coverage of at least the owner's 90% baseline, and deliberate real-board/manual testing belong in the contribution story. Existing stricter gates remain in force. Show measured results separately from policy. |
| Resource measurements | Make RAM use, allocation churn/fragmentation, flash cost, hot paths, and comparisons over time discoverable. Name the workload, runtime, board or host seam, metric, baseline, and regression gate. Do not turn a proxy such as zero net allocation into a broader fragmentation guarantee. |
| Library contribution | Welcome a library or an idea and explain the project's packaging, publishing, and hosting support. Show what the contributor supplies and what the project automates. |
| Publication continuity | Retain published versions when the original author stops supporting a library. The owner selected continued availability; active maintenance is not promised by this requirement. Verify release/hosting policy before stating an existing guarantee. |
| Board workflow | Make firmware installation, project deployment, live output/state inspection, and inspection or recovery of deployed files easy to find. The owner explicitly requires both live observation and file access. Document lossy deployment transformations and limits on recovering the original project. |
| Agent-assisted work | Show concrete ways an agent can inspect, diagnose, deploy, and test, with observable results and the same device-operation safeguards as a human workflow. |

### Evidence constraints for the rewrite

- Decision 0025, root `pyproject.toml`, and `.github/workflows/ci.yml` establish
  an 85% default coverage floor and a scoped 94% agent gate. Align the policy and
  gates before advertising the owner's 90% baseline as universal enforcement.
  Coverage is measured on the CPython-reachable, post-exclusion subset; physical
  testing remains a separate requirement.
- `MQTTClient` accepts a supplied socket and clock. A source-derived import-graph
  check with `__chumicro_skip_factories__` removes sockets but still includes
  timing, config, and msgpack. The standalone-runtime claim and the deployed-file
  claim require separate instructions and evidence. This is a capability gap to
  resolve before promising automatic omission of every default dependency.
- The audience review sampled README, timing examples, MQTT receive-stream, and
  the sockets generator demo. It found useful material with different learning
  jobs, rather than evidence that every example should be simplified. It also
  found a sockets demo README that says its loop exits while `app.py` runs
  forever; correct that contradiction when editing the page.
- Source reviews of benchmarks, publication, runtime filtering, and board-file
  access are in `.scratch/cold-writer/priorities-quality.md` and
  `priorities-architecture.md`. Re-derive any unconfirmed result before using it
  in a brief. In particular, allocation churn is not fragmentation, historical
  async research is not proof of current upstream behavior, and REPL output is
  not a complete source-recovery workflow.

## Audience mapping and implementation

1. Inventory the README entry points, demos, and examples; assign a primary reader
   and a single learning task to each. Keep useful advanced examples advanced.
2. Map the beginner path from firmware and first deployment through an explicit
   loop, an edit, and observing the changed running program. Map the intermediate
   variations and a direct advanced generator/library-author route.
3. Reconcile source evidence with the engineering commitments above. Put a
   capability gap or unsupported promise in the research record, not in a draft.
4. Revise the three held page briefs for this audience map. The prior Start-here
   brief assumes basic Python and ends with a changed greeting; that alone does
   not satisfy the owner's request to teach writing the loop. Keep generator
   internals out of this beginner brief. Recheck Install and WiFi route audiences
   and prerequisite links at the same time.
5. Independently review the revised briefs, then resume isolated generation and
   the unchanged quality gates under the owner's continuation authorization.
   Architecture and page responsibilities are recorded in
   `.scratch/cold-writer/system/architecture.md`.

The task routes and curated teaching inventory are recorded in
`.scratch/cold-writer/system/teaching-map.md`. The contributor style guide now
requires one primary task per page, example, or demo. This replaces its previous
requirement to serve beginners and advanced readers inside the same sentences,
as directed by the owner.

The revised Start-here brief teaches a visible counter loop alongside a periodic
greeting. Its stable Runner dependency and complete program were checked on the
host. The advanced page has a direct generator entry; the board guide separates
output observation, runtime-specific REPL state, and deployed-file recovery.
Firmware instructions cover unregistered boards before workbench-only commands.

## Per-page procedure

1. Research into `.scratch/cold-writer/<page>/evidence.md`; every command
   spelling confirmed with `--help`, every link target opened.
2. Telegraphic `brief.md`; fresh Opus brief review against the exact hash.
3. One `write.py` run, default voice; echo gate; blind reader and technical
   reviews in parallel. A blocker returns to the brief and a fresh writer, two
   redrafts at most.
4. Apply with the file tools, restore legacy anchors from the page's
   preservation list, fix inbound descriptions on sibling pages, build the
   guides site, run preflight.
5. Owner verdict recorded in `.github/skills/cold-writer/labels/`.

## Page constraints found during research

- `docs/install.md` names the workbench folder `my-workbench` (the template
  README's name); it ships in the same commit as the start-here rewrite or after
  it, because the committed start-here still says `my-workspace` (install ledger
  R31).
- `docs/troubleshooting/firmware-onto-a-new-board.md` is linked from the install
  page for readers who have no workbench; its rewrite gives them a route that
  does not run `chumicro-workspace install-firmware` (install technical review
  A9).
- The start-here off-ramp for CircuitPython or another board sends the reader
  to the firmware page, which today gives no CircuitPython image source
  (start-here writer-9 reader review 3); the firmware page's rewrite covers it.

## Validation history

- 2026-09-27: start-here trial 4 accepted by the owner ("plain looks good"); the
  plain-voice run became the default and the first label. Overhaul opened with
  start-here retuned first (brief-5 closes the gaps the four reviews named).
- 2026-09-28: Claude exhausted its usage with three pages in progress and the
  skill's redraft cap already exceeded. The owner authorized Codex writers and
  reviewers and one additional draft for each active page. This bounded exception
  replaces the Claude/Opus requirement for those runs; it changes no quality gate.
- 2026-09-28: all three authorized Codex runs completed. Start-here writer-12
  failed echo at 20.0%; install writer-5 at 18.4%; WiFi writer-6 at 18.0%, against
  15%. Install and WiFi passed independent reader and technical reviews. Start
  here needs grouped recovery instructions, usable pre-registration firmware
  links, removal of an unsupported BOOTSEL time bound, and punctuation repairs.
  All three destination pages remain unchanged; fourteen other pages remain
  queued. Further drafting needs an owner decision under the exhausted cap.
- 2026-09-28: full preflight passed with 11,333 tests across its phases; launcher
  tests passed 28/28 and echo tests 8/8. The three-candidate local preview built
  without warnings and passed legacy-anchor and local-link checks. Physical
  board acceptance and owner voice verdicts remain outstanding. Evidence and
  continuation details: `.scratch/cold-writer/codex-recovery.md`.
- 2026-09-28: owner specified separate beginner, intermediate, and advanced
  learning goals, advanced emphasis on generators, beginner emphasis on the
  visible loop, and the engineering commitments above. Owner clarified board
  inspection includes live output/state and deployed files; publication
  continuity means keeping published versions available. New audience planning
  precedes further drafting. Reviewed samples and source evidence are recorded
  under `.scratch/cold-writer/priorities-*.md`.
- 2026-09-28: owner directed the actual documentation overhaul using the new
  audience requirements and verified source. This authorizes continued Codex
  drafting/review beyond the exhausted numerical cap for the overhaul; quality
  gates remain unchanged. Implement task-based navigation, a direct advanced
  generator entry, and the revised beginner/project routes while preserving URLs.
- 2026-09-28: audience packets verified against source and published Runner;
  linked scheduling and dependency guidance corrected locally. Both manual
  generator drivers passed host checks; Runner and guides builds passed.
  Isolated drafting awaits the explicit payload/destination authorization
  required by automatic approval review. No new main-route draft applied.

- 2026-10-02: owner authorized the ten reviewed briefs for the configured OpenAI
  Codex service. Applied ten independently reviewed main-route drafts, legacy
  anchor markup, task navigation, and landing-page routes. First-loop and
  generator programs passed host checks. Strict guides build, all legacy IDs,
  335 local rendered links, mobile layout, and all thirteen preflight phases
  passed (11,335 tests), including final landing refinements and FAQ anchor
  parser regressions and the NTP UDP-factory contract correction in standalone
  integration. Board behavior remains unobserved.
- 2026-10-02: all twelve remaining FAQ/troubleshooting briefs passed independent
  source review. Corrected deployment-layout flags, runtime clock conversion,
  default TLS trust, storage reversal and host-recovery checks before drafting.
  Exact inputs/reviews are indexed in
  `.scratch/cold-writer/system/remaining-briefs-manifest.md`. Additional outbound
  payload authorization remains pending; destination pages are unchanged.

## Current continuation

The isolated Codex adapter and its limitations are recorded in
`.scratch/cold-writer/codex-execution.md`. A successful saved receipt establishes
the writer input and observed tool use, not factual correctness. Preserve that
distinction when resuming this work.

The revised packets live under `.scratch/cold-writer/`:

| Page | Brief | Independent review |
|---|---|---|
| Start here | `calibration/brief-6.md` | `brief-6-review-3.json`; writer 15 applied with first-loop host checks |
| Installation | `install/brief-17.md` | `brief-17-review-3.json`; writer 8 applied with runtime-build requirements |
| WiFi | `wiring-wifi/brief-23.md` | `wiring-wifi/brief-23-review-2.json`, ready |
| Generator explanation | `cooperative/brief.md` | `brief-review-3.json`; writer 4 applied with exact host invocation |
| Firmware | `firmware/brief.md` | `brief-review-3.json`; writer 2 applied |
| Board inspection | `board-workflow/brief.md` | `brief-review-2.json`; writer 1 applied |
| Examples catalog | `examples/brief.md` | `brief-review-3.json`; writer 1 applied |
| Guides entry | `guides-index/brief.md` | `brief-review-2.json`; writer 2 applied |
| Root README | `readme/brief.md` | `brief-review-3.json`; writer 2 applied |
| Quality and resource costs | `quality/brief.md` | `brief-review-3.json`; writer 2 applied |

The owner explicitly authorized sending the reviewed documentation briefs to
the configured OpenAI Codex service. Isolated drafting has resumed. The saved
app model was rejected by the CLI before generation; retries use the
`gpt-6-astra`/`xhigh` configuration recorded in the successful earlier writer
receipts. Each run retains its actual model, input, diagnostics, and outcome.

Runner, standalone-integration, slimming, and style-guide corrections are applied
locally. Manual generator drivers passed host checks for completion during
priming, a socket retry before its timeout, and cleanup. The Runner and guides
sites built successfully. Independent review accepted those four linked guides.
The full preflight passed with 11,333 tests; its complete output is saved in
`.scratch/cold-writer/system/overhaul-corrections-preflight-retry.log`.
Three demo introductions and their app docstrings match the actual loop
lifetimes, retry behavior, and allocation scope. Final review accepted the
socket-mode correction and synchronous-DNS explanation. The ten main-route
drafts passed the echo gate, independent first-read and technical reviews;
replacement pages also passed comparison against their originals. WiFi writer 8
is applied using its corrected audience review. Application records retain
legacy-anchor mappings; no substantive prose edits were made after drafting.

The guides navigation and generated landing page route readers by task.
Rendered link/layout checks and the repository gate passed. The acceptance
record is `.scratch/cold-writer/system/main-routes-acceptance.md`; the complete
gate output is `system/overhaul-complete-main-preflight.log` under the same scratch
root. Owner voice acceptance and physical-board rehearsal remain outstanding.
FAQ, the troubleshooting index, and ten remaining troubleshooting pages remain
in the original queue. All twelve source briefs and independent reviews are
ready. `system/remaining-briefs-manifest.md` and its JSON companion index the
exact 69,094-byte input set. The previous outbound approval named the ten
main-route briefs; request one authorization for these twelve additional
inputs and their reviewed revisions before invoking isolated writers. No board
operations, commit, push, or publication have been performed.

Keep the 15% echo limit, independent reader and technical reviews, and owner
verdicts. Do not repair prose mechanically to make a failed echo check pass.
