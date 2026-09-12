"""Suite-wide fixtures.

THE SESSION ID NEVER LEAKS FROM THE DEVELOPER'S OWN SESSION INTO A TEST (2026-09-12). Every
writer of the acting-session stamp keys on CLAUDE_CODE_SESSION_ID, and pytest run from
inside a Claude Code session inherits that variable. A test that runs the engage probe or
a state command against the real checkout then stamped the developer's live session id
into artifacts/.team-session.json - which armed the execution gate against the very
session running the tests, twice in one evening. The stamp is a per-session fact; a test
that needs one sets it with monkeypatch.setenv, explicitly, on a tmp_path project.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _no_inherited_session_id(monkeypatch):
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    # The same leak in miniature: an inherited project dir points every relative-root
    # writer at the developer's checkout instead of the test's tmp_path.
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
