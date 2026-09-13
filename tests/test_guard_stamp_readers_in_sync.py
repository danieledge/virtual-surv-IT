"""The session-stamp readers are copied into four hooks on purpose - "a hook must not depend
on the scripts package being importable" (scripts/enumeration_redirect.py) - and the 2026-09-12
audit (H-22) found one copy had silently fallen behind the others for two weeks. Step 3.7 of
the 2026-09-13 plan proposed a shared module; that would break the standalone rule, so this
test pins the copies to each other BEHAVIOURALLY instead: every copy must answer the same
stamp files identically, while the callers may differ in polarity (a safety gate fails toward
ARMED on a missing session id, an advisory redirect stays silent), which is checked in place."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
_FILES = {
    "guard-code-execution.py": REPO / ".claude" / "hooks" / "guard-code-execution.py",
    "guard-consent-writes.py": REPO / ".claude" / "hooks" / "guard-consent-writes.py",
    "enumeration_redirect.py": REPO / "scripts" / "enumeration_redirect.py",
    "exploration_redirect.py": REPO / "scripts" / "exploration_redirect.py",
}


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_STAMPS = {
    "legacy": {"session": "legacy-1"},
    "current": {"session_id": "cur-3", "sessions": [{"id": "cur-1"}, {"id": "cur-2"}, "cur-3"]},
    "mixed": {"session": "old", "session_id": "new", "sessions": [{"id": ""}, 7, {"id": "x"}]},
    "not-a-dict": ["a", "b"],
    "garbage": "{not json",
}


@pytest.mark.parametrize("label", sorted(_STAMPS))
def test_every_copy_reads_a_stamp_file_identically(tmp_path, label):
    stamp = tmp_path / ".team-session.json"
    content = _STAMPS[label]
    stamp.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    answers = {name: _load(path)._stamped_session_ids(str(stamp)) for name, path in _FILES.items()}
    assert len(set(answers.values())) == 1, f"the copies disagree on a {label} stamp: {answers}"
    missing = {name: _load(path)._stamped_session_ids(str(tmp_path / "absent.json")) for name, path in _FILES.items()}
    assert set(missing.values()) == {()}


def test_every_copy_looks_for_the_stamp_in_the_same_places(tmp_path):
    """Both layouts, newest first: VSIT/engagements/ then artifacts/ (audit H-22 found one
    copy still reading only the legacy path). The consent guard inlines the same pair."""
    expected = [
        str(tmp_path / "VSIT" / "engagements" / ".team-session.json"),
        str(tmp_path / "artifacts" / ".team-session.json"),
    ]
    for name in ("guard-code-execution.py", "enumeration_redirect.py", "exploration_redirect.py"):
        candidates = [str(Path(p)) for p in _load(_FILES[name])._stamp_candidates(str(tmp_path))]
        assert candidates == expected, f"{name}: {candidates}"
    consent = _FILES["guard-consent-writes.py"].read_text(encoding="utf-8")
    assert 'os.path.join(root, "VSIT", "engagements", _STAMP_NAME)' in consent
    assert 'os.path.join(root, "artifacts", _STAMP_NAME)' in consent


def test_the_polarity_difference_is_deliberate_and_stated():
    """Safety gates return True on a missing session id; advisory redirects return False."""
    for label in ("guard-code-execution.py", "guard-consent-writes.py"):
        src = _FILES[label].read_text(encoding="utf-8")
        assert "if not sid:\n        return True" in src, f"{label}: a safety gate fails toward ARMED"
    for label in ("enumeration_redirect.py", "exploration_redirect.py"):
        src = _FILES[label].read_text(encoding="utf-8")
        assert "if not sid:\n        return False" in src, f"{label}: an advisory hook stays silent"
