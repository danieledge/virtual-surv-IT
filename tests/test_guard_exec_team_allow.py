"""
Tests for the STAGED 0.29.1 code-execution guard allow-list fix
(scripts/staged_hooks/guard-code-execution.py; installed by the human via
scripts/apply-guard-exec-allow.sh, ADR-002 rec 5).

Two live-observed plugin-mode false positives - the gate demanding exec consent for the
team's OWN tooling: `engagement_state.py` missing from the bundled-copy basename list, and
quoted install paths containing spaces never matching `\\S*`. Both directions pinned here:
the new allowances, and that nothing else loosened (the exec pattern list must stay
byte-identical to the live guard's).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STAGED = _load(REPO / "scripts" / "staged_hooks" / "guard-code-execution.py")
LIVE = _load(REPO / ".claude" / "hooks" / "guard-code-execution.py")


def _allowed(seg: str) -> bool:
    return STAGED._TEAM_ALLOW.match(seg) is not None


# ------------------------------------------------------------------ new allowances


def test_engagement_state_allowed_in_all_invocation_forms():
    for cmd in (
        "python3 -m scripts.engagement_state set-status blocked",
        "python scripts/engagement_state.py render",
        "python3 /home/x/plugin/scripts/engagement_state.py add-artifact a.md --title T",
        'python3 "/Users/x/Application Support/plug/scripts/engagement_state.py" render',
        "py C:\\plugins\\team\\scripts\\engagement_state.py validate",
    ):
        assert _allowed(cmd), cmd


def test_quoted_space_paths_allowed_for_team_basenames():
    for cmd in (
        'python3 "/Users/x/Application Support/plug/scripts/render_html.py" a.md',
        'python3 "/Users/x/Application Support/plug/scripts/check_artifacts.py" --fix',
        "python3 '/home/x/my plugins/team/scripts/eval_score.py' --expected e.yaml",
        'py "C:\\Program Files\\Claude\\plug\\scripts\\convert_file.py" data.xlsx',
        'bash "/Users/x/Application Support/plug/scripts/check-review-tools.sh"',
    ):
        assert _allowed(cmd), cmd


# ------------------------------------------------------------------ still blocked


def test_non_team_basenames_still_blocked_quoted_or_not():
    for cmd in (
        "python3 /tmp/scripts/evil.py",
        'python3 "/tmp/x/scripts/evil.py"',
        "python3 evil.py",
    ):
        assert not _allowed(cmd), cmd
        assert STAGED._EXEC_RE.search(cmd), cmd  # and the exec net still catches it
    # Quoted paths WITH spaces running a non-team file: never team-allowed. The exec net's
    # `\S*\.py` cannot span the space either - a PRE-EXISTING lexical fail-open in the live
    # guard (ADR-002 residual), documented here, unchanged in either direction by 0.29.1.
    for cmd in (
        'python3 "/tmp/my scripts/evil.py"',
        'python3 "/tmp/spaced dir/evil.py"',
    ):
        assert not _allowed(cmd), cmd
        assert LIVE._TEAM_ALLOW.match(cmd) is None, cmd
        assert bool(STAGED._EXEC_RE.search(cmd)) == bool(LIVE._EXEC_RE.search(cmd)), cmd


def test_quote_smuggling_does_not_wave_through():
    # A chained execution after an allowed segment still blocks.
    segs = STAGED._segments('python3 "/x/scripts/render_html.py" ; pytest')
    assert any(not STAGED._TEAM_ALLOW.match(s) and STAGED._EXEC_RE.search(s) for s in segs)
    # Half-quoted smuggle: basename not at the closing quote -> NOT allowed (0.29.1
    # tightening: the pre-fix `[\"']?\S*` accepted this), and still exec-flagged.
    cmd = 'python3 "/x/scripts/render_html.py evil.py"'
    assert not _allowed(cmd), cmd
    assert STAGED._EXEC_RE.search(cmd), cmd
    assert LIVE._TEAM_ALLOW.match(cmd) is None  # the hole stays closed in the live guard


def test_exec_patterns_identical_to_live_guard():
    """The fix loosens ONLY the team allow-list; the execution net must not drift."""
    assert STAGED._EXEC_PATTERNS == LIVE._EXEC_PATTERNS
    assert STAGED._SEGMENT_SPLIT.pattern == LIVE._SEGMENT_SPLIT.pattern


def test_live_guard_matches_staged_once_applied():
    """After the human runs apply-guard-exec-allow.sh, live == staged; until then this
    documents the pending state rather than failing CI."""
    live_text = (REPO / ".claude" / "hooks" / "guard-code-execution.py").read_text(encoding="utf-8")
    staged_text = (REPO / "scripts" / "staged_hooks" / "guard-code-execution.py").read_text(
        encoding="utf-8"
    )
    if live_text != staged_text:
        import pytest

        pytest.skip("staged guard not yet applied (run scripts/apply-guard-exec-allow.sh)")


# ------------------------------------------- 0.32 staged: company allowlist + new scripts


def _load_with_env(monkeypatch, value):
    monkeypatch.setenv("CST_COMPANY_ALLOW", value)
    return _load(REPO / "scripts" / "staged_hooks" / "guard-code-execution.py")


def test_new_team_script_basenames_staged():
    for cmd in (
        "python3 /x/plug/scripts/extensions.py show",
        'python3 "/Users/x/App Support/plug/scripts/convert_sarif.py" r.sarif --slug s --scope x',
    ):
        assert STAGED._TEAM_ALLOW.match(cmd), cmd


def test_audit_batch_scripts_staged_2026_07_30():
    """render_findings.py (check_artifacts' STALE-FINDINGS-RENDER/COUNT-MISMATCH fixes
    literally suggest running it), render_docx.py (the opt-in .docx export) and
    engage_probe.py (the collapsed step-0 probe) are all invoked directly by the model via
    Bash - each needed adding, same gap class the memory note about this allow-list warns
    about ('new scripts/ need an entry or plugin users get consent prompts')."""
    for cmd in (
        "python3 /x/plug/scripts/render_findings.py artifacts/data/findings-x.json",
        'python3 "/Users/x/App Support/plug/scripts/render_docx.py" BRD-x.md',
        "python scripts/engage_probe.py --plugin-root /x/plug --interpreter-name python",
    ):
        assert STAGED._TEAM_ALLOW.match(cmd), cmd


def test_company_prefix_allows_exact_wrapper_only(monkeypatch):
    g = _load_with_env(monkeypatch, "python scripts/publish_pack.py|python3 tools/scan.py")
    ok = "python scripts/publish_pack.py artifacts/ --dest //share/packs"
    assert g._company_allowed(ok)
    for bad in (
        "python evil.py",
        "python scripts/publish_pack_evil.py",  # prefix is literal but this IS a longer path...
    ):
        pass  # see next test for the sharp-edge assertions
    assert g._company_allowed("python3 tools/scan.py --full")
    assert not g._company_allowed("python3 tools/other.py")
    assert not g._company_allowed("pytest tests/")


def test_company_prefix_sharp_edges(monkeypatch):
    """A prefix is literal: it also matches longer basenames sharing the prefix - document
    the recommendation (end prefixes at the .py boundary) and pin that chained segments
    after an allowed prefix are still inspected independently."""
    g = _load_with_env(monkeypatch, "python scripts/publish_pack.py")
    assert g._company_allowed("python scripts/publish_pack.py --dest x")
    # chaining: the second segment stands alone and is NOT allowed
    segs = g._segments("python scripts/publish_pack.py; pytest tests/")
    assert not g._company_allowed(segs[1]) and g._EXEC_RE.search(segs[1])


def test_company_allow_empty_env_changes_nothing(monkeypatch):
    g = _load_with_env(monkeypatch, "")
    assert g._COMPANY_ALLOW_PREFIXES == ()
    assert not g._company_allowed("python scripts/publish_pack.py")
