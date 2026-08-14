"""The /engage step-0 probe prefetch (scripts/staged_hooks/engage_probe_prefetch.py),
human-installed via scripts/apply-engage-probe-prefetch.sh into UserPromptSubmit.

Pre-runs the SAME probe engage-open.md's step 0 documents (find_plugin_root.find_plugin_root
+ engage_probe.build_report - no logic duplicated) from a hook that fires before the model's
turn, so a steady-state /engage/-light/map-codebase open can skip the Bash heredoc entirely.
Dormancy-exact: near-zero cost on every other prompt; declines silently (no output) on a cold
interpreter cache or any internal error - the live Bash-heredoc probe stays the untouched
fallback. See scripts/staged_hooks/engage_probe_prefetch.py's own docstring for the full
rationale.
"""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "staged_engage_probe_prefetch",
        REPO_ROOT / "scripts" / "staged_hooks" / "engage_probe_prefetch.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(monkeypatch, capsys, payload: dict, project: Path) -> tuple[int, str]:
    mod = _load()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    rc = mod.main()
    return rc, capsys.readouterr().out


def _repo_as_project(project: Path) -> None:
    """Minimal fixture: docs/team-operating-guide.md makes find_plugin_root short-circuit
    to PLUGIN_ROOT="" (repo-as-project) without ever touching the real machine's actual
    ~/.claude/plugins/ - this dev machine genuinely has the plugin installed, so leaving
    that path live would make the test's outcome depend on whatever happens to be on disk."""
    (project / "docs").mkdir(parents=True, exist_ok=True)
    (project / "docs" / "team-operating-guide.md").write_text("# ops guide\n", encoding="utf-8")


def _warm_cache(project: Path, interp: str = "/usr/bin/python3") -> None:
    (project / ".claude").mkdir(parents=True, exist_ok=True)
    (project / ".claude" / ".guard-interpreter").write_text(interp, encoding="utf-8")


def test_non_engage_prompt_is_zero_cost(tmp_path, monkeypatch, capsys):
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path)
    rc, out = _run(monkeypatch, capsys, {"user_input": "fix the login bug"}, tmp_path)
    assert rc == 0 and out == ""


def test_lookalike_commands_do_not_false_positive(tmp_path, monkeypatch, capsys):
    """/engagement-report and /engage-lighter must not match - only the exact three commands
    that actually read engage-open.md (grep-confirmed: engage, engage-light, map-codebase)."""
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path)
    for prompt in ("/engagement-report", "/engage-lighter", "engage without a slash"):
        rc, out = _run(monkeypatch, capsys, {"user_input": prompt}, tmp_path)
        assert rc == 0 and out == "", prompt


def test_engage_family_commands_all_match(tmp_path, monkeypatch, capsys):
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path)
    for prompt in ("/engage", "/engage-light", "/map-codebase --refresh", "/engage do the thing"):
        rc, out = _run(monkeypatch, capsys, {"user_input": prompt}, tmp_path)
        assert rc == 0, prompt
        assert "<engage-probe-result>" in out, prompt


def test_cold_cache_declines_silently(tmp_path, monkeypatch, capsys):
    """No .guard-interpreter yet = first-ever run in this project - the live heredoc's own
    interpreter-detection handles this; the hook must not reimplement it."""
    _repo_as_project(tmp_path)
    rc, out = _run(monkeypatch, capsys, {"user_input": "/engage"}, tmp_path)
    assert rc == 0 and out == ""


def test_malformed_stdin_fails_open(tmp_path, monkeypatch, capsys):
    mod = _load()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    rc = mod.main()
    assert rc == 0 and capsys.readouterr().out == ""


def test_injected_block_carries_interpreter_and_plugin_root(tmp_path, monkeypatch, capsys):
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path, interp="/opt/python3.12/bin/python3")
    rc, out = _run(monkeypatch, capsys, {"user_input": "/engage"}, tmp_path)
    assert rc == 0
    assert "INTERPRETER=/opt/python3.12/bin/python3" in out
    assert "PLUGIN_ROOT=" in out  # repo-as-project -> empty value, but the key is present
    assert "do NOT run the Bash bootstrap heredoc" in out


def test_build_failure_fails_open(tmp_path, monkeypatch, capsys):
    """A broken build_report() (any internal exception) must degrade to no output, never
    a crash or a half-written block - same fail-open contract as persona_anchor.py and
    session_resume_brief.py."""
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path)
    mod = _load()

    def _boom(*a, **k):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(mod, "_build_block", _boom)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"user_input": "/engage"})))
    # main() itself only calls _build_block inside no try/except at the call site, so a
    # raise there must be caught by the __main__ guard, not crash the hook process.
    try:
        rc = mod.main()
    except RuntimeError:
        rc = None  # fails the assertion below explicitly rather than letting pytest error out
    assert rc == 0, "main() must catch a _build_block failure itself, not rely on __main__"


def test_uses_cwd_key_when_project_dir_env_absent(tmp_path, monkeypatch, capsys):
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    mod = _load()
    monkeypatch.setattr(
        "sys.stdin", io.StringIO(json.dumps({"user_input": "/engage", "cwd": str(tmp_path)}))
    )
    rc = mod.main()
    assert rc == 0
    assert "<engage-probe-result>" in capsys.readouterr().out
