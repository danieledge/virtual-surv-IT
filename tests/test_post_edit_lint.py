"""Post-edit lint feedback (scripts/staged_hooks/post_edit_lint.py, human-installed via
scripts/apply-post-edit-lint.sh): a builder's Python edit is checked the moment it lands
(py_compile always, ruff opportunistically), with findings fed back over the PostToolUse
feedback channel. Live engagements only; dormant sessions untouched; fails open."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "staged_post_edit_lint", REPO_ROOT / "scripts" / "staged_hooks" / "post_edit_lint.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(monkeypatch, capsys, payload: dict, project: Path) -> tuple[int, str]:
    mod = _load()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = mod.main()
    return rc, capsys.readouterr().err


def _live(project: Path) -> None:
    art = project / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": "in_progress"}), encoding="utf-8"
    )


def _edit(path: Path) -> dict:
    return {"tool_name": "Write", "tool_input": {"file_path": str(path)}}


def test_dormant_session_untouched(tmp_path, monkeypatch, capsys):
    bad = tmp_path / "broken.py"
    bad.write_text("def x(:\n", encoding="utf-8")
    rc, err = _run(monkeypatch, capsys, _edit(bad), tmp_path)
    assert rc == 0 and err == ""


def test_syntax_error_fed_back_during_engagement(tmp_path, monkeypatch, capsys):
    _live(tmp_path)
    bad = tmp_path / "rule.py"
    bad.write_text("def detect(:\n    pass\n", encoding="utf-8")
    rc, err = _run(monkeypatch, capsys, _edit(bad), tmp_path)
    assert rc == 2
    assert "post-edit lint" in err and "syntax" in err


def test_clean_file_stays_silent(tmp_path, monkeypatch, capsys):
    _live(tmp_path)
    ok = tmp_path / "rule.py"
    ok.write_text("def detect(rows):\n    return [r for r in rows if r]\n", encoding="utf-8")
    rc, err = _run(monkeypatch, capsys, _edit(ok), tmp_path)
    assert rc == 0 and err == ""


def test_non_python_files_ignored(tmp_path, monkeypatch, capsys):
    _live(tmp_path)
    doc = tmp_path / "notes.md"
    doc.write_text("# notes\n", encoding="utf-8")
    assert _run(monkeypatch, capsys, _edit(doc), tmp_path)[0] == 0


def test_missing_file_and_bad_stdin_fail_open(tmp_path, monkeypatch, capsys):
    _live(tmp_path)
    assert _run(monkeypatch, capsys, _edit(tmp_path / "ghost.py"), tmp_path)[0] == 0
    mod = _load()
    monkeypatch.setattr("sys.stdin", io.StringIO("{broken"))
    assert mod.main() == 0
