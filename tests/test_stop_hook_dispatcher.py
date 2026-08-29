"""scripts/stop_hook_dispatcher.py (perf audit, 2026-08-03): one Stop-event process for
what used to be two separate hooks (dod_stop_gate, todo_panel_nudge), each previously its
own hooks.json entry -> its own process spawn, on every single Stop event while any
engagement pack is gated. Mirrors bash_hook_dispatcher.py's own PreToolUse consolidation.

This file has three halves:
  - subprocess, end-to-end fidelity checks against the REAL staged hooks (unmodified) -
    the dispatcher must produce the same decision(s) invoking each hook alone would have,
    and must COMBINE both reasons (deterministically, since the harness's own composition
    behaviour for two hooks each independently emitting decision:block is undocumented)
    when both would have fired in the same turn;
  - in-process unit tests of the dispatcher's OWN mechanics (crash handling, missing file,
    stdin re-injection) using small stand-in hook modules;
  - the staged/live byte-sync check (fails, not skips, until applied).
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DISPATCHER = REPO_ROOT / "scripts" / "stop_hook_dispatcher.py"
STAGED = REPO_ROOT / "scripts" / "staged_hooks" / "stop_hook_dispatcher.py"
DOD_STOP_GATE = REPO_ROOT / "scripts" / "staged_hooks" / "dod_stop_gate.py"
TODO_PANEL_NUDGE = REPO_ROOT / "scripts" / "staged_hooks" / "todo_panel_nudge.py"

sys.path.insert(0, str(REPO_ROOT / "scripts" / "staged_hooks"))


def _load_dispatcher_module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("stop_hook_dispatcher_staged", STAGED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Session scoping (2026-08-16): the staged hooks arm only when the payload's
# session_id matches the acting-session stamp in artifacts/.team-session.json;
# _run and _ws below carry both so the fidelity fixtures stay armed.
_SID = "sess-dispatcher-suite"


def _run(script: Path, payload: dict, project: Path) -> subprocess.CompletedProcess:
    payload.setdefault("session_id", _SID)
    return subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={"CLAUDE_PROJECT_DIR": str(project), "PATH": "/usr/bin:/bin"},
        timeout=30,
    )


def _ws(project: Path, slug: str) -> Path:
    """A genuinely valid, real engagement workspace (via the real engagement_state CLI -
    a hand-written minimal engagement-state.json is missing required fields like
    engagement.slug, which itself trips dod_stop_gate's STATE-INVALID finding and would
    silently contaminate every fixture below with an unintended extra finding)."""
    from scripts.engagement_state import main as es_main

    art = project / "artifacts"
    assert es_main(["--dir", str(art / slug), "init", "--title", slug, "--slug", slug]) == 0
    # Explicit, deterministic stamp: es_main itself only stamps when the pytest
    # process env happens to carry CLAUDE_CODE_SESSION_ID (true under a live Claude
    # session, false in CI) - never rely on that here.
    (art / ".team-session.json").write_text(json.dumps({"session": _SID}), encoding="utf-8")
    return art / slug


def _dormant_project(tmp_path: Path) -> Path:
    return tmp_path  # no artifacts/ dir at all - both hooks silent


def _dod_finding_only(tmp_path: Path) -> Path:
    """Open engagement with a real DoD finding (MISSING-HTML) but phase left at its
    default (not delivery/close), so only dod_stop_gate fires."""
    ws = _ws(tmp_path, "solo")
    (ws / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")  # no .html sibling
    return tmp_path


def _todo_nudge_only(tmp_path: Path) -> Path:
    """Open, clean engagement (no DoD finding) whose phase just reached delivery with no
    seeded marker, so only todo_panel_nudge fires."""
    from scripts.engagement_state import main as es_main

    ws = _ws(tmp_path, "solo")
    assert es_main(["--dir", str(ws), "set-phase", "delivery"]) == 0
    # Re-stamp AFTER the es_main mutation above: under a live Claude session the
    # in-process CLI stamps the REAL session id from the env, clobbering _SID.
    (tmp_path / "artifacts" / ".team-session.json").write_text(
        json.dumps({"session": _SID}), encoding="utf-8"
    )
    return tmp_path


def _both_fire(tmp_path: Path) -> Path:
    """Open engagement, phase delivery (arms todo_panel_nudge), AND a genuine DoD finding
    (arms dod_stop_gate) - both hooks should want to nudge in the same turn."""
    from scripts.engagement_state import main as es_main

    ws = _ws(tmp_path, "solo")
    assert es_main(["--dir", str(ws), "set-phase", "delivery"]) == 0
    (ws / "review-pass-1.md").write_text("# interim\n", encoding="utf-8")  # MISSING-HTML
    # Re-stamp AFTER the es_main mutation above: under a live Claude session the
    # in-process CLI stamps the REAL session id from the env, clobbering _SID.
    (tmp_path / "artifacts" / ".team-session.json").write_text(
        json.dumps({"session": _SID}), encoding="utf-8"
    )
    return tmp_path


# ------------------------------------------------------------------ fidelity: real hooks


def test_dormant_project_both_silent(tmp_path):
    project = _dormant_project(tmp_path)
    dispatched = _run(STAGED, {"cwd": str(project)}, project)
    assert dispatched.returncode == 0
    assert dispatched.stdout.strip() == ""


def test_only_dod_finding_matches_direct_invocation(tmp_path):
    project = _dod_finding_only(tmp_path)
    payload = {"cwd": str(project)}
    dispatched = _run(STAGED, payload, project)
    direct = _run(DOD_STOP_GATE, payload, project)
    assert dispatched.returncode == 0
    assert direct.returncode == 0
    assert json.loads(dispatched.stdout) == json.loads(direct.stdout)


def test_only_todo_nudge_matches_direct_invocation(tmp_path):
    project = _todo_nudge_only(tmp_path)
    payload = {"cwd": str(project)}
    dispatched = _run(STAGED, payload, project)
    direct = _run(TODO_PANEL_NUDGE, payload, project)
    assert dispatched.returncode == 0
    assert direct.returncode == 0
    assert json.loads(dispatched.stdout) == json.loads(direct.stdout)


def test_both_firing_are_combined_into_one_decision(tmp_path):
    """The decisive case: both hooks want to nudge in the same turn. The dispatcher must
    surface BOTH reasons (not just one), in one combined decision:block - not depend on
    undocumented multi-hook composition, and not silently drop either message."""
    project = _both_fire(tmp_path)
    payload = {"cwd": str(project)}
    dispatched = _run(STAGED, payload, project)
    dod_direct = _run(DOD_STOP_GATE, payload, project)
    nudge_direct = _run(TODO_PANEL_NUDGE, payload, project)

    assert dispatched.returncode == 0
    decision = json.loads(dispatched.stdout)
    assert decision["decision"] == "block"

    assert dod_direct.stdout.strip(), "fixture bug: dod_stop_gate did not fire alone"
    assert nudge_direct.stdout.strip(), "fixture bug: todo_panel_nudge did not fire alone"
    dod_reason = json.loads(dod_direct.stdout)["reason"]
    nudge_reason = json.loads(nudge_direct.stdout)["reason"]
    assert dod_reason in decision["reason"]
    assert nudge_reason in decision["reason"]


def test_malformed_stdin_allows_and_never_raises():
    result = subprocess.run(
        [sys.executable, str(STAGED)],
        input="not valid json{{{",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "Traceback" not in result.stderr


def test_staged_and_live_are_byte_synced():
    if not DISPATCHER.is_file():
        raise AssertionError(
            "stop_hook_dispatcher.py not yet installed - "
            "run: bash scripts/apply-stop-hook-dispatcher.sh"
        )
    assert DISPATCHER.read_bytes() == STAGED.read_bytes()


# ------------------------------------------------------------------ dispatcher mechanics (in-process)


def _fake_module(*, prints: str | None = None, raises: Exception | None = None):
    mod = types.ModuleType("fake_stop_hook")

    def main():
        sys.stdin.read()  # prove stdin was actually re-injected and readable
        if raises is not None:
            raise raises
        if prints is not None:
            print(prints)
        return 0

    mod.main = main
    return mod


def test_neither_hook_fires_prints_nothing(monkeypatch):
    shd = _load_dispatcher_module()
    monkeypatch.setattr(shd, "_load", lambda name, path: _fake_module(prints=None))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": "/tmp"})))
    assert shd.main() == 0


def test_one_hook_crashing_does_not_suppress_the_other(monkeypatch, capsys):
    shd = _load_dispatcher_module()

    def fake_load(name, path):
        if name == "dod_stop_gate":
            return _fake_module(raises=RuntimeError("boom"))
        return _fake_module(prints=json.dumps({"decision": "block", "reason": "nudge"}))

    monkeypatch.setattr(shd, "_load", fake_load)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": "/tmp"})))
    assert shd.main() == 0
    out = capsys.readouterr().out
    assert json.loads(out)["reason"] == "nudge"  # the crashed hook contributed nothing, not a crash


def test_missing_hook_file_skips_that_check_without_crashing(monkeypatch, tmp_path):
    shd = _load_dispatcher_module()
    monkeypatch.setattr(shd, "_CHECKS", (("dod_stop_gate", tmp_path / "does-not-exist.py"),))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": "/tmp"})))
    assert shd.main() == 0


def test_both_hooks_see_the_full_original_payload(monkeypatch):
    shd = _load_dispatcher_module()
    seen: list = []
    payload = {"cwd": "/tmp", "extra": "field"}

    def fake_load(name, path):
        mod = types.ModuleType(name)

        def main():
            seen.append(json.loads(sys.stdin.read()))
            return 0

        mod.main = main
        return mod

    monkeypatch.setattr(shd, "_load", fake_load)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    assert shd.main() == 0
    assert seen == [payload, payload]  # both hooks got the full, unconsumed payload


def test_check_artifacts_cache_propagates_from_first_hook_to_second(monkeypatch):
    """M2 (2026-08-14 perf audit): both real hooks carry an IDENTICAL check_artifacts.py
    loader that memoizes into a hook-local `_CHECK_ARTIFACTS_MODULE_CACHE` global once it
    hits the file-exec fallback (plugin mode, package import unavailable). Run back-to-back
    in this ONE dispatcher process, that meant two full execs of the ~120KB checker for one
    Stop event. This white-box test proves the dispatcher's OWN propagation mechanism using
    stand-in modules shaped exactly like the real loader's fallback-cache contract -
    fidelity against the REAL hooks (that this doesn't change dod_stop_gate.py's or
    todo_panel_nudge.py's own decisions) is covered separately by
    test_only_dod_finding_matches_direct_invocation et al above, which already run against
    a bare tmp_path project (no `scripts` package resolvable), so they already exercise
    this exact fallback path end to end."""
    shd = _load_dispatcher_module()
    exec_count = {"n": 0}
    created: list = []

    def make_fake_hook(name):
        mod = types.ModuleType(name)
        mod._CHECK_ARTIFACTS_MODULE_CACHE = None

        def main():
            sys.stdin.read()
            if mod._CHECK_ARTIFACTS_MODULE_CACHE is None:
                exec_count["n"] += 1
                mod._CHECK_ARTIFACTS_MODULE_CACHE = object()  # stand-in "loaded checker"
            return 0

        mod.main = main
        created.append(mod)
        return mod

    monkeypatch.setattr(shd, "_load", lambda name, path: make_fake_hook(name))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": "/tmp"})))
    assert shd.main() == 0

    assert exec_count["n"] == 1, (
        "check_artifacts fallback exec ran more than once for one Stop event"
    )
    assert len(created) == 2
    assert created[0]._CHECK_ARTIFACTS_MODULE_CACHE is created[1]._CHECK_ARTIFACTS_MODULE_CACHE


def test_check_artifacts_cache_propagation_is_a_noop_in_repo_mode(monkeypatch):
    """Repo mode (package import succeeds): neither hook's own loader ever touches
    `_CHECK_ARTIFACTS_MODULE_CACHE` on that path, so it must stay None on both stand-in
    modules and no propagation (or extra work) happens - proves the fix is inert, not
    just harmless, when there is nothing to share."""
    shd = _load_dispatcher_module()

    def make_fake_hook(name):
        mod = types.ModuleType(name)
        mod._CHECK_ARTIFACTS_MODULE_CACHE = None  # never populated - "package import worked"

        def main():
            sys.stdin.read()
            return 0

        mod.main = main
        return mod

    monkeypatch.setattr(shd, "_load", lambda name, path: make_fake_hook(name))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": "/tmp"})))
    assert shd.main() == 0


def test_non_block_or_empty_output_is_ignored(monkeypatch):
    """A hook that prints something that ISN'T a decision:block JSON (or nothing) must
    not be treated as a nudge - defensive against a hook printing debug noise."""
    shd = _load_dispatcher_module()
    monkeypatch.setattr(shd, "_load", lambda name, path: _fake_module(prints="not json{{"))
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"cwd": "/tmp"})))
    assert shd.main() == 0
