# Working with AI Agents

<img src="../../support/docs/chumicro_tip.png" align="left" width="64" style="margin-right: 16px; margin-bottom: 8px;">

This project is set up to work well with AI coding agents. The rules are documented, the patterns are explicit, and agents follow the same gates as human contributors. This page explains what agents do here, what to expect from their behavior, how to collaborate effectively, and what to do when a session feels off.

<br clear="left">

## What agents do in this workspace

An AI coding agent reads code, proposes changes, runs tests, and iterates, like a fast pair programmer that doesn't get tired. In this project, agents handle a lot of the repetitive work:

- **Writing tests** to hit the coverage gate
- **Generating documentation** from code and docstrings
- **Scaffolding** new libraries, examples, and boilerplate
- **Fixing lint errors** and formatting issues
- **Exploring the codebase** to answer "how does X work?" questions

Agents follow the same rules as human contributors: they run preflight, their code goes through review, and their PRs must pass CI. The difference is that agents have a stricter rule set ([`AGENTS.md`](https://github.com/ChuMicro/ChuMicro/blob/main/AGENTS.md)) because they need explicit instructions for things humans intuit, like "don't reformat code you didn't change" or "check whether this was already decided."

## What agents don't replace

Agents are capable tools, but some things still need a human in the loop:

- **Design direction:** choosing the right abstraction matters more than generating code quickly
- **Code review:** agent-generated PRs get the same scrutiny as any other
- **Hardware testing:** agents can't plug in an ESP32
- **Judgment calls:** whether an API *feels* right to use, whether a tradeoff is worth it

## How to set up an agent for this project

If you're using an AI coding tool (Claude Code, Cursor, GitHub Copilot, etc.), pointing it at this workspace makes it productive immediately:

1. **`AGENTS.md`** in the project root contains the full rule set. Most AI tools detect and follow it automatically.
2. **The `.github/skills/` directory** has step-by-step instructions for common tasks (committing, testing, creating libraries). Agents read these before acting.
3. **`plans/decisions/`** gives agents context about *why* the code is shaped the way it is, so they don't propose changes that were already considered and rejected.
4. **[The agent style guide](agent-style-guide.md)** carries the prose-tone rules for anything an agent writes: comments, docstrings, commit messages, and markdown. AGENTS.md keeps the everyday firing rules at top-of-mind, and this is the long-form reference behind them.

### Quick start with an agent

```
Human: "Add a test for ticks_add with a negative delta at the wraparound boundary"

Agent: reads the codebase, writes the test, runs it, checks coverage,
       commits with a proper message, done.
```

```
Human: "Create a new library called 'settings' for persistent key-value storage"

Agent: runs the scaffold command, generates starter code following the
       project patterns, writes tests to pass the coverage gate, builds docs,
       ready for review.
```

The agent does the mechanical work. You steer the design and review the result.

## Frame intent before invoking a skill or task

A common reflex with AI tools is to open with the direct command: `/audit-comments libraries/mqtt`, or "refactor the http_server module," or "fix this." That works for well-scoped procedural skills (`task-checkpoint`, `git-commit`, `new-decision`).  They own the procedure and don't need framing. For anything involving judgment (audits, code review, design, refactoring), opening with a sentence or two of intent saves several rounds.

```
Direct cold:   /audit-comments libraries/mqtt
Better:        "The mqtt library went through three refactor passes recently
                and the comments feel inconsistent, and I want to know which are
                still load-bearing vs residue. /audit-comments libraries/mqtt"
```

The preamble gives the agent three things the bare command doesn't:

- **Scope:** what you actually care about ("which are load-bearing" not just "audit all")
- **Motivation:** why now (informs which findings to prioritize)
- **Expected output shape:** what good looks like (a useful punch-list, not an exhaustive one)

Without preamble, the agent produces generic skill output, and you spend 2-4 rounds steering toward what you actually wanted. With preamble, the first output usually lands close.

Rule of thumb: if the skill produces a **judgment** (audit findings, design recommendations, review feedback), frame first. If it produces a **procedure execution** (commit, scaffold, refresh), cold is fine.

For longer sessions, periodically restating *"what we're solving here is X"* pulls the agent back to the load-bearing question when focus drifts. Cheap signal, large effect.

## What to expect from agent behavior here

Agents working under this project's rule set behave somewhat differently than agents in a generic workspace. Worth knowing as a collaborator:

- **Agents commit after each coherent unit of work** via the `task-checkpoint` skill: preflight, plans-doc refresh, commit, push. The tree stays clean across collaboration boundaries.
- **Coverage gate runs at 94 % on agent invocations** (humans target the 85 % pyproject baseline). A coverage failure showing `94.0%` is from this gate, per [Decision 0025](https://github.com/ChuMicro/ChuMicro/blob/main/plans/decisions/0025-dual-coverage-thresholds.md).
- **Agents restate your message when a terse reply could mean multiple things.** If you say "yes" or "option 2" after a few exchanges, expect a "confirming you mean X" before action. That's the rule firing, not the agent being slow.  It prevents acting on the wrong referent.
- **Agents surface tradeoffs before executing multi-option choices.** They name approaches and call out ambiguity. Rule firing, not indecision.
- **Agents push back when something looks wrong.** A factual disagreement followed by reasoning is the rule working as intended.

## Tips for productive collaboration

- **Be specific about what to ask for.** "Add edge-case tests for heartbeat near wraparound" is better than "improve tests."
- **Push back with reasoning, not just "no."** "No" bounces a recommendation. "No because X" teaches the agent your model, which is much higher-leverage feedback.
- **Restate when you'd reply tersely.** A 3-word answer like "yes" or "option 2" assumes you and the agent still share the same model. After a few turns, that model can drift.  Restating the referent prevents the agent acting on the wrong one.
- **Grant broader autonomy after small wins.** Reversible local work is fine on a short leash; reserve confirmation for destructive or scope-expanding moves. Trust builds across turns.
- **Let the agent read first.** Output quality goes up significantly when the agent reads `AGENTS.md` and the relevant library code before writing.
- **Review what it produces.** Agents write plausible code quickly. That's not the same as *correct* code. Read the diff like any other PR.
- **Use agents for the boring parts.** Coverage gaps, docstring formatting, example scripts, boilerplate: agents save the most time with the least risk on these.

## When a session feels off

When the agent keeps missing the point (repeated misinterpretations, output that doesn't land, you correcting more than producing), usually one of these is happening:

- **Terse replies assuming shared context that drifted.** A 3-word answer like "yes" or "option 2" assumes you and the agent share the same model of what's being asked. After a few turns, that model drifts. Restate the referent before continuing.
- **Pushback without reasoning.** "No" bounces a recommendation. "No because X" teaches the agent your model. The first wastes a round; the second teaches.
- **Underspecified task.** "Fix this" assumes the agent knows what "this" and "fix" mean. Naming the actual problem and what good looks like takes one sentence and saves several rounds.
- **Conversation has drifted too far to recover.** Sometimes the right move is to start a fresh session with clear initial framing rather than try to course-correct.

If none of the above apply and the agent still isn't tracking, try restating the actual goal explicitly ("I want to accomplish X. What's blocking that?"). That usually catches the disconnect.

## First time using an agent

For contributors who haven't used an AI coding agent, this project is a good place to start. The `AGENTS.md` file and skills system mean the agent already knows the project's rules, so no manual onboarding is needed. Try something small:

- Ask it to explain how a library works
- Ask it to write a test for an uncovered code path
- Ask it to generate an example script

Much of the "getting started" friction disappears once a question can simply be asked.

## Why this is set up this way

The investment in `AGENTS.md`, skills, and decisions exists so contributors, human or agent-assisted, spend their time on the interesting problems (API design, new libraries, hardware integration) rather than the mechanical ones (coverage, formatting, boilerplate).
