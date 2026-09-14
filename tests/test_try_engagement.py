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
