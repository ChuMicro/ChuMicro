# Decision 0116: One surface hub per repo — one server, one tab, surfaces with a lifecycle

Status: `accepted`
Date: `2026-08-01`
Summary: `webui/hub.py is the default transport for every browser surface an agent puts in front of a human: a single per-repo server on a stable port owning a single browser tab; questions, reports, and status boards are posted surfaces with a pending → answered | withdrawn | expired lifecycle; a content floor gates decision-page specs the way ask_gate gates AskUserQuestion.`
Related: Decision [0100](0100-webui-browser-surface-toolkit.md) (the webui toolkit this extends), the ask-gate floor (`.github/skills/_shared/ask_gate.py`).

## Context

Under Decision 0100 every question owned a one-shot server and every server opened a tab.
Measured failures of that shape, all operator-reported: five questions across a session
left five tabs, four of them dead; concurrent sessions fought over ports and mailboxes;
a question the conversation had already negated kept its server alive and its page
convincing; and the burden of "the session is the only opener" was distributed across
every skill that served a page. Separately, rich pages were carrying thin content: a
"who wins" verdict over bare letters passes every markup gate while telling a cold
reader nothing.

## Decision

- **One hub per repo.** `webui/hub.py` runs a single localhost server on a stable
  per-repo port (17871 here), found or race-safely started by `ensure()` (an O_EXCL
  lockfile under `.scratch/hub/`; losers use the winner). Agents are clients, never
  owners: nothing kills the hub to take its place, and no verb can resolve another
  session's pending surface except an explicit withdraw by id.
- **Surfaces, not servers.** Anything an agent wants seen is POSTed to the hub as a
  surface (kind: ask, report, or status) with a title, an optional tag, an optional
  sink path, and an optional asset dir (served under the surface with Range support).
  The hub persists surfaces to disk, so a restart reloads pending questions instead of
  orphaning them.
- **One tab, ever.** The hub opens the browser only when no shell tab is connected (it
  knows via the SSE client count) and pushes new surfaces into the open shell
  otherwise. The shell lists surfaces as chips, focuses new pending ones, shows
  withdrawn ones struck through, and flashes the pending count in the tab title. A hub
  restart reuses the port, so the old tab reconnects.
- **Lifecycle.** pending → answered (a submit wrote the sink) | withdrawn (the asking
  session moved on: `withdraw <id>`, or `--supersede` on the replacement) | expired
  (ttl). A withdrawn surface's page answers 410, naming the reason. The hub exits on
  its own after 15 idle minutes with no tab, no pending surface, and no waiter.
- **Exit-as-signal, kept.** `serve_picker.py` (and `python3 -m webui.hub ask`) posts
  the surface and blocks until it resolves; the waiting process completing is still
  the submit signal, with exit codes 0 answered / 3 withdrawn / 4 expired / 5 hub
  unreachable. Pages submit to a relative path, so the same self-contained page works
  hubbed (scoped under /s/<id>/) or served alone.
- **The content floor.** `render_picker.py` refuses to render a decision page whose
  spec a cold reader could not act on: a 120+ character brief, a real summary per
  decision card (with the axis defined when options are bare letters), full-sentence
  `option_help` per radio option, real prose prompts, no fragment-joiners outside
  quoted spans. One `FLOOR` line per defect, exit 2; `floor_waived` (a written reason)
  exists for the rare page the floor cannot fit. New spec capability: `prose` fields,
  prompted paragraph boxes whose text rides the blob as its own line.

## Rejected

- **A server per question, kept.** The one-shot transport survives behind
  `serve_picker.py --oneshot` and `webui/server.py` for a hubless host, but it is no
  longer the documented path: the per-question-server shape is the direct cause of the
  tab pile and the port fights.
- **The session as the opener.** Distributing "who opens the tab" across every skill
  produced double-opens and 20-tab sessions. Opening is the hub's decision alone,
  driven by the live client count.
- **Killing rival servers to take the port.** The reap-happy pattern is what made two
  sessions fight; the hub is a singleton by lockfile and probe, and everyone else is a
  client.

## Consequences

- Five rounds of questions are five chips in one tab. Two sessions asking at once are
  two chips, attributed by session, in the same tab.
- A negated question is withdrawn in place and its stale URL says so, instead of
  lingering as a live-looking page over a dead server.
- `validate_picker.py` gains a floor gate (a planted thin spec must refuse to render);
  `check_kit.py` gains a hub round-trip (post, serve, submit, wait-release, withdraw,
  410). The picker-edit hook keeps running both on any agent edit.
- Skills stop carrying opener choreography; their serve step is one background command
  whose completion is the answer arriving.
