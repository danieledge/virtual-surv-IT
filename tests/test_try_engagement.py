"""scripts/try_engagement.py (2026-09-13 framework review, step 8.1): one command, under a
minute, a closed synthetic engagement with an evidence room, no model call."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import try_engagement  # noqa: E402


def test_try_closes_a_synthetic_engagement_with_an_evidence_room(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))  # no machine defaults
    lines: list[str] = []
    started = time.monotonic()
    code, room = try_engagement.run(tmp_path / "proj", open_browser=False, log=lines.append)
    elapsed = time.monotonic() - started
    assert code == 0, "\n".join(lines)
    assert room is not None and room.is_file() and room.stat().st_size > 5000
    state = json.loads((room.parent / "engagement-state.json").read_text(encoding="utf-8"))
    assert state.get("status") == "closed"
    assert (room.parent / f"engagement-summary-{try_engagement.SLUG}.txt").is_file()
    assert list(room.parent.glob("REVIEW-*.md")) and list(room.parent.glob("REVIEW-*.html"))
    assert elapsed < 60, f"took {elapsed:.0f} s"
    assert any("no tokens spent" in line for line in lines)


def _fake_sample(root: Path, slug: str = "sample-review") -> Path:
    sample = root / slug
    sample.mkdir(parents=True)
    (sample / "engagement-state.json").write_text('{"status": "closed"}', encoding="utf-8")
    (sample / "START-HERE.md").write_text("# start\n", encoding="utf-8")
    (sample / "EVIDENCE-ROOM-sample-review.html").write_text("<p>room</p>", encoding="utf-8")
    return sample


def test_replay_copies_the_shipped_sample_and_opens_its_room(tmp_path):
    """Step 1.7 / 8.2: the Replay flavour is a copy of the frozen sample, no model call."""
    samples = tmp_path / "examples"
    _fake_sample(samples)
    lines: list[str] = []
    code, room = try_engagement.replay(
        tmp_path / "proj", open_browser=False, log=lines.append, samples=samples
    )
    assert code == 0 and room is not None and room.is_file()
    assert room.parent == tmp_path / "proj" / "VSIT" / "engagements" / "sample-review"
    assert (room.parent / "START-HERE.md").is_file()
    assert any("no tokens spent" in line for line in lines)
    assert any("start here" in line for line in lines)


def test_replay_reports_a_missing_sample_or_room_as_a_packaging_defect(tmp_path):
    lines: list[str] = []
    code, room = try_engagement.replay(
        tmp_path / "p1", open_browser=False, log=lines.append, samples=tmp_path / "none"
    )
    assert code == 1 and room is None
    samples = tmp_path / "examples"
    sample = _fake_sample(samples)
    (sample / "EVIDENCE-ROOM-sample-review.html").unlink()
    code, room = try_engagement.replay(
        tmp_path / "p2", open_browser=False, log=lines.append, samples=samples
    )
    assert code == 1 and room is None
    assert any("packaging defect" in line for line in lines)


def test_the_shipped_sample_is_present_and_replays():
    """The repo ships one sample engagement (step 8.2); the replay must find it as shipped."""
    assert try_engagement.shipped_samples(), "no sample engagement under examples/engagements/"


def test_the_shipped_sample_is_a_complete_closed_engagement(tmp_path):
    """Step 8.2: the frozen run must be what the README says it is - closed, with its state,
    findings packs, summary email, START-HERE page and evidence room - and must pass the same
    mechanical Definition-of-Done gate a live close passes, from a fresh checkout."""
    import re
    import shutil
    import subprocess

    sample = try_engagement.shipped_samples()[0]
    state = json.loads((sample / "engagement-state.json").read_text(encoding="utf-8"))
    assert state.get("status") == "closed" and state.get("verdict")
    assert list(sample.glob("START-HERE*.md")) and list(sample.glob("EVIDENCE-ROOM-*.html"))
    assert list((sample / "data").glob("findings-*.jsonl"))
    assert list(sample.glob("engagement-summary-*.txt"))
    for md in sample.glob("*.md"):
        assert md.with_suffix(".html").is_file(), f"{md.name} has no rendered sibling"
    # No personal identifiers: the requester's account was replaced when the run was frozen.
    text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace") for p in sample.rglob("*") if p.is_file()
    )
    emails = {m for m in re.findall(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", text) if "pytest" not in m}
    assert not emails, emails
    # The DoD gate, from a copy of the whole shipped root (index files included) laid out
    # the way a project holds it. Never on the shipped copy itself: the check may write.
    dest = tmp_path / "VSIT" / "engagements"
    shutil.copytree(try_engagement.SAMPLES, dest)
    proc = subprocess.run(
        [sys.executable, "-m", "scripts.check_artifacts", str(dest)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "DoD artifact gate: OK" in proc.stdout + proc.stderr, proc.stdout + proc.stderr
    readme = (try_engagement.SAMPLES.parent / "README.md").read_text(encoding="utf-8")
    assert f"engagements/{sample.name}/" in readme


def test_replay_flag_is_the_command_line_door(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(
        try_engagement, "replay", lambda project, open_browser=True: (0, tmp_path / "r.html")
    )
    assert try_engagement.main(["--replay", "--no-open", "--dir", str(tmp_path / "p")]) == 0
    assert "--replay" in capsys.readouterr().out
