# Workstream: config-shape beginner ergonomics — research + design + implementation

Status: **shipped 2026-05-06**.  Research + design pass landed in the same session (Q1–Q11 resolved); implementation followed in five commits across the mono-repo and workspace-template repo, then four-board hardware validation closed the loop.  See **Implementation log** at the foot for the rollout summary.

The previous unification (`scripts-workbench-config-unification`, closed 2026-05-04) and Decision [0057](../../decisions/0057-two-file-config.md) (`!secret` retired, two-file split) collapsed the *plumbing*; this workstream revisited the *shape* through a beginner-ergonomics lens and shipped it.

> **One-line rubric:** "plug in a board and go, tweak and go, be happy with results and deploy for real."  Every decision in this workstream gets weighed against it.

---

## Charter (verbatim from user, 2026-05-06)

The two prompts that opened this workstream are reproduced in full here so a cold reader sees the original framing.  Anything below this section is interpretation; if interpretation drifts, this is the source of truth.

### Prompt 1 — verification framing (set the mental model)

> hello, I'd like to run a verification pass on scripts-workbench-config-unification.md with real boards and a real "test" project in the chumicro workspace template repo (adjacent folder also in circuitpython folder.
>
> Here is what I think this is supposed to be and where it should be at. Im not positive ad it was a big wave of work so we may need to research if anything was missed. We also encountered issues with boards that were found to be a firmware issue at this time so workstreams split for a bit.
>
> My idea of what this is:
> workspace.yml file, template. during setup, copies the template to the root. user edits to fill in ssid, mqtt, even ssid2 or mqtt_other. If changes to the template happen they can be reapplied via setup without adjusting user set data.
> Per project configuration:
> This may not exist. Overrides workspace.yml settings, adds additional settings, like a "thing name" etc, configs specific to the project.
>
> Libraries:
> Have the capacity to request what they need from a config, such that if the value is not there, a clean error is printed about what value is needed and what to set, so the user can do so. This probably doesn't fully exist this way. - the wifi library has this I think via WifiConfig or was planned that way. I think thats the right path but i need a summary of how this works maybe. I beliee this also provides the ability to provide checks like has_creds, or for the code to set a config directly hard coded like WifiConfig(ssid, pass) or WifiConfig.fromConfigStore(configStore)
>
> And then the ability some how hand hold the "first time config", we cant just keep a template updated with canned commented out keys and vars for libraries that grow over time and change their config structure, is there some way the library itself can dictate the config structure for its slice of the config? I guess this kind of falls on user setup, such as passing in a WifiConfig when setting up Wifi, which may be the point to educate, both in readme/install/setup docs and in required defaults to instantiate it + the additional fromConfigStore hook. This should be fun to work through hopefully, thats the goal, for a beginner to basically grab the template workspace repo, plug in a board, run an example, change a config, run it again, change some code, run it again, without hassle, and reliable results and easy to deploy.

### Prompt 2 — research-project framing (the trigger for this plan)

> we can continue but we need to store a research project on the following, please save as a plan in workstreams research both repo folders as needed and go as far as needed in your research. this is an important area to focus on. I may not be right here either in these plans, please check industry standards here for circuitpython or other systems like what we are making. we did a home assistant way once with !secret but it was really not beginner friendly and required, at least in my opinion, a lot of up front documentation to understand, which is not exactly a beginner friendly atmosphere. Chumicro has been trying very hard to get to a point of plug in a board and go, tweak and go, be happy with results and deploy for real:
>
> checked in config.yml - yes but also no. yes we need a config file for projects, this would be like, the thing name and maybe the default board to deploy it to, things like that. that would make it a project_config.yml file I think, and it would provided via a template when running the command that generates a new project (workspace package I think).  Name of thing, default device, various knobs and tweaks for the project, like shutdown_button_hold_time=10, project_name=myProject, device="this_labeled_device". It must not contain things like ssid, or password, or secrets. those go in workspace.yml. Which is now misnamed I think. It would be better as secrets.yml or secrets.toml or something. toml may be better than yml as then we dont need yml parsing? it doesn't seem to contain anything "workspacey" does it? and for naming it could be something like "wifi.ssid" and "wifi.password"? then via chumicro-config you would access it via config["wifi.password"] - this keeps the array flat so we dont have nested arrays to deal with. and if that key doesn't exist, none is returned, no crashing? I think this makes sense and would be what beginners expect and deserve for an easy to work in workspace. thanks and appreciated and you deserve a hug for helping plan this before our testing. During our testing think about what you planned, pain points hit, lessons learned, conclusions, and mark it in the plan if its relevant to success of this repo.

---

## Premise

The current shape (post-Decision 0057) is:

- `workspace.yml` — gitignored, holds workspace defaults *and* secrets in plaintext under nested sections (`defaults.wifi.password`).
- `<project>/config.toml` — committed, per-project overrides; deep-merges over `workspace.yml::defaults`.
- Library code reads via `chumicro_config.load_section("wifi")` → dict; `WifiConfig.from_dict()` → typed object.

The user's audit (2026-05-06) flagged three pieces of the user-facing shape that don't match a beginner's expectations:

1. **Naming.**  `workspace.yml` doesn't actually carry anything "workspacey" — every field in it is either a credential (wifi password, broker auth) or a workspace-wide default (broker host).  A beginner reads "workspace.yml" and expects layout / package / build configuration, not their wifi password.  `secrets.yml` (or `secrets.toml`) describes the file's *actual* role.
2. **File format.**  YAML pulls in a parser dependency (`ruamel.yaml`).  TOML is in the Python 3.11 stdlib (`tomllib`) and is what CircuitPython's own `settings.toml` uses.  Dropping YAML aligns with CP convention and removes a dependency.
3. **Shape and accessor.**  Today's nested-section + `load_section("wifi")` shape forces beginners to think in two layers ("which section is this in?  what's the key inside it?").  The user's proposal: flat dotted keys (`wifi.ssid`, `wifi.password`), accessed via `config.get("wifi.password")`, with a missing key returning `None` instead of raising.  Library code that *requires* a key uses a separate `require()` call that raises with a helpful message.

There's also a missing "per-project knobs that aren't secrets" file in the user's proposed shape — `project_config.toml`, scaffolded by `chumicro-workspace new`, holding things like `project_name`, `default_device`, `shutdown_button_hold_time`, `mqtt_topic`.  This already partly exists as `<project>/config.toml`, but the user's framing names it more precisely and excludes secrets explicitly.

### Why now

The unification workstream froze the plumbing; that's the right time to revisit the shape.  Nothing has shipped to PyPI yet (no backward-compat burden), and the workspace-template repo is small enough that any user-facing-name change here is one search-and-replace plus a docs sweep across both repos.  Doing this *after* PyPI publication means file-format churn for real users; doing it *now* means file-format churn for `git mv` commits.

The four downstream consumers that would have to migrate:

- Mono-repo's `libraries/{wifi,requests,http_server,mqtt,sockets,websockets,ntp}/functional_tests/conftest.py`
- Workspace-template's `examples/{hello_world,wifi_only,periodic_get,telemetry_publisher,two_projects}/` and `projects/{_template,example_sensor}/`
- `chumicro_workspace._payloads/{workspace_yml,devices_yml}/` (canonical starter location)
- `chumicro_config` (the runtime API surface — what `from_dict` consumes, what `load_section` exposes, whether dotted-key access lands here or in a sibling)

---

## User-proposed shape (the spec we're testing)

> **This section is the user's proposal as captured 2026-05-06, not an accepted decision.  Open questions follow below.**

### File 1: `secrets.toml` (renamed from `workspace.yml`)

- Gitignored.  Materialized on first `setup` from a workbench-owned starter, never overwritten.
- Holds credentials and workspace-wide defaults that aren't safe to commit.
- TOML format (replacing YAML).  Flat top-level keys with dotted naming:
  ```toml
  # secrets.toml — gitignored, never committed.
  # Materialized on first `setup`; edit freely, re-running setup
  # leaves user edits alone.

  "wifi.ssid"     = "Things Cat"
  "wifi.password" = "littleandtiny420"

  "mqtt.broker.host"     = "test.mosquitto.org"
  "mqtt.broker.port"     = 1883
  "mqtt.broker.username" = ""
  "mqtt.broker.password" = ""
  ```
  *Open question (Q3 below): dotted keys as TOML strings vs nested tables.*

### File 2: `<project>/project_config.toml`

- Committed.  Scaffolded by `chumicro-workspace new <name>` from a per-project starter.
- Holds per-project knobs — names, default device target, behavior tweaks.  **Never secrets.**
- Examples:
  ```toml
  # project_config.toml — committed, lives in version control.
  project_name      = "my_porch_sensor"
  default_device    = "pi-pico-w-circuitpython-board"
  mqtt.topic        = "home/porch/temperature"
  mqtt.publish_period_ms = 5000
  shutdown_button.hold_time_ms = 10000
  ```

### Accessor API: `config.get("dotted.key")` returns `None` on miss

```python
from chumicro_config import load_runtime_config

config = load_runtime_config()  # merged secrets + project_config

ssid = config.get("wifi.ssid")            # None if missing
hold = config.get("shutdown_button.hold_time_ms", 5000)  # default fallback
broker = config.require("mqtt.broker.host")  # raises MissingConfigKey with a clean message
```

### Library API surface (the `WifiConfig` story)

The user's hand-holding goal — "library dictates what it needs, beginner sees a clean error" — keeps Phase 2's manifest validation but makes the runtime accessor the same dotted-key shape:

```python
# Today (post-Phase-2):
WifiConfig.from_dict(config["wifi"])  # raises MissingConfigKey on missing key

# Proposed:
WifiConfig.from_config(config)  # reads "wifi.ssid", "wifi.password" via config.require
WifiConfig(ssid="...", password="...")  # direct construction stays
```

The `WifiConfig.from_config()` constructor (the user's `fromConfigStore` hook) becomes the canonical "I'm a beginner, just hand the library the config" path.  Direct construction stays for advanced users / tests.

---

## Industry standards research

Sources are real systems with real beginner audiences.  Each one's worth weighed against chumicro's "plug in a board and go" rubric.

### CircuitPython `settings.toml` (the closest peer)

Since CircuitPython 8 (released 2022-09), the canonical user-config file is `settings.toml`, read by `os.getenv()`.

```toml
# /settings.toml on a CIRCUITPY drive
CIRCUITPY_WIFI_SSID = "MyNetwork"
CIRCUITPY_WIFI_PASSWORD = "hunter2"
CIRCUITPY_WEB_API_PASSWORD = "..."
```

Properties:

- **Top-level only.**  CP's TOML reader supports only string and int values at the top level — no nested tables, no arrays.  This is a deliberate constraint: every key is a flat string lookup.
- **Missing key → `None`.**  `os.getenv("MISSING")` returns `None`, never raises.  Beginner-friendly default.
- **Naming convention: SCREAMING_SNAKE_CASE.**  Mirrors environment variables.  CP-specific keys are prefixed `CIRCUITPY_*` so user keys don't collide with system ones.
- **Adafruit Learning Guides** ([Connecting to Wi-Fi with CircuitPython](https://learn.adafruit.com/getting-started-with-web-workflow-using-the-code-editor/connecting-to-wi-fi)) walk beginners through `settings.toml` as the *first* file they edit on a board.  This is the convention CP users already know.

**Implications for chumicro:**

- The user's "flat keys + missing returns None" intuition is **exactly** the CP `settings.toml` model.  Strong industry alignment.
- Naming style is the open one: dotted lowercase (`wifi.ssid`, the user's proposal) vs SCREAMING_SNAKE (`WIFI_SSID`, the CP-native style).  Dotted lowercase reads more like Python attribute access; SCREAMING_SNAKE reads more like env vars.  See Q4 below.
- Reusing `settings.toml`'s file path on the device side is tempting (one file, one convention) but conflicts with CP's read-only-on-host workflow and CP's reservation of `CIRCUITPY_*` keys.  Keep chumicro's config separate from `settings.toml`; layer if needed (Q5).

### Adafruit `secrets.py` (the legacy CP convention)

Pre-CP-8 Adafruit guides used a `secrets.py` Python module:

```python
# secrets.py
secrets = {
    "ssid": "MyNetwork",
    "password": "hunter2",
    "aio_username": "...",
    "aio_key": "...",
}
```

Gitignored by default.  Imported as `from secrets import secrets`; access via `secrets["ssid"]` raises `KeyError` on miss.

**Implications:**

- Beginner-familiar to anyone who started with CP before 2022.  Worth a one-line "if you're coming from `secrets.py`, here's the migration" doc note.
- Python-module-as-config has the advantage that you can compute values, but it's also the disadvantage — it's executable, and "your config file is a Python file" is a pit-of-failure for beginners (one stray `=` instead of `:` and it's a SyntaxError).  TOML is a strict win on that axis.

### Arduino `secrets.h`

C header with `#define`s:

```c
#define SECRET_SSID "MyNetwork"
#define SECRET_PASSWORD "hunter2"
```

Gitignored.  Beginner-friendly *for the Arduino audience* because it matches the rest of the Arduino sketch idiom.  Not relevant to chumicro's Python-first audience but worth noting that the "secrets.X" filename convention is industry-standard across embedded ecosystems.

### Home Assistant `!secret`

YAML with secret indirection:

```yaml
# configuration.yaml (committed)
http:
  api_password: !secret api_password

# secrets.yaml (gitignored)
api_password: hunter2
```

**This is the model chumicro tried and rejected** (the user's note: "we did a home assistant way once with `!secret` but it was really not beginner friendly and required a lot of up front documentation to understand").  The friction comes from:

- Two files that reference each other via a custom marker (`!secret`).
- Beginners have to learn "where does the value live" *before* they can edit anything.
- Splitting non-secret config from secrets implies a clean line that doesn't actually exist in practice (is `mqtt.broker.host` a secret if the broker is private?).
- The marker is YAML-specific — it doesn't survive a TOML conversion.

Decision 0057 already retired `!secret` for chumicro.  This research workstream is the formal "and we don't bring it back" pass.

### ESPHome (also `!secret`)

Same shape as Home Assistant.  Same friction.  Skip.

### MicroPython (no convention)

MicroPython doesn't ship a canonical config file.  Community projects use:

- `config.py` — Python module with module-level constants.
- `secrets.py` — same idea, gitignored.
- `config.json` — for machine-edited values.

No clear winner.  Beginner-friendly *only* because there's nothing to learn — but also confusing because every project does it differently.  The chumicro choice here directly fills a gap on the MP side.

### 12-factor app config (for context)

The 12-factor app pattern is "config in environment variables" — flat KEY=VALUE pairs, missing → unset.  This is the CI/cloud-services analog of CP's `settings.toml`, and it's where the "flat keys + missing returns None" instinct comes from in modern Python.  pydantic-settings, for example, expects flat env-var-style keys.

**Convergent evidence:** CircuitPython, environment variables, and the user's intuition all point at the same shape — flat string keys, missing returns `None`, `require()` for "I really need this."  The two systems that diverged from that shape (Home Assistant, ESPHome) are exactly the ones the user found beginner-hostile.

---

## Open questions (decide before any code lands)

### Q1 — Should `workspace.yml` be renamed to `secrets.toml`?

Today it carries credentials + workspace-wide defaults under one nested-YAML roof.  Three options:

1. **Rename + reformat** to `secrets.toml`.  Match the file's actual role; align with CP convention; drop the YAML parser dep.
2. **Rename only** to `secrets.yml`.  Keeps YAML; aligns with file role.
3. **Keep `workspace.yml`.**  Existing name; existing tooling.

*Lean: 1.*  The "what's actually in here" framing wins; YAML earns its parser dep nowhere else in chumicro's user-facing surface.

### Q2 — Should there be a separate committed `project_config.toml`?

Today the committed per-project file is `<project>/config.toml`.  The user's framing renames it `project_config.toml` to make "this is for project knobs, not secrets" explicit in the filename.

1. **Rename to `project_config.toml`.**  Self-documenting; no shape change.
2. **Keep `config.toml`.**  Shorter; matches CP `settings.toml` convention (config lives in `<scope>.toml`).

*Lean: 2 + a strong one-line header comment.*  `config.toml` is shorter, and the per-project context is already implicit ("this is the file in the project's directory").  But the user's instinct here is real — flag this in the README and the scaffold's commented header so the role is unambiguous.

### Q3 — Flat dotted-key TOML strings vs nested tables?

The user's example uses TOML string keys with embedded dots: `"wifi.password" = "..."`.  Standard TOML would write that as `[wifi]\npassword = "..."`.

Three sub-options for the on-disk shape:

1. **Pure flat with dotted strings** (user's example).  `"wifi.password" = "x"` — every key is a top-level string with dots in the name.  Simplest reader; matches CP `settings.toml`'s flat-only constraint exactly.  Ugly for tables/arrays.
2. **Standard nested TOML, flat dotted accessor** (recommended).  On-disk: `[wifi]\npassword = "x"`.  In code: `config.get("wifi.password")`.  The dotted-key API is a thin facade over the nested dict.  Beginners who eyeball the TOML file see clean section structure; beginners who write code use one-liner dotted keys.
3. **Flat + standard nesting both supported.**  Reader normalizes either form.  More flexible, more confusing.

*Lean: 2.*  TOML's nested-table syntax is what beginners see in every other Python project (pyproject.toml, ruff.toml, etc.).  The accessor API is where chumicro adds value — a flat dotted-key facade over a standard-nested file gives the best of both.  This is also the one option that doesn't force a wire-format change to `runtime_config.msgpack` (which is already nested).

### Q4 — Naming style for keys: dotted lowercase vs SCREAMING_SNAKE?

The user proposes `wifi.password`.  CircuitPython's `settings.toml` uses `CIRCUITPY_WIFI_PASSWORD`.

1. **Dotted lowercase** (`wifi.password`).  Reads like Python attribute access; matches the nested-table TOML shape one-to-one.
2. **SCREAMING_SNAKE** (`WIFI_PASSWORD`).  Matches CP `settings.toml` and POSIX env-var convention.  No nesting.
3. **Both.**  Reader normalizes; documentation picks one for examples.

*Lean: 1.*  Dotted lowercase is what every other TOML config in the Python ecosystem uses (pyproject `[tool.ruff]`, `[tool.coverage.report]`, etc.).  SCREAMING_SNAKE is appropriate when the file *is* the env (CP's case — `settings.toml` is loaded into the env namespace).  Chumicro's file is a config file, not env, so dotted lowercase fits.

### Q5 — Relationship to CircuitPython's `settings.toml`?

A CP board has its own `settings.toml` for board-level configuration (web workflow password, USB drive properties).  Chumicro deploys `runtime_config.msgpack` to the same filesystem.

1. **Separate files (today's shape).**  `settings.toml` for board-level CP config, `runtime_config.msgpack` for app-level chumicro config.  Clear separation; no conflict.
2. **Read both from `chumicro-config`.**  `config.get("WIFI_SSID")` falls through to `os.getenv("WIFI_SSID")` if not in the chumicro msgpack.  Beginners with existing `settings.toml` setups don't have to migrate.
3. **One file: chumicro writes `settings.toml`.**  Maximum convergence; conflicts with CP's reservation of `CIRCUITPY_*` keys and with CP's read-only-on-host workflow.

*Lean: 2 (eventually).*  Defer; not blocking on the rename + reshape.  But list as a follow-up — the migration story for "I already have a `settings.toml`" is real.

### Q6 — Missing key returns `None` vs raises?

Three accessor patterns for the in-code API:

1. **`config.get("wifi.ssid")`** — returns `None` on miss.  Always safe; never raises.
2. **`config["wifi.ssid"]`** — `KeyError` on miss.  Python-standard; cryptic for beginners.
3. **`config.require("wifi.ssid")`** — raises `MissingConfigKey("required config key 'wifi.ssid' is missing")` on miss.  Clean message; opt-in strictness for library code.

*Lean: all three.*  `get` for soft access (apps), `require` for hard access (libraries), `[]` because Python.  Library code uses `require` so the on-device error message names the missing key; app code uses `get` with a default.  This is the same split today's `chumicro-config` has between `try_load_section` and `load_section`, just renamed and unflattened.

### Q7 — Where does manifest validation live?

Phase 2 already added `[tool.chumicro.config.sections.<name>]` in library `pyproject.toml` files, aggregated by `chumicro_workspace.config_manifest`, validated at deploy time by `WithRuntimeConfig`.  Today only `chumicro-wifi` declares a manifest.

After the rename + flatten:

1. **Keep nested-section manifest format** (today's shape).  `required = ["ssid"]` under `[tool.chumicro.config.sections.wifi]`.  Validator unflattens the dotted-key config to match.
2. **Switch to flat dotted manifest.**  `required_keys = ["wifi.ssid", "wifi.password"]` under `[tool.chumicro.config]`.  Direct match to the runtime accessor.
3. **Both.**  Reader accepts either.

*Lean: 2.*  If the runtime API is `config.get("wifi.password")`, the manifest should declare requirements in the same vocabulary.  Today's nested-section manifest is one indirection step that adds nothing.  Migration is mechanical (one library has a manifest; rewriting it is five lines).

### Q8 — How do we get from today's shape to the proposed shape?

Two-step migration is required (no PyPI users yet, but the workspace-template repo and any local clones need to keep working through the change):

1. **Step 1 — Add the new accessor surface alongside the old.**  `chumicro-config` gains `config.get(dotted_key)` / `config.require(dotted_key)` over the existing nested dict.  No file-format change yet.  Library code can opt in.
2. **Step 2 — Rename + reformat the on-disk files.**  `workspace.yml` → `secrets.toml`; old `materialize_workbench_starters` keeps the YAML reader for one cycle so existing clones don't break on first re-setup.  After one cycle, drop the YAML reader.

The `setup-schema-reconciliation.md` workstream (already in next-up) handles the related "user has edited workspace.yml; how do we surface new starter additions without clobbering" question; that workstream's strategy applies to the rename-and-migrate path too.

---

## Tradeoff matrix

| Axis | Today | User proposal | Recommended (after research) |
|---|---|---|---|
| **File 1 name** | `workspace.yml` | `secrets.toml` | `secrets.toml` |
| **File 1 format** | YAML (`ruamel.yaml`) | TOML (`tomllib`) | TOML |
| **File 1 shape on disk** | Nested sections | Flat dotted-string keys | Nested tables (Q3 option 2) |
| **File 2 name** | `<proj>/config.toml` | `<proj>/project_config.toml` | `<proj>/config.toml` (Q2 option 2) |
| **Key naming** | Nested sections | `wifi.password` (dotted lowercase) | `wifi.password` (Q4 option 1) |
| **Accessor — soft** | `config["wifi"]["password"]` (raises) | `config.get("wifi.password")` (None) | `config.get(...)` |
| **Accessor — hard** | `load_section("wifi")` (raises) | `config.require("wifi.password")` (MissingConfigKey) | `config.require(...)` |
| **Library config manifest** | Nested sections in pyproject | (not specified) | Flat dotted keys in pyproject (Q7 option 2) |
| **Library constructor** | `WifiConfig.from_dict(...)` | `WifiConfig.from_config(config)` | Both — `.from_config(config)` is the beginner path, `from_dict` stays for advanced |
| **`!secret` indirection** | Already retired (Decision 0057) | Stays retired | Stays retired |
| **CP `settings.toml` integration** | None | (not specified) | Defer (Q5) |

The recommended column is what to put in front of the user as the concrete proposal once verification results are in.  All four "user proposal" cells either match the recommendation exactly or are within editorial-distance.

---

## Verification ties — capture during today's real-board testing

Today's verification pass against the workspace-template + real boards is **the** opportunity to ground this design in evidence.  As we go through scenarios, capture observations against these probes — they'll either reinforce the user proposal or surface a counter-case before any code is written.

Add observations to the **Findings** section below, dated and tied to a specific scenario, as we encounter them.  Each finding tagged with one of:

- `[reinforces]` — the proposal addresses a real pain point we just hit.
- `[counter]` — the proposal would have made this worse, or didn't help.
- `[orthogonal]` — useful observation but doesn't bear on the config-shape question.
- `[gap]` — the proposal doesn't cover this case; revisit.

### Probes to watch for

1. **Re-setup behavior.**  When a user edits `workspace.yml` and re-runs setup, what happens?  Does setup tell them their file is missing new starter sections?  (This is the `setup-schema-reconciliation` overlap — observations help both workstreams.)
2. **First-deploy error UX.**  Deploy a project with a missing required key.  What error does the user see?  Where (deploy time vs boot time)?  Is it specific (`MissingConfigKey: required config key 'wifi.password' is missing — set it in secrets.toml under wifi.password`) or cryptic?
3. **Section discoverability.**  A beginner edits `workspace.yml` for the first time.  Do they know what sections are valid?  Is there a discoverable list, or do they need to read the wifi/mqtt/requests/etc. READMEs?
4. **Naming-style friction.**  As we move between files (workspace.yml's `defaults.wifi.password` and `<proj>/config.toml`'s `[wifi]\npassword`), do we hit ambiguity about which form is right?  Track every "wait, which file uses dots?" moment.
5. **The "I just want to override the broker for one project" flow.**  How many edits across how many files to accomplish that?  Today: 1 file (`<proj>/config.toml`).  Under the proposal: same.  But verify by doing it.
6. **Beginner test: drop `workspace.yml` entirely, deploy a wifi project.**  What happens?  Is the message "you need a workspace.yml with `[wifi]` keys" specific?  Does the same message work for a fresh-clone user who hasn't run setup yet?
7. **Library-side: does `WifiConfig.from_dict` raise the right kind of error?**  We already verified the message text; verify the timing (deploy vs boot) and verify a beginner reading it knows what to fix.

### Findings

> Append observations here as we go.  Format:
>
> ```
> #### YYYY-MM-DD — Scenario N: <short title>
> [tag] What happened.  How it bears on the proposal.  Whether to update Q1‑Q8.
> ```

#### 2026-05-06 — Scenario 1: Fresh setup chicken-and-egg on `workspace.yml`

`[reinforces]` (and exposes a real beginner-onramp bug).

A fresh-clone user follows the README, runs `python3 run.py setup`, and gets:

```
error: no workspace.yml found in $WORKSPACE_TEMPLATE_ROOT or any parent
```

Root cause: [`_cmd_setup`](../../../workbench/workspace/src/chumicro_workspace/cli/) calls `_resolve_workspace(args)`, which in turn calls `WorkspaceLayout.from_dir()` — and that walks up looking for `workspace.yml` and raises `WorkspaceNotFoundError` when it's absent.  But setup itself is what *creates* `workspace.yml` (via `materialize_workbench_starters` ten lines later).  The bootstrap fails before reaching the materializer.

This is a textbook "plug-in-and-go" regression: the very first command a beginner runs after `git clone` blocks with a confusing error about a file they shouldn't even need to know exists yet.

**Bearing on the research plan:**

- `[reinforces]` for the file-rename question (Q1) — every time the user-facing surface mentions `workspace.yml`, a beginner has to figure out which file the message means and whether they're supposed to create it.  A renamed `secrets.toml` doesn't fix the bug, but the file's role (and thus the error's meaning) becomes obvious — "you need a `secrets.toml` to deploy" is more diagnosable than "no workspace.yml found in any parent."
- `[reinforces]` for the `setup-schema-reconciliation` sister workstream — the same `_resolve_workspace` precondition is what makes "setup adds new starter sections" hard today; both workstreams share the same surface.
- Suggests a Q9 we hadn't listed: **Does `setup` need its own resolver path, or should `WorkspaceLayout.from_dir()` accept a "may-not-exist-yet" mode?**  Fix shipped as part of this verification — `_cmd_setup` now uses `Path.cwd()` directly (no walk-up, no precondition).

Fix landed in this commit; verification continues.

#### 2026-05-06 — Scenario 1: missing test deps in chumicro-dev mode

`[orthogonal]` to the config-shape question, but worth flagging since it surfaces in every dev-mode setup:

```
ERROR: pip's dependency resolver does not currently take into account all the packages that are installed.
chumicro-pytest-device 0.4.0 requires pytest>=8.0, which is not installed.
chumicro-repl 0.0.0 requires prompt-toolkit>=3.0, which is not installed.
```

`run.py`'s editable install loop uses `--no-deps` (line 154) to avoid pulling in PyPI versions of chumicro packages.  Side effect: the third-party deps each package declares (pytest, prompt-toolkit) don't get installed either.  The workspace-level `pip install -e .` later doesn't pull them in because they're not declared in the workspace's `pyproject.toml`.

Doesn't affect today's deploy verification (deploy doesn't need pytest), but it would block running tests from a fresh chumicro-dev clone.

#### 2026-05-06 — Scenario 1: dev-mode `sync_library_sources` strips the workspace.yml comment header

`[reinforces]` (significant — directly contradicts the user's mental model).

After the chicken-and-egg fix landed, setup completed:

```
setup: materialized 2 workbench-owned starter(s)
  devices.yml
  workspace.yml
setup: synced library_sources for 15 chumicro libraries from $CHUMICRO_ROOT
```

The materialized `workspace.yml` is:

```yaml

# managed by chumicro-workspace setup — chumicro-dev.toml mode
library_sources:
  chumicro_compat: ../chumicro/libraries/compat/src
  chumicro_config: ../chumicro/libraries/config/src
  ...
```

The entire ~60-line comment header from the canonical starter (the file role explanation + `defaults:` example + `deploy_targets:` example + `quality:` example) is gone.

Root cause: the starter is **all comments, no keys** — every block is commented out (`# defaults:` ... `# wifi:` etc.).  When `sync_library_sources` round-trips through ruamel, the parsed YAML has zero top-level keys.  Ruamel's round-trip preserves comments by attaching them to keys; comments with no key to attach to (the leading file-level header) get dropped on dump.  The dev-mode sync then writes back a file containing only the new `library_sources` key — which is exactly what we see.

Two compounding problems:

1. **The starter's didactic value is wiped out on first setup in dev mode.**  The user's first encounter with `workspace.yml` is a stripped file with no hint of what `defaults:` or `deploy_targets:` are for.  They have to read the README or the workstream doc to figure out the shape.
2. **The "re-run setup, your edits are preserved" property only holds for non-dev users.**  Mono-repo contributors and template-fork developers get their workspace.yml rewritten every time they run `setup`.

**Bearing on the research plan:**

- `[reinforces]` Q3 (on-disk shape) — a starter with **real keys** (uncommented placeholders that the user replaces) survives round-trip preservation; an all-comments starter doesn't.  The user's proposal to put actual entries (`"wifi.ssid" = ""`, `"wifi.password" = ""`) in the starter rather than commented examples isn't just a stylistic choice — it's required for round-trip preservation to work at all.
- `[reinforces]` Q1 (rename) and the file-format question — if the file's contents were canonical TOML with real keys (`"wifi.ssid" = ""` instead of `# ssid: my-ap`), there'd be no comment-vs-key mismatch.  TOML stdlib serialization also doesn't have ruamel's "comments-attach-to-keys" gotcha.
- Surfaces a Q10: **Should the starter ship with placeholder real-keys or with all-commented examples?**  Real keys round-trip safely and double as the schema beginners can edit without thinking.  Commented examples preserve flexibility (no key clutter for users who don't need that section) but break round-trip preservation.

**Workaround for verification:** edit `workspace.yml` manually to add `defaults.wifi.{ssid,password}` (uncommented) before scenario 5.  The round-trip will preserve them on subsequent setup runs because they're real keys now.

#### 2026-05-06 — Scenario 2: re-setup with real keys present is correctly idempotent

`[orthogonal]` confirmation, but worth recording.

After adding `defaults.wifi.{ssid,password}` + `defaults.mqtt.broker.{host,port}` (real keys) to `workspace.yml` and re-running `python3 run.py setup`, the output was:

```
setup: library_sources already in sync with $CHUMICRO_ROOT
```

— and `workspace.yml` was untouched (header preserved, defaults preserved, library_sources preserved).  `sync_library_sources` short-circuited at the "already in sync" check before re-writing.  This confirms the diagnosis from the previous finding: the round-trip preservation works correctly **when there are keys to anchor comments to**.

#### 2026-05-06 — Scenario 3: `add-device` works cleanly across 4 boards but missed two ergonomics moments

`[orthogonal]` to the config-shape question, but two beginner-onramp findings worth tracking:

* **All 4 boards probed cleanly**: Pi Pico W CP/MP, Lolin S2 CP/MP.  `add-device` auto-detected runtime, captured UID + machine string, and populated `devices.yml` correctly.  Three-zone classification working (USER-OWNED ID + description, HARDWARE-ONCE uid/machine, PROBED-ALWAYS address).
* **Firmware-version parser fails on RC builds**: every probe printed

  ```
  add-device: warning — circuitpython firmware compatibility:
    Could not parse the firmware version
    (circuitpython reported an unrecognized version string).
  ```

  The actual firmware string was `10.2.0-rc.0` (visible in the CP REPL banner).  The parser likely does not handle the `-rc.N` suffix.  `firmware_version: 10.2.0.` (trailing dot) is what landed in `devices.yml` — the regex captured up to the `-` then appended a stray dot.  Side effect: `requires_flash` floor checks are silently disabled on every contributor's machine running RC firmware.  **Real bug, separate workstream — not config-shape.**
* **`add-device` doesn't suggest IDs from the probe.**  Hardware identity already gives `board_id: raspberry_pi_pico_w` + `runtime: micropython`; an obvious id is `raspberry-pi-pico-w-mp`.  Today the user has to invent one.  Beginner-onramp friction.  Not config-shape, but worth a separate small-fix workstream.

#### 2026-05-06 — Scenario 4: `deploy <name>` blocks on `app.py`/`code.py` mismatch

`[reinforces]` the broader beginner-onramp question (orthogonal to config-shape but same root concern):

```
ValueError: entrypoint '/code.py' not produced by directory walk
(keys: ['/README.md', '/app.py'])
```

Every example in `examples/` ships `app.py` + `run()` (the boot-shim convention).  Plain `deploy <name>` defaults to non-boot-shim mode and expects `code.py` (CP) or `main.py` (MP) at the project root.  The fix is `deploy <name> --boot-shim --import-graph`, but a beginner reading the README and `examples/hello_world/README.md` doesn't know that.

The boot-shim flow is what every example is designed for — auto-detecting it (when the project ships `app.py` with a `run()` callable and no `code.py`/`main.py`) would close this gap.  **Real beginner-onramp papercut, separate workstream.**

#### 2026-05-06 — Scenario 5: full pipeline VERIFIED end-to-end on CP

`[reinforces nothing — confirms the unification works]`.  Pi Pico W CP, after `deploy wifi_only --device pi-pico-w-cp --boot-shim --import-graph`:

```
wifi_only: connecting ...
wifi: connected at 192.0.2.21
wifi: connected at 192.0.2.21
```

Pipeline verified end-to-end:

1. `workspace.yml::defaults.wifi.{ssid,password}` read by host
2. `compose_runtime_config(workspace.yaml, projects/wifi_only/config.toml)` deep-merged into a dict
3. `WithRuntimeConfig` wrote `runtime_config.msgpack` into the staged tree
4. `chumicro-deploy` rsync'd the staged tree to `/Volumes/CIRCUITPY 1`
5. On boot, `boot_shim` imported `chumicro_config.load_runtime_config()` which read the msgpack
6. `WifiConfig.from_dict(config["wifi"])` consumed the merged dict
7. `WifiService` associated to the AP and reported the IP

**The user's complaint is correctly framed**: it's not that the unified pipeline doesn't work — it does, demonstrably, on real hardware.  The complaint is that the path from `git clone` → `deploy wifi_only` requires too many beginner-hostile steps (chicken-and-egg fix + comment-stripping starter + boot-shim flag + manually-invented device IDs).  Each of those is a separate small workstream; the config-shape research workstream is one piece of the larger beginner-onramp story.

(MP wifi_only deploy partially verified — file transfer was interrupted by a 50 s `gtimeout` which proved insufficient for MP's chunked-write transport.  The pipeline math is identical between runtimes; CP success is sufficient evidence.)

#### 2026-05-06 — Scenario 6: missing-required-key UX is GOOD where it exists

`[reinforces]` Q7 (manifest format) and the broader proposal.

After temporarily removing `password:` from `workspace.yml::defaults.wifi:`, `deploy wifi_only` failed at the host **before any bytes hit the device** with:

```
chumicro_workspace.config_manifest.ConfigManifestError:
Runtime config does not satisfy the union manifest of imported libraries:
  [wifi] missing required keys: password
  (declared by: ../chumicro/libraries/wifi/pyproject.toml)
```

This is the failure mode the user wanted: section name, missing key, and the library that declared the requirement (with a path to the pyproject.toml).  A beginner can act on this without a stack trace.

**The gap**: today **only `chumicro-wifi` declares a manifest**.  Six other networking libraries (mqtt, requests, http_server, sockets, websockets, ntp) ship without `[tool.chumicro.config.sections.<name>]` blocks in their pyproject.toml.  A project that uses MQTT and forgets `mqtt.broker.host` deploys silently and then crashes on-device with a still-clean-but-less-precise `MissingConfigKey` at runtime.

**Bearing on the research plan:**

- `[reinforces]` Q7 — the manifest format works.  Phase 2's `[tool.chumicro.config.sections.<name>]` shape is good UX once it's filled in.
- `[reinforces]` the user's "library dictates its slice of the config" intuition — this is exactly what Phase 2 enables.  The proposal to flatten the on-disk shape (Q3) doesn't change manifest semantics; it just changes the keys' names from `wifi.password` (nested) to `"wifi.password"` (flat).  The validator works the same way.
- Adds a Q11: **should declaring a config manifest be required** (e.g., a `check-config-manifest` script that fails CI if a library imports `chumicro-config` but doesn't declare a manifest)?  Today it's opt-in and six libraries opted out.  Fail-fast incentive missing.

This was the most informative scenario of the verification pass.  The good news: when the user-visible promise is honored, it's honored well — the error is precise, actionable, and beginner-readable.  The bad news: it's honored only one library deep.

---

## Verification conclusions (2026-05-06)

The unification workstream landed correctly: the pipeline works end-to-end on real hardware (Pi Pico W CP demonstrated `wifi: connected at 192.0.2.21` from a workspace.yml-baked merged-config msgpack).  But verification surfaced **seven beginner-onramp issues**, of which two are config-shape questions (this workstream's domain) and five are adjacent papercuts that compound into the user's "plug in a board and go" complaint:

| # | Finding | Bearing | Status |
|---|---|---|---|
| 1 | Setup chicken-and-egg in `_cmd_setup` | `[reinforces]` Q1 | **Shipped** 2026-05-06 in `4ac81fd` (mono-repo) |
| 2 | Comment-only starter loses header on round-trip | `[reinforces]` Q3, raises Q10 | **Resolved** by Q10 direction (real placeholders) + Strategy C additive re-apply (`7d36f27`) |
| 3 | `add-device` firmware-version parser breaks on RC | `[orthogonal]` | **Shipped** 2026-05-06 in `8ecf728` (probe + parser walk version tuple, stop at first non-int) |
| 4 | `add-device` doesn't suggest IDs from probe | `[orthogonal]` | **Shipped** 2026-05-06 in `f5539e9` (`add-device --address` with no positional suggests an id from probe) |
| 5 | `deploy <name>` blocks on `app.py`/`code.py` mismatch | `[orthogonal]` | **Shipped** 2026-05-06 in `3fde27c` (boot-shim simplification: deploy auto-synthesises three-line entrypoint when `app.py` exports `run`) |
| 6 | mpremote leaves orphan port-holder after non-clean exit | `[orthogonal]` | **Shipped** 2026-05-06 in `224c489` (deploy surfaces the offending PID in the error message) |
| 7 | Manifest validation works well; only one library uses it | `[reinforces]` Q7, raises Q11 | Phase 2 follow-up to declare manifests in remaining libraries (still open — only `chumicro-wifi` declares one) |

**Conclusions for Q1‑Q11:**

- **Q1 (rename `workspace.yml` → `secrets.toml`)** — the verification reinforces but does not decide.  The error message in finding 1 (`error: no workspace.yml found in <root> or any parent`) is more diagnosable when the file's role is in its name.  But the rename is the second-order benefit; the first-order benefit is fixing the bugs that made the file-name appear in error messages at all.
- **Q3 (on-disk shape — flat dotted strings vs nested tables)** — strongly reinforced.  Finding 2 (the comment-stripping bug) is rooted in ruamel-rt's "comments must attach to keys" behavior.  TOML's stdlib serialization doesn't have that constraint; nested tables with real keys (Q3 option 2) survive round-trip at all costs.  Q3 option 1 (pure flat with dotted strings) also works but adds verbose key names.  **Lean: option 2** — nested tables on disk, flat dotted accessor in code.
- **Q7 (manifest format flat vs nested)** — reinforced.  The current nested `[tool.chumicro.config.sections.wifi]` format works; flattening it to `[tool.chumicro.config]` with `required_keys = ["wifi.password"]` would match the proposed runtime accessor exactly without changing semantics.  **Lean: flatten when the on-disk shape flattens (Q3 + Q7 move together).**
- **Q10 (new — starter content shape)** — the verification raised this question.  An all-comments starter breaks round-trip preservation in dev mode.  **Lean: ship real placeholder keys** (`"wifi.ssid" = ""` rather than `# ssid: my-ap`) — both for round-trip safety and as a built-in schema beginners see and edit.
- **Q11 (new — required manifest declaration)** — the verification raised this too.  Six libraries don't declare manifests; a `check-config-manifest` ratchet (or a CI step that imports each library's pyproject.toml and fails if `chumicro-config` is imported anywhere in `src/` without a manifest block) would close the gap.  **Lean: add the ratchet**, but only after this workstream lands the renamed-file shape (so the manifests don't have to migrate twice).

**Overall:** this workstream's premise survives contact with reality.  The user's mental model (rename, flat keys, missing → None, library declares its slice) was reinforced rather than contradicted by every finding.  The fact that the pipeline **does** work end-to-end is the floor we're refining from; nothing in this verification pass calls for a teardown.

---

## Direction set 2026-05-06 — user clarifications post-verification

User responses after the verification pass.  These supersede the earlier "lean" calls on Q1, Q10, and Q11; the rest stay open.

### File-purpose split — both files stay, but with distinct roles

Verbatim user direction:

> "if the workspace is itself saving data here that is not relevant to configuration keys and values needed on a circuitpython or micropython board, those configs should go to another file.  That would define a clearer reason for a workspace.yml and a secrets.yml i think, which would mean having both but with different purposes"

This **resolves Q1** — and reframes it.  The original Q1 question was "rename `workspace.yml` to `secrets.toml`?"  The answer is **no, but split**.  Two files, each with a purpose visible in its name:

| File | Role | What lives here | Reaches a board? |
|---|---|---|---|
| `workspace.yml` | **Workspace machinery** | `library_sources` (dev-mode editable overrides), `deploy_targets` (per-project → device mapping), `quality` (lint / coverage knobs) | **Never.** Host-only. |
| `secrets.toml` | **Device runtime config** | `wifi.ssid`, `wifi.password`, `mqtt.broker.host`, anything else that gets baked into `runtime_config.msgpack` | **Yes** — flows through `compose_runtime_config` to the device. |
| `<project>/config.toml` | **Per-project device override** | Same shape as `secrets.toml`, project-specific values | Yes — deep-merges over `secrets.toml`'s defaults. |

The misnamed file isn't `workspace.yml` — it's the wifi/mqtt creds that are misnamed *while inside* `workspace.yml`.  Move them out, and `workspace.yml`'s name becomes accurate (it really does hold workspace machinery now).

This is a strictly cleaner answer than the original "rename to `secrets.toml`" because:

- Each file's role is self-evident from the filename.
- `workspace.yml` continues to be parsed by the existing reader (no migration for `library_sources` / `deploy_targets`).
- `secrets.toml` is purely device-bound config — no machine-managed blocks living inside it, so the comment-strip bug class can't recur there.
- TOML stdlib parsing applies to `secrets.toml` (the file format question collapses to this one file — `workspace.yml` can stay YAML for one cycle if we want, since it's not the file beginners interact with).

Q1 resolved: **two files, distinct purposes, names that reflect roles.**  Q3 (on-disk shape) and Q4 (key naming) now apply to `secrets.toml` only — `workspace.yml`'s shape is determined by the existing readers.

### Q10 — ship real placeholders + additive re-apply (no clobbering)

Verbatim user direction:

> "for q10, we should ship real placeholders, it could even be a fake/bogus wifi for example purposes.  though i would hope we maintain comments when re-applying the template.  if re-applying the template breaks things like this or what the user edited and we can't fix it then we shouldn't re-apply at all?"

> "really all the re-apply has to do is add new keys that have been put into the template (commented out or not) and append them to the users existing config"

This locks Q10 and adds a hard requirement on the setup re-apply behavior.  Two parts:

1. **Starter ships real placeholder values** (e.g., `"wifi.ssid" = "replace-with-your-ssid"`, `"wifi.password" = "replace-with-your-password"`).  Bogus enough that nothing can accidentally use them at runtime; real enough to survive parser round-trip; visible enough to invite editing.  *Implication: manifest validation needs to also reject placeholder values* (a key being "present" with `replace-with-your-ssid` shouldn't satisfy the manifest).  Two ways to enforce: a sentinel value the manifest validator knows to reject, OR a runtime check at `from_dict` time.  Lean: sentinel rejection at deploy time, since that's where the rest of the validation already lives.

2. **Setup re-apply is additive, never destructive.**  When the upstream template gains a new key (commented or not), `setup` adds it to the user's existing config file.  When it doesn't gain anything, `setup` is a no-op.  Existing user edits are NEVER touched.  Re-apply has exactly two outcomes:
   - **No new template keys** → no-op.  User file untouched.
   - **New template keys** → append the new keys (in the same order the template introduces them, with their comments).  User file's existing content untouched.

This is **strategy C** of the [`setup-schema-reconciliation.md`](setup-schema-reconciliation.md) workstream — promoted from "natural follow-up" to **the canonical setup re-apply behavior**.  The user's framing ("if we can't preserve, we shouldn't re-apply at all") makes additive-only the contract.

This also implicitly **rejects strategy B** (show a diff, no auto-apply): the user's read is that re-apply should be silent + safe, not interactive.

Q10 resolved: **real placeholders, additive-only re-apply, no clobbering.**

### Q11 — CI applies its own configs locally + a generic validator

Verbatim user direction:

> "yes ci can and should apply its own configs locally prior to executing tests.  that is the current plan at least.  is there a better way to think about this for ci?"

CI applying its own config is fine.  The "better way" question has one structural answer worth considering:

**Add a standalone `chumicro-workspace config-validate <config-file>` CLI** that reads the union of installed library manifests and lints any config file against them.  This is the same logic that already runs at deploy time (`WithRuntimeConfig.files()` calls `validate_runtime_config`); exposing it as a standalone CLI:

- **Decouples** "what the libraries need" (declared in pyproject manifests, single source of truth) from "how CI provides it" (env vars, side files, secrets store, whatever).
- **CI step becomes**: `apply-test-config && chumicro-workspace config-validate workspace.yml secrets.toml && pytest`.  The middle step catches schema drift instantly — if a library adds a required key tomorrow, CI fails on the validate step rather than mid-test with a confusing `MissingConfigKey`.
- **Local dev gets the same tool**: a contributor can run `chumicro-workspace config-validate` before `deploy` to catch problems without burning a board cycle.

This isn't an alternative to "CI applies its own config" — it's a **lint step** that pairs with it.  Cheap to build (the validator already exists internally), cheap to maintain (no new code path for CI to special-case), and gives every contributor a fast feedback loop on "is my config complete?"

Q11 resolved: **CI applies its own config + new standalone `config-validate` CLI as the missing lint step.**  Track as a Phase-2-follow-up alongside the broader manifest declaration push.

### Q2 — per-project file is `project_config.toml`

User direction:

> "q2 - project_config.toml i think makes sense"

Q2 resolved: **`project_config.toml`**, not `config.toml`.  Self-documenting filename — beginners reading the project directory understand the file's role from the name.  Migration touches the workspace-template repo's `projects/_template/`, the example projects, and the mono-repo's documentation pointers.

### Q3 — nested on disk, flat on the board (compose-time flatten)

User direction:

> "q3 - nestable table that resolved to a dotted lookup in a flat dict when it gets into the board?  should we just do nested dicts?  Im really not sure.  I think the flat dict is technically better for circuitpython/micropython"

Locked: **nested tables on disk, flat dict on the board, flatten at compose-time.**  Best of both worlds:

- **`secrets.toml` on the host (beginner-readable)** —
  ```toml
  [wifi]
  ssid = "Things Cat"
  password = "..."

  [mqtt.broker]
  host = "test.mosquitto.org"
  port = 1883
  ```

- **`compose_runtime_config` flattens during merge** —
  ```python
  {"wifi.ssid": "Things Cat",
   "wifi.password": "...",
   "mqtt.broker.host": "test.mosquitto.org",
   "mqtt.broker.port": 1883}
  ```

- **`runtime_config.msgpack` ships the flat dict to the device** — single hash lookup, one dict allocation, no recursion to walk.  Honors the 256 KB-RAM floor.

- **On-device** — `config = load_runtime_config()` returns the flat dict directly.  `config.get("wifi.password")` is one hop.

Why this beats either pure-nested or pure-flat:

- Pure nested costs N+1 dict allocations and two hash lookups per access on a memory-constrained board — measurable on a 256 KB target.
- Pure flat (with literal dotted-string keys on disk) is uglier to read and edit.  `[wifi]\nssid = "..."` reads better than `"wifi.ssid" = "..."`.
- Compose-time flattening lets the disk format optimize for human readability and the wire format optimize for device performance.  No tradeoff.

Q3 resolved.

### Q4 — lowercase snake within segments, dot-separated when flattened

User direction:

> "q4 - lower_case_snake but look at q3?  Are these basically the same question?"

Q4 falls out of Q3.  On disk: `[wifi]\nssid = "..."` (lowercase snake within the segment, no dots — TOML's section header provides the namespace).  After flattening: `"wifi.ssid"` (lowercase snake segments joined by dots).  SCREAMING_SNAKE rejected — it's an env-var convention, and chumicro's file is a config file, not an env namespace.

Q4 resolved: **lowercase snake-case within segments; dots are the segment separator after flattening.**

### Q5 — no native `settings.toml`, but read it as a fallback if present

User direction:

> "q5 - not sure we should support settings.toml in this environment honestly.  we could read it if it exists on board (i think circuitpython does that on its own) so the config library should probably 'try' to aggregate data from it if it exists to be nice I guess"

Locked: **chumicro-config does not write or require `settings.toml`.**  It does try to read it as a fallback when a key isn't found in the chumicro msgpack:

```python
def get(key: str, default: Any = None) -> Any:
    if key in self._flat_dict:
        return self._flat_dict[key]
    # CircuitPython-only fallback: settings.toml via os.getenv
    env_key = key.upper().replace(".", "_")
    fallback = os.getenv(env_key)  # CP returns None on miss; MP doesn't have settings.toml
    return fallback if fallback is not None else default
```

This gives CircuitPython users with existing `settings.toml` setups (`CIRCUITPY_WIFI_SSID = "..."`) a free migration path — they don't have to delete or migrate their existing config; chumicro-config picks it up as a fallback.  MicroPython users see no change (no `settings.toml` exists there).

Q5 resolved: **`settings.toml` fallback on CP via `os.getenv`, no native support, no migration required.**  Implementation note for whoever builds the chumicro-config flat accessor: the upper-and-replace-dots transform (`"wifi.ssid"` → `"WIFI_SSID"`) is the bridge.

### Q6 — `.get()` is the safe accessor; `[]` raises (Pythonic)

User direction:

> "q6 - i guess it makes more sense then to use get('key', default) and get('key') where if none, default is returned.  and since its flat you wont end up with .get('x', {}).get('y', {}) which is great"

Locked: **standard Python dict semantics, made tractable by flat keys.**

- `config.get("wifi.password")` — returns `None` on miss.  Standard `.get()`.
- `config.get("wifi.password", default)` — returns `default` on miss.  Standard `.get()`.
- `config["wifi.password"]` — raises `MissingConfigKey` (subclass of `KeyError`) on miss.  Standard `[]`, with our error type for a beginner-readable message.
- `config.require("wifi.password")` — raises `MissingConfigKey` with extra context (which library declared the requirement).  Used by library code where the key is required.

The flat-key shape eliminates the `.get("x", {}).get("y", {})` chain pain that drives some codebases toward `[]`-returns-None semantics — once keys are flat, a single `.get("x.y")` does the same job cleanly.  No reason to deviate from Python convention.

Q6 resolved.

### Q7 — manifest format follows Q3/Q4 (flat dotted in pyproject.toml)

User direction:

> "q7 - what is pyproject.toml? is that the name from q2? should follow same behavior as q3/q4?"

Clarifying first: `pyproject.toml` is **the library's** packaging metadata file — different from `project_config.toml` (per-user-project) and `secrets.toml` (per-user-workspace).  Each library has one (e.g., `libraries/wifi/pyproject.toml`); it declares the library's name, version, dependencies, and now its config-key requirements via `[tool.chumicro.config]`.

Locked: **manifest format follows Q3/Q4** — flat dotted keys in the pyproject metadata.  Today's nested form:

```toml
[tool.chumicro.config.sections.wifi]
required = ["ssid", "password"]
optional = ["hostname", "connect_timeout_ms", ...]
```

becomes:

```toml
[tool.chumicro.config]
required_keys = ["wifi.ssid", "wifi.password"]
optional_keys = [
    "wifi.hostname",
    "wifi.connect_timeout_ms",
    ...
]
```

Aligns with the runtime accessor (`config.get("wifi.password")`).  Aligns with the validator's failure message (already prints "missing required key 'wifi.password'").  No semantic change to validation — just same vocabulary, end to end.

Q7 resolved.

### Q8 — order of operations + cadence

User direction:

> "q8 the order looks ok but be careful.  and you dont have to commit as often, only if it helps with the next step and rolling back."

Locked sequence (each step internally consistent; commit-cadence is "when rollback would be useful"):

1. **Add the flat-key accessor to `chumicro-config`** alongside the existing nested API.  Both APIs callable; no file format change yet.  Forward-compatible: anything that wants the flat shape can opt in.
2. **Add compose-time flattening to `compose_runtime_config`** so the msgpack wire format becomes flat.  On-device readers have to migrate atomically with this — see step 3.
3. **Migrate libraries one at a time** to use the flat accessor.  WifiService first (already has the manifest).  Each library's migration is one commit.
4. **Add `chumicro-workspace config-validate` CLI** (Q11 lint step).  Independent of file-shape work; can land any time after step 1.
5. **Move credentials out of `workspace.yml` into `secrets.toml`** (host-side material).  Update the workbench payload, the materializer, and both repos.  Decision 0057 is updated or superseded here — needs an ADR.
6. **Migrate per-project `config.toml` → `project_config.toml`** in the template repo.  Touches `examples/*/`, `projects/_template/`, `projects/example_sensor/`, and the mono-repo's functional-test conftests.
7. **Migrate library manifests in pyproject.toml** to flat format.  Aligns with the Q11 push to declare manifests in the six libraries that don't have them yet.
8. **Wire additive-only re-apply behavior** into `setup` (strategy C — the Q10 contract).  Implementation detail: comment-preserving merge in TOML.  Open question 4 of `setup-schema-reconciliation.md` becomes the critical implementation challenge.
9. **Drop the old nested API from `chumicro-config`.**  Final cleanup; no consumers left.

No backward-compat burden — both repos can be updated atomically per step.  Commit cadence: one per step where the step is internally consistent and rollback-able; smaller commits inside a step only when an intermediate state needs preservation (debug, hardware verification, etc.).

Q8 resolved.

---

## Status of all eleven questions

| # | Question | Status (as of 2026-05-06) | Source |
|---|---|---|---|
| Q1 | File rename | ✅ Resolved — split, both files stay, distinct roles | User direction post-verification |
| Q2 | Per-project filename | ✅ Resolved — `project_config.toml` | User direction |
| Q3 | On-disk shape | ✅ Resolved — nested on disk, flat on board, flatten at compose | User direction |
| Q4 | Key naming | ✅ Resolved — lowercase snake within segments, dots between | User direction (Q3 downstream) |
| Q5 | `settings.toml` integration | ✅ Resolved — fallback only, no native support | User direction |
| Q6 | Accessor patterns | ✅ Resolved — standard `.get()` / `[]`-raises / `require()` for libs | User direction |
| Q7 | Manifest format | ✅ Resolved — flat dotted keys in pyproject `[tool.chumicro.config]` | User direction (Q3 downstream) |
| Q8 | Migration sequence | ✅ Resolved — 9-step sequence, no backward-compat burden | User direction |
| Q9 | (n/a — was reserved by an earlier finding) | — | — |
| Q10 | Starter content + re-apply | ✅ Resolved — real placeholders + additive-only re-apply | User direction post-finding-2 |
| Q11 | CI / manifest declaration | ✅ Resolved — CI applies own + add `config-validate` CLI | User direction |

**All design questions resolved.**  Ready for implementation per the Q8 sequence; further design pass not required.

---

## Pre-conditions for a fresh agent picking this up

The design pass is **complete** as of 2026-05-06 — all eleven questions resolved (see status table above).  A fresh agent picking this up is implementing, not designing.

1. Read this file end-to-end.  Treat the **Status of all eleven questions** table + the **Direction set 2026-05-06** section as the spec; the upstream design discussion is context, not negotiable.
2. Read [Decision 0057](../../decisions/0057-two-file-config.md) (current two-file shape) — note that step 5 of the Q8 sequence either updates or supersedes this decision; an ADR pass is part of that step.
3. Read [Decision 0036](../../decisions/0036-chumicro-config-library.md) (`chumicro-config` library API) — the flat-accessor work in step 1 of the Q8 sequence extends this surface.
4. Read [`scripts-workbench-config-unification.md`](scripts-workbench-config-unification.md) (the unification that froze today's plumbing).
5. Read [`setup-schema-reconciliation.md`](setup-schema-reconciliation.md) — strategy C is now the canonical contract per Q10; that workstream's open question 4 (comment preservation in YAML/TOML round-trip) is the critical implementation challenge for Q8 step 8.
6. Skim the workspace-template repo's `examples/wifi_only/` and `projects/example_sensor/` to see what migrating to `project_config.toml` looks like in practice.
7. Pick up at **step 1 of the Q8 sequence**.  Steps 1–4 are host-only plumbing (no user-visible change yet); steps 5–6 land the file split + per-project rename; steps 7–9 finish the migration.  Each step is rollback-able on its own.

## Constraints

- Nothing has been published to PyPI yet.  No backward-compatibility burden on file formats or accessor API names.
- The workspace-template repo must keep working throughout — every change either improves or is a no-op for that repo.
- Decision 0057 (two-file shape, no `!secret`) is the floor — any proposal here has to keep that property.
- Coverage gate stays at 94 %.
- Beginner-ergonomics rubric (the user's "plug in a board and go") is the tie-breaker on every Q above.

---

## Implementation log (2026-05-06)

The Q8 sequence collapsed into five commits — three in the mono-repo, one in the workspace-template repo, and a hardware-validation pass on the four-board canonical matrix.

### Mono-repo commits

1. **`30e2878` — Flatten runtime-config wire shape; migrate chumicro-wifi to flat-key API.**  Picks up Q8 steps 1–3 + 7.  Adds `RuntimeConfig` wrapper to `chumicro-config`; `load_section` / `try_load_section` rewritten with a `prefix` parameter; `WifiConfig.from_config` / `try_from_config` replace `from_dict` / `try_from_dict`; `flatten_config` helper; `compose_runtime_config` / `build_runtime_config` flatten the deep-merged dict before write; `[tool.chumicro.config] required_keys = [...]` flat-key manifest format; seven mono-repo functional-test conftests + on-device tests use flat access (`config["wifi.ssid"]`).  Bumps chumicro-config 0.1.0→0.2.0, chumicro-wifi 0.0.4→0.1.0, chumicro-workspace 0.10.0→0.11.0.
2. **`8303d17` — Split workspace.yml machinery from secrets.toml device-bound config.**  Q8 step 5.  `secrets.toml` becomes the device-bound credentials/defaults file; `workspace.yml` keeps machinery (`library_sources`, `deploy_targets`, `quality`).  New payload + `read_secrets_toml_starter` + `read_secrets_toml`; `compose_runtime_config(secrets_toml=…)` (was `workspace_yaml=`); `WorkspaceLayout.secrets_toml` property; `health.check_secrets_toml`; `starter_drift` walks both files; gitignore + mono-repo's `_workspace_template/` add `secrets.toml`.
3. **`7d36f27` — config-validate CLI + additive setup re-apply + ADR refresh.**  Q8 steps 4 + 8.  New `chumicro-workspace config-validate [<project>...]` runs the manifest validator without deploying.  `additive_reapply` (new module, tomlkit + ruamel) appends upstream-starter keys missing from the user's `workspace.yml` / `secrets.toml` in place, comments preserved (Strategy C of `setup-schema-reconciliation.md` — the canonical contract).  Decisions 0036 + 0057 rewritten in place to describe the flat-key + three-file shape.  Bumps chumicro-workspace 0.11.0→0.12.0.

### Workspace-template repo commit

4. **`72c6ffb` (template repo) — Migrate to flat-key runtime config + secrets.toml + project_config.toml.**  Q8 step 6.  Four example apps + the worked-example sensor app use `WifiConfig.from_config(config)` and `config.require("mqtt.broker")` instead of pre-extracted section dicts.  All `config.toml` files renamed to `project_config.toml` (legacy filename still accepted via `find_project_config`'s fallback).  `.gitignore` adds `/secrets.toml`.  README / CONTRIBUTING / AGENTS / `add-new-project` skill updated for the two-file split.

### Hardware validation (canonical four-board matrix)

| Board | Runtime | wifi acceptance | MQTT round-trip |
|---|---|---|---|
| Pi Pico W | CircuitPython 10.2.0 | 3/3 ✓ | 1/1 ✓ |
| Pi Pico W | MicroPython 1.28.0 | 3/3 ✓ | 1/1 ✓ |
| Lolin S2 | CircuitPython 10.1.4 | 3/3 ✓ | 1/1 ✓ |
| Lolin S2 | MicroPython 1.28.0 | 3/3 ✓ | 1/1 ✓ |

Wifi acceptance exercises `WifiConfig.try_from_config(config)` end-to-end (associate, deliberate disconnect + reconnect, state-callback observation).  MQTT round-trip exercises `config["mqtt.broker.host"]` / `config["mqtt.broker.port"]` flat-key access plus the QoS-1 publish/subscribe loop.  Both cover the new `compose_runtime_config(secrets_toml=…)` host-side path through the on-device flat dict.

### Workstream closed

All eleven design questions resolved + implemented + hardware-validated.  No follow-up open from this workstream — Q11's "declare manifests in the remaining libraries" is its own future workstream (six libraries still ship without `[tool.chumicro.config]` blocks; the `config-validate` CLI lints what's declared, but currently only chumicro-wifi declares anything).
