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
import sys
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


def _warm_cache(project: Path, interp: str = sys.executable) -> None:
    """Default to sys.executable, not a plausible-looking fake path - _read_cache now
    validates via shutil.which() (Fable review W2 fix), so a fixture using a fake path
    would silently exercise the garbage-cache path instead of the warm-cache path."""
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
    for prompt in (
        "/engagement-report",
        "/engage-lighter",
        "engage without a slash",
        "/compliance-surveillance-team:engagement-report",
        "/compliance-surveillance-team:engage-lighter",
    ):
        rc, out = _run(monkeypatch, capsys, {"user_input": prompt}, tmp_path)
        assert rc == 0 and out == "", prompt


def test_engage_family_commands_all_match(tmp_path, monkeypatch, capsys):
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path)
    for prompt in ("/engage", "/engage-light", "/map-codebase --refresh", "/engage do the thing"):
        rc, out = _run(monkeypatch, capsys, {"user_input": prompt}, tmp_path)
        assert rc == 0, prompt
        assert "<engage-probe-result>" in out, prompt


def test_namespaced_plugin_commands_match_too(tmp_path, monkeypatch, capsys):
    """2026-08-16 live finding: a plugin install namespaces every command, so real
    plugin-mode users type (and virt-surv go pre-seeds) the namespaced spelling - the
    bare-only pattern meant the prefetch NEVER fired for them, and every open silently
    paid the in-session fallback probe. Unnoticed because the repo-as-project dev loop
    and Friday's pre-namespacing launcher both used the bare spelling that did match."""
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path)
    for prompt in (
        "/compliance-surveillance-team:engage --new",
        "/compliance-surveillance-team:engage-light",
        "/compliance-surveillance-team:map-codebase --refresh",
        "/renamed-fork:engage",
    ):
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
    _warm_cache(tmp_path, interp=sys.executable)
    rc, out = _run(monkeypatch, capsys, {"user_input": "/engage"}, tmp_path)
    assert rc == 0
    assert f"INTERPRETER={sys.executable}" in out
    assert "PLUGIN_ROOT=" in out  # repo-as-project -> empty value, but the key is present
    assert "do NOT run the Bash bootstrap heredoc" in out


def test_garbage_cache_declines_silently(tmp_path, monkeypatch, capsys):
    """Fable review W2: a corrupted-but-non-empty cache used to be injected verbatim as
    authoritative - probe-contract.md tells the model never to re-probe the printed word,
    so a bad cache would poison the whole open. A single-token value that doesn't resolve
    to anything executable must decline exactly like a cold/missing cache."""
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path, interp="not-a-real-interpreter-xyz")
    rc, out = _run(monkeypatch, capsys, {"user_input": "/engage"}, tmp_path)
    assert rc == 0 and out == ""


def test_multiline_cache_declines_silently(tmp_path, monkeypatch, capsys):
    """A cache file is meant to hold one token/path - multi-line content (corruption, or a
    concurrent writer interleaving) must not be treated as a valid single interpreter."""
    _repo_as_project(tmp_path)
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / ".guard-interpreter").write_text(
        f"{sys.executable}\nsome garbage second line\n", encoding="utf-8"
    )
    rc, out = _run(monkeypatch, capsys, {"user_input": "/engage"}, tmp_path)
    assert rc == 0 and out == ""


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


def test_injected_block_carries_resume_menu(tmp_path, monkeypatch, capsys):
    """RESUME_MENU is the same computation as `engagement_state list --menu`
    (SKILL.md step 0b) - even with no engagements at all, the field must appear with a
    valid empty-menu shape (open=[] etc.), proving the mechanism ran, not just that it
    silently declined."""
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path)
    rc, out = _run(monkeypatch, capsys, {"user_input": "/engage"}, tmp_path)
    assert rc == 0
    assert "RESUME_MENU" in out
    # the JSON blob itself: pull it out and confirm it's the real resume_menu() shape
    start = out.index("RESUME_MENU")
    menu_text = out[start:].split("</engage-probe-result>")[0]
    brace = menu_text.index("{")
    menu = json.loads(menu_text[brace:])
    assert menu == {"open": [], "shown": [], "more": 0, "archived": 0, "default": None}


def test_resume_menu_failure_does_not_drop_the_rest_of_the_block(tmp_path, monkeypatch, capsys):
    """RESUME_MENU and the probe report fail open INDEPENDENTLY - a broken
    engagement_state.resume_menu() must not cost the INTERPRETER=/PLUGIN_ROOT= part of the
    open too, since those come from a wholly separate function call."""
    _repo_as_project(tmp_path)
    _warm_cache(tmp_path)
    mod = _load()

    def _boom(*a, **k):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(mod, "_resume_menu_json", _boom)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"user_input": "/engage"})))
    rc = mod.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "<engage-probe-result>" in out and f"INTERPRETER={sys.executable}" in out
    assert "RESUME_MENU" not in out


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
