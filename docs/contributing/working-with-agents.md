# Working with AI Agents

<img src="https://chumicro.com/assets/chumicro-head.png" alt="" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

AI coding agents work in this repository under written rules and explicit patterns, and pass the same gates as human contributors.

<br clear="left">

## What agents do in this workspace

An AI coding agent reads code, proposes changes, runs tests, and iterates. Here agents handle much of the repetitive work:

- **Writing tests** to hit the coverage gate
- **Generating documentation** from code and docstrings
- **Scaffolding** new libraries, examples, and boilerplate
- **Fixing lint errors** and formatting issues
- **Exploring the codebase** to answer "how does X work?" questions

Agents follow the same rules as human contributors: they run preflight, their code goes through review, and their pull requests pass CI.  They also follow a stricter rule set, [`AGENTS.md`](https://github.com/ChuMicro/ChuMicro/blob/main/AGENTS.md), because they need explicit instructions for things people do by instinct, like "fix only what was asked" or "check whether this was already decided."

## What stays with a human

- **Design direction:** choosing the right abstraction matters more than generating code quickly
- **Code review:** agent-generated pull requests get the same scrutiny as any other
- **Hardware testing:** agents can't plug in an ESP32
- **Judgment calls:** whether an API *feels* right to use, whether a tradeoff is worth it

## How to set up an agent for this project

An AI coding tool such as Claude Code, Cursor, or GitHub Copilot picks up the project's rules from these files:

1. **`AGENTS.md`** in the project root holds the full rule set. Most AI tools detect and follow it automatically.
2. **The `.github/skills/` directory** has step-by-step instructions for common tasks: committing, testing, creating libraries. Agents read these before acting.
3. **`plans/decisions/`** tells agents *why* the code is shaped the way it is, so they skip proposals already considered and rejected.
4. **[The agent style guide](agent-style-guide.md)** holds the worked examples, the per-noun article test, and the AI-tic regex behind the writing rules in `AGENTS.md`.

### Quick start with an agent

```
Human: "Add a test for ticks_add with a negative delta at the wraparound boundary"

Agent: reads the codebase, writes the test, runs it, checks coverage,
       runs preflight, and commits when you ask it to.
```

```
Human: "Add a timing example that blinks two LEDs at different rates"

Agent: reads the timing guide and the existing examples, writes the file
       with both blinks inside one while True: loop, runs verify-examples
       and preflight, ready for review.
```

The agent does the mechanical work. You steer the design and review the result.

## Frame intent before invoking a skill or task

A procedural skill, such as `task-checkpoint`, `git-commit`, or `new-decision`, owns its procedure and runs well from the bare command. A task that needs judgment, such as an audit, a code review, a design, or a refactor, goes better with a sentence or two of intent first:

```
Direct cold:   /audit-comments libraries/mqtt
Better:        "The mqtt library went through three refactor passes recently
                and the comments feel inconsistent, and I want to know which are
                still load-bearing vs residue. /audit-comments libraries/mqtt"
```

That opening tells the agent:

- **Scope:** what you actually care about, such as "which are load-bearing" in place of "audit all"
- **Motivation:** why now, which sets which findings come first
- **Expected output:** what good looks like, such as a useful punch-list in place of an exhaustive one

Without that opening, the agent produces generic skill output and needs two to four rounds of steering. With it, the first output usually lands close.

Rule of thumb: a skill that produces a **judgment**, such as audit findings, design recommendations, or review feedback, gets framing first. A skill that **executes a procedure**, such as a commit, a scaffold, or a refresh, runs fine cold.

In a long session, restating *"what we're solving here is X"* now and then pulls the agent back to the main question when focus drifts.

## What to expect from agent behavior here

- **Agents close each unit of work with the `task-checkpoint` skill**: preflight, then the docs and planning files the change touched.  They commit only when you ask, staging files by name so your own uncommitted work stays out.
- **Agents hold the libraries they change to 94 % coverage**, above the 85 % `pyproject.toml` baseline that humans and untouched libraries keep.  A coverage failure showing `94.0%` comes from this gate ([Decision 0025](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0025-dual-coverage-thresholds.md)).
- **Agents confirm what a terse reply means.**  After a "yes" or "option 2" a few exchanges in, an agent states which option it understood before acting, so it never acts on the wrong one.
- **Agents surface tradeoffs before choosing among options.**  They name the approaches and call out ambiguity.
- **Agents push back when something looks wrong.**  A factual disagreement followed by reasoning is the rule working as intended.

## Tips for productive collaboration

- **Be specific about what to ask for.**  "Add edge-case tests for `Rate` near tick wraparound" beats "improve tests."
- **Give your reason when you say no.**  "No" bounces a recommendation.  "No, because X" teaches the agent how you think, and the next proposal lands closer.
- **Name the thing when you'd reply tersely.**  A short answer like "yes" or "option 2" assumes you and the agent still mean the same thing.  After a few turns that drifts, and "yes, split the file" keeps the agent on the right option.
- **Grant broader autonomy after small wins.**  Reversible local work runs fine on a short leash.  Save confirmation for destructive or scope-expanding moves.  Trust builds across turns.
- **Let the agent read first.**  An agent that reads `AGENTS.md` and the relevant library code before writing produces much better output.
- **Review what it produces.**  Agents write plausible code quickly, and plausible code can still be wrong.  Read the diff like any other pull request.
- **Use agents for the boring parts.**  Coverage gaps, docstring formatting, example scripts, and boilerplate save the most time at the least risk.

## When a session feels off

When the agent keeps missing the point, through repeated misreadings or output that misses, check the tips above first: terse replies and unexplained "no"s cause most of it.  Other causes:

- **An underspecified task.**  "Fix this" assumes the agent knows what "this" and "fix" mean.  One sentence naming the problem and what good looks like saves several rounds.
- **A conversation drifted too far to recover.**  Start a fresh session with a clear opening statement of the goal, instead of steering the old one back.

When the agent still loses track, state the goal outright: "I want to accomplish X. What's blocking that?"

## First time using an agent

`AGENTS.md` and the skills already teach an agent the project's rules, so a first agent session can start small:

- Ask it to explain how a library works
- Ask it to write a test for an uncovered code path
- Ask it to write an example that does one thing, then keeps blinking or printing inside a `while True:` loop

## Why this is set up this way

`AGENTS.md`, the skills, and the decision records take mechanical work, such as coverage, formatting, and boilerplate, off contributors, so their time goes to API design, new libraries, and hardware integration.
