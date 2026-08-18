"""Staged gate-hardening for the DoD stop gate and persona anchor (2026-07-29 register,
phase 1; scripts/staged_hooks/, human-installed via scripts/apply-project-anchor.sh).

  G3 - [reproduced] the stop gate was a silent no-op in plugin mode: launched by absolute
       path from a foreign project, `from scripts.check_artifacts import ...` never
       resolved and the bare `except` swallowed it. The staged copy falls back to a
       __file__-relative load (the same fallback check_artifacts itself carries), and the
       subprocess test here imports the hook exactly the way plugin mode does - the
       in-process suite structurally could not catch this class.
  G5 - both hooks now delegate to the checker's shared `pack_status` instead of a raw
       emoji-substring sniff: a words-only status arms them, a stray ⏳ in a closed index
       no longer re-arms them.
  G8 - the derived registry is checked at turn end while any pack is gated.
  R5 - the nudge tells an interrupted close to FINISH (set-status closing -> closed),
       never to delete close artifacts.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"staged_{name}", REPO_ROOT / "scripts" / "staged_hooks" / f"{name}.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Session scoping (2026-08-16): staged hooks arm only on a payload-session match with
# the stamp in artifacts/.team-session.json - both run helpers below provide it.
_SID = "sess-hardening-suite"


def _stamp_if_artifacts(project: Path) -> None:
    art = project / "artifacts"
    if art.is_dir():
        (art / ".team-session.json").write_text(
            json.dumps({"session": _SID}), encoding="utf-8"
        )


def _run_gate(monkeypatch, capsys, payload: dict, project: Path):
    payload.setdefault("session_id", _SID)
    _stamp_if_artifacts(project)
    gate = _load("dod_stop_gate")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = gate.main()
    return rc, capsys.readouterr().out


def _run_anchor(monkeypatch, capsys, payload: dict, project: Path):
    payload.setdefault("session_id", _SID)
    _stamp_if_artifacts(project)
    pa = _load("persona_anchor")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = pa.main()
    return rc, capsys.readouterr().out


def _ws(project: Path, slug: str, status: str = "in_progress"):
    from scripts.engagement_state import main as es_main

    art = project / "artifacts"
    es_main(["--dir", str(art / slug), "init", "--title", slug, "--slug", slug])
    if status != "in_progress":
        es_main(["--dir", str(art / slug), "set-status", status])
    return art


# --- G3: plugin-mode subprocess (the class the in-process suite cannot see) ---------------


def test_stop_gate_fires_in_plugin_mode_subprocess(tmp_path):
    project = tmp_path / "client-project"
    art = project / "artifacts"
    art.mkdir(parents=True)
    (art / "START-HERE.md").write_text("Status: ⏳ in progress\n", encoding="utf-8")
    (art / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")  # MISSING-HTML
    (art / ".team-session.json").write_text(
        json.dumps({"session": _SID}), encoding="utf-8"
    )
    hook = REPO_ROOT / "scripts" / "staged_hooks" / "dod_stop_gate.py"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["CLAUDE_PROJECT_DIR"] = str(project)
    result = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"session_id": _SID, "cwd": str(project)}),
        capture_output=True,
        text=True,
        cwd=str(project),  # a foreign project: no `scripts` package resolvable
        env=env,
        timeout=120,
    )
    assert result.returncode == 0
    decision = json.loads(result.stdout)
    assert decision["decision"] == "block" and "MISSING-HTML" in decision["reason"]


# --- G5: shared status parser in both hooks -----------------------------------------------


def test_stop_gate_words_only_status_arms(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text("Status: in progress\n", encoding="utf-8")
    (art / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")
    rc, out = _run_gate(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0
    assert json.loads(out)["decision"] == "block"


def test_stop_gate_stray_emoji_in_closed_index_stays_silent(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text(
        "# S\n\n| **Status** | ✅ CLOSED 2026-07-01 |\n\n- history: ⏳ was in progress\n"
        "- delivery-report.md\n",
        encoding="utf-8",
    )
    (art / "START-HERE.html").write_text("<p>x</p>", encoding="utf-8")
    # A closed-pack defect the old (wrongly re-armed) gate would have nagged about:
    (art / "delivery-report.md").write_text("# final\n", encoding="utf-8")
    (art / "delivery-report.html").write_text("<p>x</p>", encoding="utf-8")
    rc, out = _run_gate(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0 and out == ""


def test_stop_gate_gates_closing_status(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": "closing"}), encoding="utf-8"
    )
    rc, out = _run_gate(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"  # invalid-minimal state -> STATE-INVALID findings


def test_anchor_stray_emoji_in_closed_index_stays_silent(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text(
        "# S\n\n| **Status** | ✅ CLOSED 2026-07-01 |\n\n- history: ⏳ was in progress\n",
        encoding="utf-8",
    )
    rc, out = _run_anchor(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0 and out == ""


def test_anchor_fires_during_closing(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": "closing"}), encoding="utf-8"
    )
    rc, out = _run_anchor(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0 and "persona-anchor" in out


# --- G8: registry checked at turn end -----------------------------------------------------


def test_stop_gate_reports_stale_registry(tmp_path, monkeypatch, capsys):
    art = _ws(tmp_path, "active")
    _ws(tmp_path, "other")
    reg = art / "engagements.json"
    stale = json.loads(reg.read_text(encoding="utf-8"))
    stale["engagements"][0]["status"] = "blocked"  # registry no longer matches disk
    reg.write_text(json.dumps(stale), encoding="utf-8")
    capsys.readouterr()  # drop the fixture's own render output
    rc, out = _run_gate(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0
    assert "REGISTRY-STALE" in json.loads(out)["reason"]


# --- R1: the anchor surfaces the on-disk ACTIVE marker ------------------------------------


def test_anchor_names_active_engagement_from_marker(tmp_path, monkeypatch, capsys):
    art = _ws(tmp_path, "audit")
    _ws(tmp_path, "scoping")
    (art / ".active-engagement.json").write_text(
        json.dumps({"slug": "audit", "set": "2026-07-29"}), encoding="utf-8"
    )
    capsys.readouterr()
    rc, out = _run_anchor(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0
    assert "ACTIVE: audit" in out


def test_anchor_asks_for_active_when_no_marker(tmp_path, monkeypatch, capsys):
    _ws(tmp_path, "audit")
    _ws(tmp_path, "scoping")
    capsys.readouterr()
    rc, out = _run_anchor(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0
    assert "set-active" in out


# --- 2026-08-03: full anchor once, short steady-state form thereafter (token-usage audit) -
# a long engagement used to pay the full ~9-line anchor on every single prompt forever. -----


def test_fresh_engagement_gets_the_full_anchor_with_a_log_note_instruction(
    tmp_path, monkeypatch, capsys
):
    _ws(tmp_path, "solo")
    capsys.readouterr()
    rc, out = _run_anchor(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0
    assert "Engagement live - persona/discipline anchor" in out  # the full anchor's own header
    assert "Close = set-status closing" in out  # full-anchor-only content
    assert 'log-note "persona-anchor-seeded"' in out


def test_seeded_engagement_gets_the_short_anchor(tmp_path, monkeypatch, capsys):
    from scripts.engagement_state import main as es_main

    art = _ws(tmp_path, "solo")
    assert es_main(["--dir", str(art / "solo"), "log-note", "persona-anchor-seeded"]) == 0
    capsys.readouterr()
    rc, out = _run_anchor(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0
    assert "short form" in out
    assert "Close = set-status closing" not in out  # the full-only close-procedure detail is gone
    # the rules that actually decay still survive in the short form
    assert "🎩" in out and "AskUserQuestion" in out


# --- R5: the nudge never tells the model to delete close artifacts ------------------------


def test_nudge_says_finish_the_close_never_delete(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "START-HERE.md").write_text("Status: ⏳ in progress\n", encoding="utf-8")
    (art / "engagement-summary-x.txt").write_text("Done.\n", encoding="utf-8")
    rc, out = _run_gate(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    reason = json.loads(out)["reason"]
    assert "SUMMARY-BEFORE-CLOSE" in reason
    assert "remove a premature" not in reason
    assert "NEVER delete" in reason and "set-status closing" in reason


# --- 2026-08-03: cross-turn suppression (token-usage audit) - an unchanging finding must
# nudge once, then stay silent across every later stop/turn/session, not just the same
# stop_hook_active cycle; a NEW/DIFFERENT finding set must re-arm it. ----------------------


def test_unchanged_finding_nudges_once_then_stays_silent_across_calls(
    tmp_path, monkeypatch, capsys
):
    from scripts.engagement_state import main as es_main

    art = _ws(tmp_path, "solo")  # root artifacts/ dir; the workspace itself is art/"solo"
    ws = art / "solo"
    (ws / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")  # MISSING-HTML
    capsys.readouterr()

    rc, out = _run_gate(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0
    decision = json.loads(out)
    assert decision["decision"] == "block"
    reason = decision["reason"]
    assert "dod-nudged:" in reason
    # Extract the exact log-note command the model was told to run, and actually run it -
    # this is the model's real recovery action, not a test-only shortcut.
    import re as _re

    m = _re.search(r'log-note "(dod-nudged:[0-9a-f]+)"', reason)
    assert m, f"no log-note command found in reason: {reason!r}"
    marker = m.group(1)
    assert es_main(["--dir", str(ws), "log-note", marker]) == 0

    # Same finding, same hash, marker now recorded - a later stop (a fresh process, a new
    # turn, even a new session) must go silent instead of repeating the identical nudge.
    capsys.readouterr()
    rc2, out2 = _run_gate(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc2 == 0
    assert out2 == ""


def test_a_new_finding_re_arms_the_nudge_even_with_an_old_marker_present(
    tmp_path, monkeypatch, capsys
):
    from scripts.engagement_state import main as es_main

    art = _ws(tmp_path, "solo")
    ws = art / "solo"
    (ws / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")
    capsys.readouterr()
    rc, out = _run_gate(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    old_reason = json.loads(out)["reason"]
    import re as _re

    old_marker = _re.search(r'log-note "(dod-nudged:[0-9a-f]+)"', old_reason).group(1)
    assert es_main(["--dir", str(ws), "log-note", old_marker]) == 0

    # A second, genuinely NEW defect appears - the finding set (and therefore its hash) is
    # now different, so the gate must nudge again even though an (unrelated, now-stale)
    # marker already sits in the log.
    (ws / "review-pass-2.md").write_text("# more interim\n", encoding="utf-8")
    capsys.readouterr()
    rc2, out2 = _run_gate(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc2 == 0
    decision2 = json.loads(out2)
    assert decision2["decision"] == "block"
    new_marker = _re.search(r'log-note "(dod-nudged:[0-9a-f]+)"', decision2["reason"]).group(1)
    assert new_marker != old_marker  # a different finding set really does re-arm it


def test_suppression_is_per_finding_set_not_a_blanket_silence(tmp_path, monkeypatch, capsys):
    """A marker for finding-set A must not silence an UNRELATED finding-set B that happens
    to arrive first in a fresh project - proves the hash gate isn't just "any marker present
    in the log means stay quiet forever"."""
    from scripts.engagement_state import main as es_main

    art = _ws(tmp_path, "solo")
    ws = art / "solo"
    es_main(["--dir", str(ws), "log-note", "dod-nudged:0000000000000000"])
    (ws / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")
    capsys.readouterr()
    rc, out = _run_gate(monkeypatch, capsys, {"cwd": str(tmp_path)}, tmp_path)
    assert rc == 0
    assert json.loads(out)["decision"] == "block"
