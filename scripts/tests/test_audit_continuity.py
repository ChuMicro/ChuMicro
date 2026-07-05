"""Tests for the audit skills' continuity keystone (`.github/skills/_shared/audit_continuity.py`).

The keystone is one fingerprint used four ways, so the tests are grouped by use:

* fingerprint + matching — the fuzzy identity: reword tolerance (defect token overlap), rename /
  move tolerance (file basename + symbol leaf fallbacks), and the locus gate that keeps two
  distinct findings on the same symbol apart;
* baseline stamping — new / persisting / resolved across two runs, and a prior skip-with-note
  preloaded onto its match;
* waiver ledger — record / load round-trip, the coarse file pre-filter, and the deterministic
  suppression that only ever fires on a real ledger entry;
* incremental — the cheap "is it still live" re-check against a file on disk, and prior-run
  detection over the persisted `<slug>-<UTC>` directory names.

Pure Python — no jedi, no clean room, no git needed except the two tests that build a tiny repo.
"""

import subprocess
import sys
from pathlib import Path

SHARED_DIR = Path(__file__).resolve().parents[2] / ".github" / "skills" / "_shared"
if str(SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(SHARED_DIR))

import audit_continuity as ac  # noqa: E402, I001  (imported after SHARED_DIR joins sys.path, above)


def _finding(fid, file, symbol, defect, **extra):
    base = {"id": fid, "file": file, "symbol": symbol, "defect": defect,
            "angle": "trap", "severity": "high", "site": defect}
    base.update(extra)
    return base


# --- fingerprint + matching ---

def test_fingerprint_tokenizes_and_normalizes():
    fp = ac.fingerprint(_finding(1, "./libraries/mqtt/src/mqtt.py", "Client._recv",
                                 "recv_exact loops over the socket and a short read spins"))
    assert fp["file"] == "libraries/mqtt/src/mqtt.py"      # leading ./ stripped
    assert fp["basename"] == "mqtt.py"
    assert fp["symbol"] == "Client._recv"
    assert fp["symbol_leaf"] == "_recv"
    assert "recv_exact" in fp["tokens"] and "spins" in fp["tokens"]
    assert "the" not in fp["tokens"] and "and" not in fp["tokens"]   # stopwords dropped
    assert "a" not in fp["tokens"]                                   # length-filtered


def test_removed_prefix_stripped_from_symbol():
    assert ac.fingerprint({"symbol": "removed:old_helper"})["symbol"] == "old_helper"


def test_reworded_defect_still_matches():
    fp_a = ac.fingerprint(_finding(1, "a.py", "Foo.bar", "off-by-one loop bound skips last element"))
    fp_b = ac.fingerprint(_finding(2, "a.py", "Foo.bar", "loop bound off-by-one drops the final element"))
    assert ac.similarity(fp_a, fp_b) >= ac.MATCH_THRESHOLD


def test_distinct_findings_on_same_symbol_stay_apart():
    fp_a = ac.fingerprint(_finding(1, "a.py", "Foo.bar", "off-by-one loop bound skips last element"))
    fp_b = ac.fingerprint(_finding(2, "a.py", "Foo.bar", "unclosed socket descriptor leaks on retry path"))
    assert ac.similarity(fp_a, fp_b) < ac.MATCH_THRESHOLD


def test_different_locus_never_matches():
    fp_a = ac.fingerprint(_finding(1, "a.py", "Foo.bar", "identical wording of the very same defect here"))
    fp_b = ac.fingerprint(_finding(2, "b.py", "Baz.qux", "identical wording of the very same defect here"))
    assert ac.similarity(fp_a, fp_b) == 0.0


def test_moved_file_matches_on_basename_with_strong_defect_overlap():
    fp_a = ac.fingerprint(_finding(1, "old/dir/mqtt.py", "Client.push",
                                "queue push overwrites the pending frame when the buffer is full"))
    fp_b = ac.fingerprint(_finding(2, "new/place/mqtt.py", "Client.push",
                                "queue push overwrites the pending frame when the buffer is full"))
    assert ac.similarity(fp_a, fp_b) >= ac.MATCH_THRESHOLD


def test_best_match_returns_none_below_threshold():
    fp = ac.fingerprint(_finding(1, "a.py", "Foo.bar", "wholly unrelated wording alpha beta gamma"))
    other = _finding(9, "a.py", "Foo.bar", "completely different delta epsilon zeta")
    payload, score = ac.best_match(fp, [(ac.fingerprint(other), "hit")])
    assert payload is None and score < ac.MATCH_THRESHOLD


# --- baseline stamping ---

def test_stamp_baseline_new_persisting_resolved():
    prior = [
        _finding(1, "a.py", "Foo.bar", "off-by-one in the loop bound skips the last element"),
        _finding(2, "a.py", "Baz.qux", "leaked socket descriptor on the retry path never closed"),
    ]
    current = [
        _finding(10, "a.py", "Foo.bar", "loop bound off-by-one drops the final element"),   # persisting
        _finding(11, "a.py", "New.sym", "fresh finding nobody saw before mu nu xi"),          # new
    ]
    stamped, resolved = ac.stamp_baseline(current, prior)
    by_id = {f["id"]: f for f in stamped}
    assert by_id[10]["baseline_status"] == "persisting"
    assert by_id[11]["baseline_status"] == "new"
    assert [r["id"] for r in resolved] == [2]                # Baz.qux is gone -> resolved
    assert resolved[0]["baseline_status"] == "resolved"


def test_stamp_baseline_preloads_prior_skip_note():
    prior = [_finding(3, "a.py", "Foo.bar", "off-by-one in the loop bound skips the last element")]
    current = [_finding(7, "a.py", "Foo.bar", "loop bound off-by-one drops the final element")]
    picks = ac.parse_picks("3 = skip\nnote 3: intentional — the caller already clamps the index")
    stamped, _resolved = ac.stamp_baseline(current, prior, prior_picks=picks)
    assert stamped[0]["preload_choice"] == "skip"
    assert "caller already clamps" in stamped[0]["preload_note"]


def test_parse_picks_handles_namespaced_ids():
    picks = ac.parse_picks("heartbeat#3 = skip\nnote heartbeat#3: keep as-is")
    assert picks["heartbeat#3"]["choice"] == "skip"
    assert picks["3"]["note"] == "keep as-is"          # bare integer tail indexed too


def test_stamp_baseline_does_not_mutate_inputs():
    current = [_finding(1, "a.py", "Foo.bar", "some defect wording alpha beta gamma delta")]
    ac.stamp_baseline(current, [])
    assert "baseline_status" not in current[0]


# --- waiver ledger ---

def test_record_and_load_waiver_round_trip(tmp_path):
    finding = _finding(1, "libraries/mqtt/src/mqtt.py", "Client._recv",
                       "recv_exact loops without a byte bound; a short read spins")
    entry = ac.record_waiver(str(tmp_path), finding, "documented in Decision 0106",
                             date="2026-07-05", target="libraries/mqtt/src/mqtt.py", skill="audit-code")
    assert entry["note"] == "documented in Decision 0106"
    assert entry["date"] == "2026-07-05"
    assert entry["fingerprint"]["symbol"] == "Client._recv"
    loaded = ac.load_ledger(str(tmp_path))
    assert len(loaded) == 1 and loaded[0]["note"] == "documented in Decision 0106"


def test_waivers_for_files_coarse_prefilter(tmp_path):
    ac.record_waiver(str(tmp_path), _finding(1, "libraries/mqtt/src/mqtt.py", "A.b", "defect one here"),
                     "n1", date="2026-07-05")
    ac.record_waiver(str(tmp_path), _finding(2, "libraries/wifi/src/wifi.py", "C.d", "defect two here"),
                     "n2", date="2026-07-05")
    ledger = ac.load_ledger(str(tmp_path))
    kept = ac.waivers_for_files(ledger, ["libraries/mqtt/src/mqtt.py"])
    assert len(kept) == 1 and kept[0]["note"] == "n1"


def test_apply_waivers_suppresses_only_matching(tmp_path):
    ac.record_waiver(str(tmp_path), _finding(1, "a.py", "Foo.bar", "off-by-one loop bound skips last"),
                     "known and accepted", date="2026-07-05")
    waivers = ac.load_ledger(str(tmp_path))
    findings = [
        _finding(1, "a.py", "Foo.bar", "loop bound off-by-one drops the final element"),   # matches waiver
        _finding(2, "a.py", "Baz.qux", "unrelated leaked descriptor wording entirely"),     # does not
    ]
    suppressed = ac.apply_waivers(findings, waivers)
    assert suppressed == 1
    assert findings[0]["suppressed"] is True and findings[0]["waiver_note"] == "known and accepted"
    assert findings[0]["baseline_status"] == "waived"
    assert "suppressed" not in findings[1]


# --- incremental ---

def test_cheap_recheck_site_present_and_gone(tmp_path):
    source_file = tmp_path / "mod.py"
    source_file.write_text("def f():\n    return ticks_diff(a, b) >= 0\n")
    live = _finding(1, "mod.py", "f", "boundary sign", site="return ticks_diff(a, b) >= 0")
    gone = _finding(2, "mod.py", "f", "boundary sign", site="return no_such_call(x) < 0")
    assert ac.cheap_recheck(live, str(tmp_path)) == "persisting"
    assert ac.cheap_recheck(gone, str(tmp_path)) == "resolved"


def test_cheap_recheck_missing_file_is_resolved(tmp_path):
    finding = _finding(1, "gone.py", "f", "whatever", site="x = 1")
    assert ac.cheap_recheck(finding, str(tmp_path)) == "resolved"


def test_carry_forward_carries_unchanged_live_and_tracks_resolved(tmp_path):
    (tmp_path / "unchanged.py").write_text("def f():\n    return live_call()\n")
    prior = [
        _finding(1, "unchanged.py", "f", "boundary sign wrong here alpha", site="return live_call()"),
        _finding(2, "unchanged.py", "g", "gone defect wording beta", site="return dead_call()"),
        _finding(3, "changed.py", "h", "this file was re-audited gamma", site="x = 1"),
    ]
    current = [_finding(9, "changed.py", "h", "fresh finding on the changed file", site="x = 1")]
    carried, resolved = ac.carry_forward(prior, current, {"changed.py"}, str(tmp_path))
    # #1 (unchanged file, site present) carried past the current max id; #2 (site gone) resolved;
    # #3 (changed file — got a fresh lens pass) neither carried nor tracked resolved here
    assert [c["id"] for c in carried] == [10]
    assert carried[0]["carried"] is True and carried[0]["baseline_status"] == "persisting"
    assert carried[0]["symbol"] == "f"
    assert [r["id"] for r in resolved] == [2]


def test_find_prior_runs_orders_newest_first(tmp_path):
    for name in ["wifi-20260101T000000Z", "wifi-20260705T101010Z", "wifi-notarun", "other-20260705T101010Z"]:
        (tmp_path / name).mkdir()
    runs = ac.find_prior_runs(str(tmp_path), "wifi")
    assert [Path(r).name for r in runs] == ["wifi-20260705T101010Z", "wifi-20260101T000000Z"]


def test_persist_run_copies_substrate_and_manifest(tmp_path):
    room = tmp_path / "room"
    room.mkdir()
    (room / "eval.json").write_text('{"findings": []}')
    (room / "picker.html").write_text("<html></html>")
    dest = tmp_path / "persisted"
    copied = ac.persist_run(str(room), str(dest), head_sha="abc123", slug="wifi", target="x.py")
    assert "eval.json" in copied and "picker.html" in copied
    manifest = (dest / "persisted.json")
    assert manifest.exists()
    import json
    meta = json.loads(manifest.read_text())
    assert meta["head_sha"] == "abc123" and meta["slug"] == "wifi"


def test_delta_files_over_real_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)

    git("init")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (repo / "a.py").write_text("x = 1\n")
    (repo / "b.py").write_text("y = 1\n")
    git("add", "-A")
    git("commit", "-m", "base")
    first = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                           capture_output=True, text=True).stdout.strip()
    (repo / "b.py").write_text("y = 2\n")
    git("add", "-A")
    git("commit", "-m", "touch b")
    changed = ac.delta_files(str(repo), first, "HEAD")
    assert changed == {"b.py"}
