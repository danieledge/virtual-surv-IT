"""The document-input redirect (scripts/staged_hooks/document_input_redirect.py,
human-installed via scripts/apply-document-redirect.sh).

Live failure (2026-07-29): handed a PDF mid-engagement, the team read the binary bytes via
PowerShell and hand-parsed, unaware of the vendored converter. The hook mechanically
redirects Read/Bash on binary documents to `scripts.convert_file` - but ONLY while an
engagement is live: a dormant session behaves as standard Claude Code (the dormancy
invariant), and the hook fails open on any error (quality redirect, not a safety guard).
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "staged_doc_redirect",
        REPO_ROOT / "scripts" / "staged_hooks" / "document_input_redirect.py",
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


def _live_engagement(project: Path, status: str = "in_progress") -> None:
    art = project / "artifacts"
    art.mkdir(parents=True, exist_ok=True)
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": status}), encoding="utf-8"
    )


def _read(path: str) -> dict:
    return {"tool_name": "Read", "tool_input": {"file_path": path}}


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# --- dormancy: a session that never engaged the team is untouched -------------------------


def test_dormant_session_reads_pdf_untouched(tmp_path, monkeypatch, capsys):
    rc, err = _run(monkeypatch, capsys, _read(str(tmp_path / "spec.pdf")), tmp_path)
    assert rc == 0 and err == ""


def test_closed_engagement_is_dormant(tmp_path, monkeypatch, capsys):
    _live_engagement(tmp_path, "closed")
    rc, _ = _run(monkeypatch, capsys, _read("spec.pdf"), tmp_path)
    assert rc == 0


# --- live engagement: binary documents route to the converter -----------------------------


def test_read_pdf_blocked_with_converter_pointer(tmp_path, monkeypatch, capsys):
    _live_engagement(tmp_path)
    rc, err = _run(monkeypatch, capsys, _read("requirements/spec.pdf"), tmp_path)
    assert rc == 2
    assert "convert_file" in err and "--layout" in err


def test_read_xlsx_blocked(tmp_path, monkeypatch, capsys):
    _live_engagement(tmp_path)
    rc, err = _run(monkeypatch, capsys, _read("data/extract.xlsx"), tmp_path)
    assert rc == 2 and "convert_file" in err


def test_powershell_hand_parse_blocked(tmp_path, monkeypatch, capsys):
    _live_engagement(tmp_path)
    rc, err = _run(
        monkeypatch,
        capsys,
        _bash("powershell -c \"[IO.File]::ReadAllBytes('spec.pdf')\""),
        tmp_path,
    )
    assert rc == 2 and "convert_file" in err


def test_cat_of_pdf_blocked(tmp_path, monkeypatch, capsys):
    _live_engagement(tmp_path)
    rc, _ = _run(monkeypatch, capsys, _bash("cat requirements/spec.pdf | head -50"), tmp_path)
    assert rc == 2


def test_workspace_engagement_arms_too(tmp_path, monkeypatch, capsys):
    art = tmp_path / "artifacts" / "audit"
    art.mkdir(parents=True)
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": "closing"}), encoding="utf-8"
    )
    rc, _ = _run(monkeypatch, capsys, _read("spec.pdf"), tmp_path)
    assert rc == 2


# --- what must keep working ---------------------------------------------------------------


def test_convert_file_invocation_passes(tmp_path, monkeypatch, capsys):
    _live_engagement(tmp_path)
    rc, err = _run(
        monkeypatch,
        capsys,
        _bash("python3 -m scripts.convert_file requirements/spec.pdf --layout"),
        tmp_path,
    )
    assert rc == 0 and err == ""


def test_text_files_never_touched(tmp_path, monkeypatch, capsys):
    _live_engagement(tmp_path)
    assert _run(monkeypatch, capsys, _read("notes.md"), tmp_path)[0] == 0
    assert _run(monkeypatch, capsys, _read("feed.csv"), tmp_path)[0] == 0
    assert _run(monkeypatch, capsys, _bash("cat notes.md"), tmp_path)[0] == 0


def test_mentioning_a_pdf_without_reading_it_passes(tmp_path, monkeypatch, capsys):
    _live_engagement(tmp_path)
    rc, _ = _run(monkeypatch, capsys, _bash("ls -la requirements/spec.pdf"), tmp_path)
    assert rc == 0


def test_bad_stdin_fails_open(monkeypatch, capsys):
    mod = _load()
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert mod.main() == 0
