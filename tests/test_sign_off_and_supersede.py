"""Finishing a finished engagement, without reopening it.

2026-08-21. "What if the user wants to reopen?" splits three ways, and only one of them is
really a reopen at all:

  * **sign-off outstanding** - delivery is complete, nobody has put their name to it. Every
    unattended run produces this BY DESIGN (auto mode always closes PARTIAL), so it is now
    the common case, not an edge one. Solved by APPENDING a signature, which leaves the
    as-found record intact.
  * **defect or redo** - new work that supersedes the old pack, linked from the new one so
    the closed record is never edited.
  * **follow-on scope** - an ordinary new engagement; nothing special needed.

The thing all three protect is the property the QA evidence rules already state: a closed
pack must not be retro-edited, because rewriting it to "look passed" destroys the only
reason to keep it.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _run(*args, **kw):
    return subprocess.run(
        [sys.executable, "-m", "scripts.engagement_state", *args],
        cwd=REPO_ROOT, capture_output=True, text=True, **kw
    )


def _pack(tmp_path: Path, slug="demo"):
    """A valid engagement pack.

    Deliberately NOT driven through a full DoD close. Doing that needs a Morgan-signed,
    indexed summary email and a clean gate run, none of which any property here depends on:
    `sign-off` appends a ratification to a VALID pack, and validity is what it inherits. The
    close gate itself is covered by its own tests, and duplicating it here would make these
    tests fail for reasons that have nothing to do with signatures.
    """
    workspace = tmp_path / "artifacts" / slug
    _run("init", "--dir", str(workspace), "--slug", slug, "--title", "Demo", check=True)
    _run("set-team", "--dir", str(workspace), "morgan", check=True)
    return workspace


def _state(workspace):
    return json.loads((workspace / "engagement-state.json").read_text(encoding="utf-8"))


def _sign(workspace, by):
    return _run("sign-off", "--dir", str(workspace), "--by", by)


def test_sign_off_appends_and_changes_nothing_else(tmp_path):
    """THE property. The pack still says PARTIAL afterwards, because it WAS partial at
    close - what changed is that a person has accepted it, and who and when."""
    workspace = _pack(tmp_path)
    before = _state(workspace)
    assert _sign(workspace, "Daniel Edge").returncode == 0
    after = _state(workspace)
    assert after["status"] == before["status"]
    assert after["verdict"] == before["verdict"]
    signed = [r for r in after["ratifications"] if r["text"].startswith("human sign-off")]
    assert len(signed) == 1
    assert signed[0]["status"] == "ratified" and "Daniel Edge" in signed[0]["text"]
    assert signed[0].get("at"), "a signature with no timestamp is not evidence"


def test_sign_off_is_idempotent_and_never_overwrites_the_first_signer(tmp_path):
    """Two people pressing [s] must not silently reattribute the signature."""
    workspace = _pack(tmp_path)
    _sign(workspace, "First Person")
    second = _sign(workspace, "Second Person")
    assert second.returncode == 0
    signed = [r for r in _state(workspace)["ratifications"] if r["text"].startswith("human")]
    assert len(signed) == 1 and "First Person" in signed[0]["text"]


def test_sign_off_refuses_without_a_name(tmp_path):
    """An unattributed signature is worse than none - it looks like accountability."""
    workspace = _pack(tmp_path)
    result = _run("sign-off", "--dir", str(workspace), "--by", "   ")
    assert result.returncode == 2
    assert not _state(workspace).get("ratifications")


def test_the_launcher_reads_back_who_signed(tmp_path):
    mod = _load("virt_team_launcher")
    workspace = _pack(tmp_path)
    assert mod._sign_off_state(tmp_path, "demo") == ""
    _sign(workspace, "Daniel Edge")
    assert mod._sign_off_state(tmp_path, "demo") == "Daniel Edge"


def test_the_launcher_signs_with_the_identity_at_this_keyboard(tmp_path):
    """Recorded by the launcher, never by a session: an agent signing off work - its own or
    anyone's - is the thing the Definition-of-Done gate exists to prevent."""
    mod = _load("virt_team_launcher")
    _pack(tmp_path)
    note = mod._record_sign_off(tmp_path, "demo")
    assert "signed off by" in note, note
    assert mod._sign_off_state(tmp_path, "demo") == mod._signer_name()


def test_redo_starts_new_work_and_never_touches_the_old_pack(tmp_path):
    mod = _load("virt_team_launcher")
    workspace = _pack(tmp_path)
    before = (workspace / "engagement-state.json").read_bytes()
    command = mod._supersede_command(tmp_path, "demo")
    assert "--new" in command and "--supersedes demo" in command
    assert "--review" not in command and "--resume" not in command
    assert (workspace / "engagement-state.json").read_bytes() == before, (
        "building the command must not write to the superseded pack"
    )


def test_the_skill_forbids_reopening_and_places_the_link_on_the_new_pack():
    skill = (REPO_ROOT / ".claude" / "skills" / "engage" / "SKILL.md").read_text(encoding="utf-8")
    assert "--supersedes" in skill
    assert "Never reopen or edit the" in skill and "superseded pack" in skill
    assert "not yours to give" in skill, "the skill must say sign-off is not the agent's"
