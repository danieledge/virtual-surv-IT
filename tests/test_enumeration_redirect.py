"""Map-first enforcement (scripts/enumeration_redirect.py, 2026-08-17).

A live review session priced its target with a bare `find <project> -type f` that
dumped 217 paths (caches, artifacts/, .claude/ internals included) into the
transcript. The map-first rules were prose; this Bash rule makes them mechanical -
in ENGAGED sessions only, with advisory polarity (unknowable state stays silent)."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "enumeration_redirect.py"


def _run(command: str, project: Path, session: str = "sess-1") -> subprocess.CompletedProcess:
    payload = {
        "tool_name": "Bash",
        "session_id": session,
        "tool_input": {"command": command},
    }
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env={"CLAUDE_PROJECT_DIR": str(project), "PATH": "/usr/bin:/bin"},
    )


def _engaged(project: Path, session: str = "sess-1") -> Path:
    (project / "artifacts").mkdir(parents=True, exist_ok=True)
    (project / "artifacts" / ".team-session.json").write_text(
        json.dumps({"session": session}), encoding="utf-8"
    )
    return project


def test_bare_find_type_f_blocked_when_engaged(tmp_path):
    r = _run('find "C:/Users/x/proj" -type f | grep -v pycache', _engaged(tmp_path))
    assert r.returncode == 2
    assert "codebase-map" in r.stderr
    assert "repo_skeleton" in r.stderr


def test_recursive_ls_and_powershell_forms_blocked(tmp_path):
    _engaged(tmp_path)
    for cmd in ("ls -laR src/", "Get-ChildItem C:/proj -Recurse", "rg --files"):
        r = _run(cmd, tmp_path)
        assert r.returncode == 2, cmd


def test_count_only_and_targeted_forms_pass(tmp_path):
    _engaged(tmp_path)
    for cmd in (
        "find . -type f | wc -l",
        'find . -name "*.py" -type f',
        "git ls-files | wc -l",
        "python -m scripts.repo_skeleton . --budget 4000",
        "find . -maxdepth 1 -type f",
        "ls -la",
    ):
        r = _run(cmd, tmp_path)
        assert r.returncode == 0, f"{cmd}: {r.stderr}"


def test_dormant_session_never_hit(tmp_path):
    # no stamp at all - plain Claude Code work is untouched
    r = _run("find / -type f", tmp_path)
    assert r.returncode == 0
    # stamp from a DIFFERENT session - still silent (advisory polarity)
    _engaged(tmp_path, session="other-session")
    r = _run("find / -type f", tmp_path, session="sess-1")
    assert r.returncode == 0


def test_missing_session_id_stays_silent(tmp_path):
    """Advisory polarity inversion vs the exec gate: unknowable = silent, never armed."""
    _engaged(tmp_path)
    payload = {"tool_name": "Bash", "tool_input": {"command": "find . -type f"}}
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=30,
        env={"CLAUDE_PROJECT_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert r.returncode == 0


def test_dispatcher_wires_the_rule():
    """The staged dispatcher must carry the enumeration_redirect entry for Bash -
    without it the module is inert (the 2026-08-01 'silently inert control' lesson)."""
    staged = (REPO_ROOT / "scripts" / "staged_hooks" / "bash_hook_dispatcher.py").read_text(
        encoding="utf-8"
    )
    assert "enumeration_redirect" in staged


def test_module_importable_and_fail_open_shape():
    spec = importlib.util.spec_from_file_location("enum_redirect", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._ENUM_RE.search("find /x -type f")
    assert not mod._ENUM_RE.search("grep -rn pattern src/")
