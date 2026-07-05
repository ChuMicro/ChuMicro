#!/usr/bin/env python3
"""Continuity keystone for the clean-room audit skills (audit-code, audit-branch).

Each audit run used to be an island: a re-audit of the same target re-found everything, skipped
findings resurfaced as noise, fixed findings were indistinguishable from persisting ones, and the
pipeline paid full cost even when two files changed. This module is the one shared piece the whole
continuity story keys on — a FINGERPRINT and the fuzzy match over it — used four ways:

  * baseline stamping        (`stamp_baseline`)  — new / persisting / resolved across two runs;
  * prior skip-with-note      (`stamp_baseline`)  — a prior skip's note preloaded onto its match;
  * waiver-ledger matching    (`apply_waivers`)   — a human-recorded waiver suppresses its finding;
  * incremental carry         (`cheap_recheck`)   — a carried finding re-checked without a lens pass.

FINGERPRINT — a finding is identified by WHERE it lives (file + symbol) and WHAT it says (a
normalized defect fragment), never by line number. Line numbers come off comment-stripped copies
and shift every run, so keying on them would lose a finding after any edit; keying on the quoted
symbol + a token-set of the defect is drift-tolerant by construction. File and symbol each carry a
coarse fallback (basename, leaf name) so a moved file or a renamed enclosing class still matches.
The defect is compared as a Jaccard overlap of salient tokens, so a reworded fragment still matches
its prior self while two genuinely different findings on the same symbol stay apart.

WAIVER LEDGER — the central committed registry (`plans/audit-waivers/ledger.jsonl`, one JSON object
per line) the skill writes at skip-with-note time. Each entry is the quoted human note + the
finding's fingerprint + the date. Staging pre-filters the ledger to the audited files and copies the
slice into the room; the pipeline's actionability gate then suppresses any finding whose fingerprint
matches an entry, marking it with the quoted note. A suppression therefore ALWAYS traces to a human
decision recorded in the ledger — the orchestrator never filters on its own authority (clean-room
invariant 9).

REPO-SPECIFIC (ChuMicro): the ledger's default home is `plans/audit-waivers/` under the repo root,
and persisted runs live under `.scratch/audits/` — both are this workspace's conventions. Porting
these skills means pointing `default_ledger_dir` / the persistence root elsewhere (or passing
`--ledger` / an explicit dest); the fingerprint and matching are repo-agnostic.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime

# --- fingerprint -----------------------------------------------------------------------------

# Stopwords stripped before the defect token-set: articles/prepositions plus the words that recur
# in almost every defect fragment ("code", "value", "call", "when"...). Removing them keeps the
# Jaccard overlap driven by the SALIENT nouns/verbs that distinguish one defect from another.
STOPWORDS = frozenset("""
a an the and or but if then else when while for from into onto over under of to in on at by with
is are was were be been being do does did has have had not no nor so than that this these those it
its as via per not_ code value call calls called caller callee case cases path paths line lines
returns return returned method function symbol field arg args param params object which where what
""".split())

_TOKEN_RE = re.compile(r"[a-z0-9_]+")
_WS_RE = re.compile(r"\s+")


def _read_text(path):
    with open(path, encoding="utf-8", errors="replace") as handle:
        return handle.read()


def _dump_json(payload, path):
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=1)


def _load_json(path):
    with open(path) as handle:
        return json.load(handle)


def _norm_path(path):
    """Repo-relative path, normalized: forward slashes, no leading `./`. Case preserved (paths are
    case-sensitive on the runtimes these repos target)."""
    if not path:
        return ""
    return str(path).strip().replace("\\", "/").lstrip("./") or ""


def _basename(path):
    return _norm_path(path).rsplit("/", 1)[-1]


def _norm_symbol(symbol):
    """The finding's enclosing qualname, minus the branch lens's `removed:` marker."""
    if not symbol:
        return ""
    text = str(symbol).strip()
    if text.startswith("removed:"):
        text = text[len("removed:"):].strip()
    return text


def _leaf_symbol(symbol):
    return _norm_symbol(symbol).rsplit(".", 1)[-1]


def defect_tokens(text):
    """The salient token set of a defect fragment: lowercased word tokens, minus stopwords and
    very short tokens. This is what makes matching reword-tolerant — order and grammar drop out,
    only the distinguishing terms remain."""
    if not text:
        return frozenset()
    return frozenset(t for t in _TOKEN_RE.findall(str(text).lower())
                     if len(t) > 2 and t not in STOPWORDS)


def fingerprint(finding, default_file=""):
    """A finding's location-and-substance fingerprint, JSON-serializable.

    `default_file` supplies the file for a single-target audit-code finding, which carries a
    `symbol` but no `file` (the whole run is one file); a branch finding names its own `file`.
    """
    file = _norm_path(finding.get("file") or default_file)
    symbol = _norm_symbol(finding.get("symbol"))
    defect = str(finding.get("defect") or finding.get("bite") or "").strip()
    return {
        "file": file,
        "basename": _basename(file),
        "symbol": symbol,
        "symbol_leaf": _leaf_symbol(symbol),
        "defect": defect,
        "tokens": sorted(defect_tokens(defect)),
    }


# --- matching --------------------------------------------------------------------------------

# Weights and threshold for similarity(). File and symbol are GATES (both must be > 0, or the two
# findings are at a different locus and can never be the same one); past the gate the defect token
# overlap does most of the discriminating, so two distinct findings on one symbol stay apart while a
# reworded fragment still re-matches its prior self. Tuned so: exact locus needs only a weak token
# overlap (>~1 salient shared term) to match; a moved file / renamed class (coarse-fallback locus)
# needs a stronger overlap to compensate.
_W_FILE, _W_SYMBOL, _W_DEFECT = 0.2, 0.2, 0.6
MATCH_THRESHOLD = 0.5


def _jaccard(a, b):
    a, b = set(a), set(b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _file_score(a, b):
    if a["file"] and a["file"] == b["file"]:
        return 1.0
    if a["basename"] and a["basename"] == b["basename"]:
        return 0.6
    return 0.0


def _symbol_score(a, b):
    if a["symbol"] and a["symbol"] == b["symbol"]:
        return 1.0
    if a["symbol_leaf"] and a["symbol_leaf"] == b["symbol_leaf"]:
        return 0.6
    return 0.0


def similarity(a, b):
    """0..1 similarity of two fingerprints. 0 when they sit at a different locus (the file/symbol
    gate); otherwise a weighted blend dominated by defect-token overlap."""
    file_score = _file_score(a, b)
    symbol_score = _symbol_score(a, b)
    if file_score == 0.0 or symbol_score == 0.0:
        return 0.0
    return _W_FILE * file_score + _W_SYMBOL * symbol_score + _W_DEFECT * _jaccard(a["tokens"], b["tokens"])


def best_match(fp, candidates, threshold=MATCH_THRESHOLD):
    """Best (payload, score) among candidates `[(fingerprint, payload), ...]`, or (None, best_score)
    when nothing clears the threshold."""
    best_payload, best_score = None, 0.0
    for cand_fp, payload in candidates:
        score = similarity(fp, cand_fp)
        if score > best_score:
            best_payload, best_score = payload, score
    return (best_payload, best_score) if best_score >= threshold else (None, best_score)


# --- selection blob (prior picks) ------------------------------------------------------------

_CHOICE_LINE = re.compile(r"^\s*([A-Za-z0-9_.#-]+)\s*=\s*(apply|discuss|skip)\s*$")
_NOTE_LINE = re.compile(r"^\s*note\s+([A-Za-z0-9_.#-]+)\s*:\s*(.*\S)\s*$")


def parse_picks(text):
    """The prior run's selection blob -> {id: {"choice": ..., "note": ...}}.

    Mirrors the picker's line-oriented paste-back format (`<id> = <choice>` plus `note <id>: ...`
    riders); this reader ignores everything else so a partial or hand-typed blob still yields what
    it can. In library/merge scope the ids are namespaced (`heartbeat#3`); the numeric tail after
    the last `#` is also indexed so a matched prior finding's integer id still resolves."""
    picks = {}
    for raw in (text or "").splitlines():
        line = raw.strip()
        match = _CHOICE_LINE.match(line)
        if match:
            picks.setdefault(match.group(1), {})["choice"] = match.group(2)
            continue
        match = _NOTE_LINE.match(line)
        if match:
            picks.setdefault(match.group(1), {})["note"] = match.group(2)
    # index the bare integer tail of a namespaced id too, so lookups by a prior finding's id work
    expanded = {}
    for key, value in picks.items():
        expanded[key] = value
        tail = key.rsplit("#", 1)[-1]
        if tail != key and tail.isdigit():
            expanded.setdefault(tail, value)
    return expanded


# --- baseline stamping -----------------------------------------------------------------------

def stamp_baseline(current, prior, prior_picks=None, default_file=""):
    """Annotate each current finding with a `baseline_status` against the prior run, and return the
    prior findings that no longer appear.

    Every current finding gains `baseline_status`: "persisting" when a prior finding matches it,
    else "new". A current finding matched to a prior finding the human SKIPPED WITH A NOTE also
    gains `preload_choice="skip"` + `preload_note` — the renderer defaults its card to skip and
    shows the note, so a decision the human already made does not have to be made again. Prior
    findings that match nothing current are returned as `resolved` — the finding was there last
    time and is gone now.

    Mutates copies, not the inputs. `prior_picks` maps a prior finding's id (str or int) to
    {"choice", "note"} (from `parse_picks`)."""
    prior_picks = prior_picks or {}
    prior_fps = [(fingerprint(p, default_file), p) for p in prior]
    matched_prior = set()
    stamped = []
    for finding in current:
        clone = dict(finding)
        fp = fingerprint(finding, default_file)
        match, _score = best_match(fp, prior_fps)
        if match is not None:
            clone["baseline_status"] = "persisting"
            matched_prior.add(id(match))
            pick = prior_picks.get(match.get("id")) or prior_picks.get(str(match.get("id")))
            if pick and pick.get("choice") == "skip" and pick.get("note"):
                clone["preload_choice"] = "skip"
                clone["preload_note"] = pick["note"]
        else:
            clone["baseline_status"] = "new"
        stamped.append(clone)
    resolved = []
    for prior_finding in prior:
        if id(prior_finding) not in matched_prior:
            ghost = dict(prior_finding)
            ghost["baseline_status"] = "resolved"
            resolved.append(ghost)
    return stamped, resolved


# --- waiver ledger ---------------------------------------------------------------------------

LEDGER_FILE = "ledger.jsonl"


def _repo_root(start="."):
    result = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                            cwd=start, capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else os.path.abspath(start)


def default_ledger_dir(start="."):
    """REPO-SPECIFIC (ChuMicro): `plans/audit-waivers/` under the repo root."""
    return os.path.join(_repo_root(start), "plans", "audit-waivers")


def load_ledger(ledger_dir):
    """Every waiver entry in the ledger (a malformed line is skipped, never fatal)."""
    path = os.path.join(ledger_dir, LEDGER_FILE)
    entries = []
    if not os.path.exists(path):
        return entries
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except ValueError:
                continue
    return entries


def record_waiver(ledger_dir, finding, note, date=None, target="", skill="", run="", default_file=""):
    """Append one waiver entry — the quoted human note + the finding's fingerprint + the date — and
    return it. The skill calls this once per skip-with-note, so the file is ledger-formatted because
    the skill writes it, not because a human hand-curated it."""
    entry = {
        "date": date or datetime.now(UTC).strftime("%Y-%m-%d"),
        "note": (note or "").strip(),
        "fingerprint": fingerprint(finding, default_file),
        "angle": finding.get("angle", ""),
        "severity": finding.get("severity", ""),
        "target": _norm_path(target),
        "skill": skill,
        "run": run,
    }
    os.makedirs(ledger_dir, exist_ok=True)
    with open(os.path.join(ledger_dir, LEDGER_FILE), "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def waivers_for_files(ledger, files):
    """Coarse file-level pre-filter for staging: the waivers whose fingerprint touches one of the
    audited files (exact path or basename). The full fingerprint match happens later, against the
    actual findings; this only keeps the room's `waivers.json` to the relevant slice."""
    paths = {_norm_path(f) for f in files}
    bases = {_basename(f) for f in files}
    out = []
    for waiver in ledger:
        fp = waiver.get("fingerprint", {})
        if fp.get("file") in paths or fp.get("basename") in bases:
            out.append(waiver)
    return out


def stage_waivers(rundir, files, ledger_dir=None):
    """Copy the ledger's file-relevant slice into the room as `waivers.json`, for the merger's
    actionability gate to consult. Returns the count staged. Called by the phase-1 launchers before
    the clean-room workflow runs — the room's copy is what makes the suppression traceable to a
    human decision without the workflow reaching into `plans/`."""
    ledger_dir = ledger_dir or default_ledger_dir(rundir if os.path.isdir(rundir) else ".")
    matched = waivers_for_files(load_ledger(ledger_dir), files)
    _dump_json({"waivers": matched}, os.path.join(rundir, "waivers.json"))
    return len(matched)


def load_staged_waivers(rundir):
    """The waivers staged into a room by `stage_waivers` (empty when none were staged)."""
    path = os.path.join(rundir, "waivers.json")
    if not os.path.exists(path):
        return []
    data = _load_json(path)
    return data.get("waivers", []) if isinstance(data, dict) else data


def match_waiver(finding, waivers, default_file=""):
    """The waiver whose fingerprint matches this finding, or None."""
    fp = fingerprint(finding, default_file)
    candidates = [(w.get("fingerprint", {}), w) for w in waivers]
    match, _score = best_match(fp, candidates)
    return match


def apply_waivers(findings, waivers, default_file=""):
    """Mark every finding that matches a human waiver as suppressed, carrying the quoted note.

    Deterministic — a finding is suppressed if and ONLY if a real ledger entry matches its
    fingerprint, so the suppression always traces to a human decision (invariant 9). Mutates the
    findings in place (they are about to be re-serialized to eval.json) and returns the count."""
    suppressed = 0
    for finding in findings:
        waiver = match_waiver(finding, waivers, default_file)
        if waiver is not None:
            finding["suppressed"] = True
            finding["waiver_note"] = waiver.get("note", "")
            finding.setdefault("baseline_status", "waived")
            suppressed += 1
    return suppressed


# --- incremental re-audit --------------------------------------------------------------------

def find_prior_runs(persist_root, slug):
    """Newest-first list of a slug's persisted run dirs under `persist_root` (named
    `<slug>-<UTC>`, UTC = `%Y%m%dT%H%M%SZ` so the name sorts chronologically)."""
    if not os.path.isdir(persist_root):
        return []
    pattern = re.compile(r"^" + re.escape(slug) + r"-\d{8}T\d{6}Z$")
    runs = [os.path.join(persist_root, name) for name in os.listdir(persist_root)
            if pattern.match(name) and os.path.isdir(os.path.join(persist_root, name))]
    runs.sort(reverse=True)
    return runs


def delta_files(repo_root, prior_head, head="HEAD"):
    """The repo-relative paths changed between the last audited head and the current one — the set
    a re-audit must pay a fresh lens pass for. Everything else is carried."""
    result = subprocess.run(["git", "-C", repo_root, "diff", "--name-only", f"{prior_head}..{head}"],
                            capture_output=True, text=True)
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def carry_forward(prior_findings, current_findings, changeset_files, repo_root, default_file=""):
    """Carry a prior run's findings forward on the incremental path (phase 4).

    A re-audit stages only the delta range (`prior-head..new-head`), so the lenses pay for the
    changed files only; the prior findings on the UNCHANGED files are carried here instead of
    re-judged. Each carried candidate (a prior finding whose file is not in the current change-set)
    gets a cheap `cheap_recheck` — its quoted site still present means it persists, gone means it was
    resolved. A carried-live finding a fresh current finding already re-found is dropped (the fresh
    one, with its patch and validator verdict, wins).

    Returns (carried_live, resolved): carried_live findings get ids past the current max, a
    `carried` flag, and `baseline_status="persisting"` (the renderer greys them); resolved are
    returned for counting/tracking, not injected."""
    changeset = {_norm_path(path) for path in changeset_files}
    current_fps = [(fingerprint(finding, default_file), finding) for finding in current_findings]
    next_id = max((finding.get("id", 0) for finding in current_findings), default=0) + 1
    carried_live, resolved = [], []
    for prior in prior_findings:
        if _norm_path(prior.get("file") or default_file) in changeset:
            continue                                  # this file got a fresh lens pass
        if cheap_recheck(prior, repo_root, default_file) == "resolved":
            resolved.append(prior)
            continue
        match, _score = best_match(fingerprint(prior, default_file), current_fps)
        if match is not None:
            continue                                  # a fresh finding already covers it
        clone = dict(prior)
        clone["id"] = next_id
        clone["carried"] = True
        clone["baseline_status"] = "persisting"
        carried_live.append(clone)
        next_id += 1
    return carried_live, resolved


def cheap_recheck(finding, repo_root, default_file=""):
    """Is a carried finding still live, without a fresh lens pass? Its quoted `site` still present
    in the current file -> "persisting"; the site (or the file) gone -> "resolved".

    Whitespace-normalized substring match, so reflow/indent drift does not lose the anchor. Cheaper
    and more honest than re-running a lens: it can tell that the flagged code is gone, not that a
    subtle defect elsewhere was fixed — which is exactly the carry decision, not a re-judgment."""
    fp = fingerprint(finding, default_file)
    if not fp["file"]:
        return "persisting"
    path = os.path.join(repo_root, fp["file"])
    if not os.path.exists(path):
        return "resolved"
    site = (finding.get("site") or "").strip()
    if not site:
        return "persisting"
    needle = _WS_RE.sub(" ", site.splitlines()[0]).strip()
    haystack = _WS_RE.sub(" ", _read_text(path))
    return "persisting" if needle and needle in haystack else "resolved"


# --- persistence -----------------------------------------------------------------------------

# The full findings substrate a persisted run keeps, so a later re-audit is comparable AND its
# carried findings keep their prose + patch (not just the fact fragments). The /tmp room dies with
# the machine; this copy is what every continuity item reads.
PERSIST_ARTIFACTS = ("eval.json", "written.json", "patches.json", "summary.json", "validation.json",
                     "phase1.json", "manifest.json", "spec.json", "picker.html", "selection.txt")


def persist_run(rundir, dest_dir, head_sha="", slug="", target=""):
    """Copy a run room's findings substrate into `dest_dir` and stamp a `persisted.json` manifest
    (source room, head SHA, slug, target, UTC, artifacts). Returns the copied artifact names."""
    os.makedirs(dest_dir, exist_ok=True)
    copied = []
    for name in PERSIST_ARTIFACTS:
        src = os.path.join(rundir, name)
        if os.path.exists(src):
            shutil.copy(src, os.path.join(dest_dir, name))
            copied.append(name)
    meta = {
        "source_rundir": os.path.abspath(rundir),
        "head_sha": head_sha,
        "slug": slug,
        "target": target,
        "persisted_utc": datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        "artifacts": copied,
    }
    _dump_json(meta, os.path.join(dest_dir, "persisted.json"))
    return copied


# --- CLI ---------------------------------------------------------------------------------------

def _load_json(path, default):
    return _load_json(path) if os.path.exists(path) else default


def _findings_of(rundir):
    evaluation = _load_json(os.path.join(rundir, "eval.json"), {"findings": []})
    if isinstance(evaluation, list):
        return evaluation
    return evaluation.get("findings", [])


def _flag(args, name, default=None):
    return args[args.index(name) + 1] if name in args else default


def cmd_persist(args):
    """persist <rundir> (--into <root> --slug <slug> | --dest <dir>) [--head <sha>] [--target <t>]

    `--head` / `--target` default to the room's manifest.json / phase1.json, so a branch run needs
    only `--into <root> --slug <slug>`."""
    rundir = os.path.abspath(args[0])
    manifest = _load_json(os.path.join(rundir, "manifest.json"), {})
    phase1 = _load_json(os.path.join(rundir, "phase1.json"), {})
    head = _flag(args, "--head") or manifest.get("head_sha") or phase1.get("head_sha") or ""
    target = _flag(args, "--target") or phase1.get("target") or manifest.get("label") or ""
    slug = _flag(args, "--slug", "")
    dest = _flag(args, "--dest")
    into = _flag(args, "--into")
    if not dest:
        if not into or not slug:
            sys.exit("persist: give --dest <dir>, or both --into <root> and --slug <slug>")
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        dest = os.path.join(os.path.abspath(into), f"{slug}-{stamp}")
    copied = persist_run(rundir, dest, head_sha=head, slug=slug, target=target)
    print(f"PERSISTED {dest}")
    print(f"  artifacts: {', '.join(copied) or '(none found in room)'}")
    return 0


def cmd_find_prior(args):
    """find-prior --root <persist_root> --slug <slug>   -> newest prior run + its head + eval path"""
    root = os.path.abspath(_flag(args, "--root", ""))
    slug = _flag(args, "--slug", "")
    if not root or not slug:
        sys.exit("find-prior: --root <persist_root> --slug <slug>")
    runs = find_prior_runs(root, slug)
    if not runs:
        print("NO-PRIOR")
        return 0
    newest = runs[0]
    meta = _load_json(os.path.join(newest, "persisted.json"), {})
    print(f"PRIOR {newest}")
    print(f"  eval: {os.path.join(newest, 'eval.json')}")
    print(f"  persisted_utc: {meta.get('persisted_utc', '?')}   head_sha: {meta.get('head_sha', '?')}")
    print(f"  older_runs: {len(runs) - 1}")
    return 0


def cmd_record_waiver(args):
    """record-waiver --run <rundir> --id <finding_id> --note <text> [--ledger <dir>] [--date <YMD>]

    Pulls the finding out of the run's eval.json by id and appends a ledger entry. The target and
    skill come from the run's phase1.json, so the orchestrator passes only the id and the note."""
    rundir = os.path.abspath(_flag(args, "--run", ""))
    fid = _flag(args, "--id")
    note = _flag(args, "--note", "")
    if not rundir or fid is None:
        sys.exit("record-waiver: --run <rundir> --id <finding_id> --note <text>")
    ledger_dir = _flag(args, "--ledger") or default_ledger_dir(rundir if os.path.isdir(rundir) else ".")
    phase1 = _load_json(os.path.join(rundir, "phase1.json"), {})
    target = phase1.get("target", "")
    default_file = target if str(target).endswith(".py") else ""
    findings = _findings_of(rundir)
    match = next((f for f in findings if str(f.get("id")) == str(fid)), None)
    if match is None:
        sys.exit(f"record-waiver: no finding id={fid} in {os.path.join(rundir, 'eval.json')}")
    skill = "audit-branch" if os.path.exists(os.path.join(rundir, "manifest.json")) else "audit-code"
    entry = record_waiver(ledger_dir, match, note, date=_flag(args, "--date"),
                          target=target, skill=skill, run=os.path.basename(rundir),
                          default_file=default_file)
    print(f"WAIVER RECORDED -> {os.path.join(ledger_dir, LEDGER_FILE)}")
    print(f"  {json.dumps(entry, ensure_ascii=False)}")
    return 0


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: audit_continuity.py <persist|find-prior|record-waiver> ...")
    command, rest = sys.argv[1], sys.argv[2:]
    dispatch = {"persist": cmd_persist, "find-prior": cmd_find_prior, "record-waiver": cmd_record_waiver}
    handler = dispatch.get(command)
    if not handler:
        sys.exit(f"audit_continuity.py: unknown command {command!r} "
                 f"(persist | find-prior | record-waiver)")
    sys.exit(handler(rest))


if __name__ == "__main__":
    main()
