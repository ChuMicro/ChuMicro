# Writer brief template

Copy the sections below into a run's `brief.md` and replace their contents with
verified material. The reviewer checks the completed brief for old prose,
finished-sentence fact notes, and missing evidence. Omit empty optional sections. The launcher sends this file in
full, so keep research commentary in the separate ledger.

## Reader and outcome

- Page type and title.
- Reader's starting knowledge: general skills this page may assume.
- Project-specific concepts the reader needs to learn, in dependency order.
- One concrete result the reader will reach.
- Required equipment, software, versions, and accounts.
- Supported runtime and board variants for this page.
- Working length range appropriate to this scope; preserve needed context and risks.

## Verified facts

One telegraphic note per ID: subject, behavior, condition, consequence, as
fragments the writer turns into its own sentences. Never a finished sentence;
the writer relays finished sentences, and the page then inherits the
researcher's register. Mark each note required, supporting context, or linked
detail. Required notes enable the task, explain unfamiliar behavior, or prevent
a consequential mistake. Supporting context guides accurate wording; the writer
selects what this reader needs on the page. The evidence ledger holds source
locations and verification details.

Example note: `F04 required. sensor read: returns last cached value while bus busy;
cache age under 1 s; stale value never raises`.

## Exact commands and examples

For each example, state its ID, execution location, prerequisites, complete code,
expected result, and replaceable values. The writer may arrange and explain the
example; changes to its technical contents require verification.

## Page sequence

List sections in reading order. For each, name the reader's existing knowledge,
next task or concept, and relevant fact and example IDs. Name checkpoints or
illustrations only where they meet a specific need. The writer chooses headings
for these tasks; the orchestrator preserves legacy inbound anchors separately.

## Links and visuals

Provide approved labels and destinations. For each available image, give its
path, instructional purpose, caption facts, and alt-text facts. If an image has
not been produced, choose text that works without it and record the asset need
outside the publishable page.

## Publication requirements

Name supported Markdown components, required frontmatter,
footer requirements, and any exact strings needed by downstream consumers.
Keep legacy inbound anchor IDs in the orchestrator's preservation list.
Use periods, commas, colons, or parentheses to connect prose clauses. Describe
current behavior directly. Keep warnings tied to a specific action and risk.
