"""UTF-8 encoding pin in the guard launcher (scripts/staged_hooks/run-guard.sh, human-
installed via scripts/apply-guard-utf8-encoding.sh).

Regression under test (live corporate report 2026-07-31): locked_menu_guard.py kept
blocking a correctly-formed Fix-cycle answer ("Fix → re-review loop") with a false
"review-menu drift" on a Windows box, even though the option text matched review-menu.md
exactly. Root cause: the launcher exec'd the resolved Python interpreter without pinning
its text encoding, so stdin/stdout/stderr fell back to the platform default (the Windows
console codepage, e.g. cp1252) - which doesn't raise on the arrow's multi-byte UTF-8
bytes, it silently mis-decodes them into different-but-valid characters. The fix exports
PYTHONIOENCODING=utf-8 and PYTHONUTF8=1 before every exec path.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "staged_hooks" / "run-guard.sh"
GUARD = REPO_ROOT / "scripts" / "staged_hooks" / "locked_menu_guard.py"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sh") is None, reason="needs a POSIX shell"
)


def _env(project_dir: Path, **extra):
    import os

    env = {"CLAUDE_PROJECT_DIR": str(project_dir), "PATH": os.environ["PATH"]}
    env.update(extra)
    return env


def _run(project_dir: Path, target: Path, payload: str, **extra_env):
    return subprocess.run(
        ["sh", str(LAUNCHER), str(target)],
        input=payload,
        capture_output=True,
        text=True,
        env=_env(project_dir, **extra_env),
        timeout=30,
    )


def test_launcher_forces_utf8_regardless_of_locale(tmp_path):
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    helper = tmp_path / "print_encoding.py"
    helper.write_text(
        "import sys; print(sys.stdin.encoding); print(sys.stdout.encoding)\n",
        encoding="utf-8",
    )
    proc = _run(proj, helper, "", LC_ALL="C", LANG="C")
    assert proc.returncode == 0
    lines = [line.strip().lower() for line in proc.stdout.splitlines() if line.strip()]
    assert lines == ["utf-8", "utf-8"]


def _review_menu_payload() -> str:
    """The exact three-question construction from review-menu.md, including the locked
    Fix-cycle option text with its literal U+2192 arrow."""
    questions = [
        {
            "header": "Depth",
            "multiSelect": False,
            "options": [{"label": label} for label in ("Quick", "Deep", "Audit", "None")],
        },
        {
            "header": "Performance",
            "multiSelect": False,
            "options": [{"label": label} for label in ("Yes", "No")],
        },
        {
            "header": "Fix-cycle",
            "multiSelect": False,
            "options": [
                {"label": "Report only"},
                {"label": "Apply fixes"},
                {"label": "Fix → re-review loop"},
            ],
        },
        {
            "header": "Origin",
            "multiSelect": False,
            "options": [
                {"label": "AI-assisted / vibe-coded"},
                {"label": "Mixed"},
                {"label": "Hand-written"},
            ],
        },
    ]
    return json.dumps({"tool_name": "AskUserQuestion", "tool_input": {"questions": questions}})


def test_correct_review_menu_is_not_blocked_under_a_non_utf8_locale(tmp_path):
    """End-to-end repro of the corporate report: under a C/POSIX locale (the launcher's
    stand-in for "the OS default text encoding isn't UTF-8"), a byte-for-byte-correct
    review-menu answer must still pass - not trip the drift guard on the arrow label."""
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    proc = _run(proj, GUARD, _review_menu_payload(), LC_ALL="C", LANG="C")
    assert proc.returncode == 0, proc.stderr


def test_actual_drift_is_still_caught_under_the_same_locale(tmp_path):
    """The UTF-8 pin must not accidentally widen the guard into a no-op: a genuine
    reordering of the locked headers still blocks."""
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    payload = json.loads(_review_menu_payload())
    payload["tool_input"]["questions"][0]["header"] = "Depth"
    payload["tool_input"]["questions"][1]["header"] = "Fix-cycle"
    payload["tool_input"]["questions"][2]["header"] = "Performance"
    proc = _run(proj, GUARD, json.dumps(payload), LC_ALL="C", LANG="C")
    assert proc.returncode == 2
    assert "review-menu drift" in proc.stderr
