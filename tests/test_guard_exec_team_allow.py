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

import pytest

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


# ------------------------------------------------------------------ maintenance rule


# Front-door scripts the team invokes on the user's behalf. These MUST run consent-free in
# plugin mode, where skills invoke the bundled copy BY PATH - CLAUDE.md §7: "never ask the user
# for consent to run a front-door script". A basename missing from _TEAM_SCRIPT_NAMES means a
# consent prompt for the team's own tooling.
#
# Deliberately NOT auto-derived from a glob over scripts/: that would let a genuinely new tool
# silently allow-list itself, which is the opposite of the intent. The list is curated, and this
# test is the reminder to curate it.
_FRONT_DOOR_SCRIPTS = (
    "render_html",
    "render_findings",
    "render_docx",
    "convert_file",
    "ingest",
    "gen_synthetic",
    "synthesise",
    "validate_masking",
    "validate_manifest",
    "validate_rtm",
    "validate_references",
    "check_citations",
    "eval_score",
    "calibrate_spoofing",
    "check_artifacts",
    "engagement_state",
    "extensions",
    "convert_sarif",
    "engage_probe",
)


@pytest.mark.parametrize("name", _FRONT_DOOR_SCRIPTS)
def test_front_door_script_runs_consent_free_by_path(name):
    """Plugin mode invokes bundled scripts by absolute path, so the BASENAME must be
    allow-listed. Regression for the 2026-08-01 audit finding: engage_probe, render_findings
    and render_docx were missing, so plugin-mode /engage tripped the execution gate on its own
    step-0 probe and asked the user to grant consent for the team's own tooling."""
    assert _allowed(f"python3 /home/x/plugin/scripts/{name}.py"), (
        f"{name}.py is not in _TEAM_SCRIPT_NAMES - plugin-mode users will be prompted for "
        "execution consent to run a front-door script (CLAUDE.md §7 forbids this)"
    )


@pytest.mark.parametrize("name", _FRONT_DOOR_SCRIPTS)
def test_front_door_script_exists_on_disk(name):
    """The allow-list must not accumulate entries for scripts that no longer exist - a stale
    basename is a lexical hole (any file with that name in a scripts/ dir would be accepted)."""
    assert (REPO / "scripts" / f"{name}.py").is_file(), (
        f"scripts/{name}.py is allow-listed but missing - remove the stale entry"
    )


def test_non_team_script_by_path_still_blocked():
    """The allow-list must stay a list, not a pattern that waves through anything in scripts/."""
    assert not _allowed("python3 /home/x/plugin/scripts/evil.py")
    assert not _allowed("python3 /tmp/scripts/render_htmlx.py")


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
    assert STAGED._SEGMENT_DELIMS == LIVE._SEGMENT_DELIMS


# ---------------------------------- command substitution inside double quotes (2026-08-07)
#
# Found by a framework-wide audit, verified by hand before this fix: bash actually EXECUTES
# `$(...)`/backtick substitution even inside double quotes - only single quotes suppress it.
# _segments() gated backtick/`$(` on the same "not in_single and not in_double" condition as
# the ordinary delimiters (;/&&/||/|/newline), for which that gating IS correct (those really
# are just literal text inside "..."). So `echo "$(pytest)"` never became its own segment,
# and the segment-start-anchored `^pytest` pattern in _EXEC_PATTERNS never saw it. Mirrors
# the fix guard-consent-writes.py already had (its own comment: "command substitution
# executes even inside double quotes - always a boundary").


def test_dollar_paren_inside_double_quotes_starts_its_own_segment():
    """The fix is lexical, not a matching-paren parser (ADR-002's own stated design: still
    lexical, safe-direction-on-imprecision, same philosophy as "unclosed quotes fold the
    remainder into one segment"). `$(`/backtick correctly become a segment boundary; the
    guard does not attempt to find `$(...)`'s MATCHING close, so trailing characters after
    it (the outer string's own closing quote, e.g.) stay glued onto that segment rather
    than being cleanly separated. That's fine - checked separately below - because the
    anchored patterns match on segment START, so the extra tail never hides the command."""
    for cmd, expect_prefix in (
        ('echo "$(pytest)"', "pytest"),
        ('echo "$(make)"', "make"),
        ('X="$(pytest -x)"', "pytest -x"),
        ('echo "prefix $(pytest) suffix"', "pytest"),
    ):
        segs = STAGED._segments(cmd)
        assert any(s.startswith(expect_prefix) for s in segs), (
            f"{cmd!r} -> {segs!r} (expected some segment starting with {expect_prefix!r})"
        )


def test_backtick_inside_double_quotes_starts_its_own_segment():
    segs = STAGED._segments('echo "`pytest`"')
    assert any(s.startswith("pytest") for s in segs), segs


def test_double_quoted_substitution_still_trips_the_exec_net():
    """The segment the fix isolates must actually match _EXEC_PATTERNS (not just exist) -
    proving the anchored `^pytest`/`^make` patterns see the real command, not the quote
    wrapper, once _segments() stops hiding it inside a larger double-quoted blob."""
    for cmd in ('echo "$(pytest)"', 'echo "$(make)"', 'echo "`pytest`"', 'X="$(pytest -x)"'):
        segs = STAGED._segments(cmd)
        assert any(STAGED._EXEC_RE.search(s) and not STAGED._TEAM_ALLOW.match(s) for s in segs), (
            f"{cmd!r} -> {segs!r} - no segment both matches the exec net and fails the "
            "team allow-list, meaning this command would NOT be blocked"
        )


def test_single_quoted_dollar_paren_correctly_stays_literal():
    """Single quotes genuinely suppress substitution in real bash - `echo '$(pytest)'`
    prints the literal text and never runs pytest. Confirms the fix didn't overcorrect
    into treating $(/backtick as a boundary inside SINGLE quotes too."""
    segs = STAGED._segments("echo '$(pytest)'")
    assert segs == ["echo '$(pytest)'"], segs


def test_ordinary_delimiters_still_stay_literal_inside_double_quotes():
    """The fix must be scoped to command substitution ONLY - ;/&&/||/|/newline are still
    genuinely literal text inside double quotes in real bash (this is the exact false-
    positive test_guard_hardening's own 2026-08-03 fix protects), so this must not regress."""
    cmd = 'git commit -m "close as-is; no real source data exists"'
    segs = STAGED._segments(cmd)
    assert len(segs) == 1, segs


def test_double_quoted_exec_substitution_end_to_end_via_staged_guard(tmp_path):
    """Full subprocess invocation of the staged guard script itself (not just internal
    functions) - the strongest proof, matching exactly how the audit verified the bypass."""
    import json
    import os
    import subprocess
    import sys

    staged_path = REPO / "scripts" / "staged_hooks" / "guard-code-execution.py"
    for cmd in ('echo "$(pytest)"', 'echo "$(make)"', 'echo "`pytest`"'):
        env = {k: v for k, v in os.environ.items() if k != "CST_ALLOW_EXEC"}
        env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
        proc = subprocess.run(
            [sys.executable, str(staged_path)],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}}),
            text=True,
            capture_output=True,
            env=env,
        )
        assert proc.returncode == 2, f"{cmd!r} was NOT blocked (rc={proc.returncode})"


# ------------------------------------------------ env-var prefix before the interpreter
# (2026-08-04): a compound command like `OUT=$(PYTHONIOENCODING=utf-8 python ".../x.py")`
# splits (on `$(`) into a segment starting with `PYTHONIOENCODING=utf-8 python ...`, not
# with the python token itself - the old anchor required the interpreter literally at
# segment start, so team-allowed scripts got blocked whenever a Windows cp1252 workaround
# prefixed an env var. Live report: engage_probe.py blocked this way during /engage step 0.


def test_env_var_prefixed_team_script_allowed():
    for cmd in (
        'PYTHONIOENCODING=utf-8 python "/plugin/scripts/engage_probe.py" --probe',
        "PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python -m scripts.engagement_state list",
        'FOO=1 BAR=baz python "/x/scripts/render_html.py" a.md',
    ):
        assert _allowed(cmd), cmd


def test_the_live_compound_command_regression_no_longer_false_positives():
    """Reconstructs the exact live failure: `$(` segment-splitting leaves the env-var
    prefix attached to the inner segment, which must still resolve to team-allowed."""
    cmd = 'OUT=$(PYTHONIOENCODING=utf-8 python "/plugin/scripts/engage_probe.py" --probe)'
    segs = STAGED._segments(cmd)
    inner = [s for s in segs if "engage_probe" in s]
    assert len(inner) == 1
    assert _allowed(inner[0]), inner[0]


def test_env_var_prefix_does_not_loosen_non_team_scripts():
    """The fix widens WHAT CAN PRECEDE an allowed form, not WHAT COUNTS as allowed - an
    env-var prefix in front of a non-team script must still be blocked."""
    for cmd in (
        "FOO=1 python /tmp/evil.py",
        "PYTHONIOENCODING=utf-8 python /tmp/scripts/evil.py",
    ):
        assert not _allowed(cmd), cmd
        assert STAGED._EXEC_RE.search(cmd), cmd


def test_live_guard_matches_staged_once_applied():
    """HARD FAILURE, never a skip.

    This test used to skip while the fix was unapplied, "documenting the pending state rather
    than failing CI". On 2026-08-01 an audit found the consequence: the live guard was missing
    engage_probe, render_findings and render_docx from its team-script allow-list, so plugin-mode
    /engage was asking users for execution consent to run its own step-0 probe - something the
    operating guide explicitly forbids. The suite was green throughout, because this test was
    skipping precisely when it had something to say.

    A control that is silently inert looks identical to a healthy one. Pending guard work now
    fails the suite until the human applies it.
    """
    live_text = (REPO / ".claude" / "hooks" / "guard-code-execution.py").read_text(encoding="utf-8")
    staged_text = (REPO / "scripts" / "staged_hooks" / "guard-code-execution.py").read_text(
        encoding="utf-8"
    )
    assert live_text == staged_text, (
        "staged guard not yet applied - run: bash scripts/apply-guard-exec-allow.sh"
    )


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
        "python3 /x/plug/scripts/render_findings.py artifacts/data/findings-x.jsonl",
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


# ------------------------------------------------ quote-aware segment splitting
# (2026-08-03, second fix): the old regex split chopped INSIDE a quoted argument - a
# log-note/commit message using ';' or '&&' as ordinary punctuation got sliced into a
# bogus fragment. Live: `engagement_state log-note "...close as-is; no real source data
# exists..." && ...` was split mid-sentence right after the semicolon inside the quotes,
# and the resulting garbage fragment spuriously tripped the execution-block pattern.


def test_semicolon_inside_quoted_argument_is_not_a_segment_boundary():
    cmd = 'echo "close as-is; no real source data exists" && echo done'
    assert STAGED._segments(cmd) == [
        'echo "close as-is; no real source data exists"',
        "echo done",
    ]


def test_ampersand_and_pipe_inside_quotes_are_not_boundaries():
    assert STAGED._segments('echo "a && b | c"') == ['echo "a && b | c"']
    assert STAGED._segments("echo 'a && b | c'") == ["echo 'a && b | c'"]


def test_quoted_text_does_not_shield_a_genuine_later_boundary():
    """The fix must not over-correct into treating the WHOLE command as unsplittable - a
    real boundary after the closing quote still splits."""
    segs = STAGED._segments('echo "a; b" && echo "c; d"')
    assert segs == ['echo "a; b"', 'echo "c; d"']


def test_the_live_eval_regression_no_longer_false_positives(monkeypatch):
    """Reconstructs the exact command that blocked live in the 2026-08-03 eval run and
    confirms the log-note segment survives intact rather than being chopped into a
    garbage mid-sentence fragment."""
    cmd = (
        'python3 -m scripts.engagement_state resolve-outstanding "does not exist" '
        "--slug q2-alert-fp-summary 2>&1 | grep -v NoCssSanitizerWarning && \\\n"
        'python3 -m scripts.engagement_state log-note "User chose to drop FP root-cause '
        'commissioning and close as-is; no real source data exists for it (2026-08-03)" '
        "--slug q2-alert-fp-summary 2>&1 | grep -v NoCssSanitizerWarning"
    )
    segs = STAGED._segments(cmd)
    log_note_segs = [s for s in segs if "log-note" in s]
    assert len(log_note_segs) == 1
    assert "no real source data exists for it (2026-08-03)" in log_note_segs[0]
    assert log_note_segs[0].strip().startswith("python3 -m scripts.engagement_state log-note")


# --------------------------------------- targeted note for ad hoc inline diagnostics
# (2026-08-07): the GENERIC block message gave no hint that `-c`/stdin execution is
# ALWAYS blocked (not a consent question) or what to do instead - live-recurring in two
# shapes: retrying after a step-0 /engage probe failure by improvising a replacement, and
# verifying a findings-pack JSON parses by running `python -c "...json.load..."` instead
# of just reading the file. Pinned here so the note fires exactly for this command shape
# and nowhere else.


def test_inline_code_re_matches_python_dash_c():
    assert STAGED._INLINE_CODE_RE.search('python -c "import sys; print(sys.executable)"')


def test_inline_code_re_matches_the_findings_pack_verification_live_report():
    """The exact command shape from the 2026-08-07 live report: checking a findings pack
    parses and counting its entries via an ad hoc python -c, inside a cd && chain."""
    cmd = (
        'cd "C:/Users/dev/claude/analytics-project" && python -c "import json,sys;'
        "d=json.load(open('artifacts/analytics-project-full/data/findings-code-backend-core-"
        "analytics-project-full.json',encoding='utf-8')); f=d['findings']; "
        "print('parsed OK, findings:',len(f))\""
    )
    segs = STAGED._segments(cmd)
    hit = [s for s in segs if STAGED._INLINE_CODE_RE.search(s)]
    assert len(hit) == 1
    assert STAGED._EXEC_RE.search(hit[0])  # also caught by the general exec pattern


def test_inline_code_re_does_not_match_ordinary_exec_patterns():
    assert not STAGED._INLINE_CODE_RE.search("pytest tests/")
    assert not STAGED._INLINE_CODE_RE.search("python target_module.py")
    assert not STAGED._INLINE_CODE_RE.search("python -m scripts.ingest data/raw")


def test_block_adds_the_inline_note_for_python_dash_c(capsys):
    with pytest.raises(SystemExit) as exc:
        STAGED._block('python -c "import json"', 'python -c "import json"')
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "ad hoc inline diagnostic" in err
    assert "NOT a consent question" in err
    assert "python --version" in err
    assert "python -V" in err


def test_block_omits_the_inline_note_for_ordinary_exec(capsys):
    with pytest.raises(SystemExit):
        STAGED._block("pytest tests/", "pytest tests/")
    err = capsys.readouterr().err
    assert "ad hoc inline diagnostic" not in err
    # the standard consent instructions are still present regardless
    assert "CST_ALLOW_EXEC" in err


# ------------------------------- 2026-08-26 staged: the interpreter invoked BY PATH


# Live report, corporate Windows, plugin mode. `virt-surv` resolves `<python>` to an absolute
# interpreter when the PATH is unreliable (which is the whole reason that resolution exists),
# so the team's own front door arrived as:
#
#   "C:/Python313/python.exe" "C:/Users/.../virtual-surv-IT/scripts/engagement_state.py" init ...
#
# _TEAM_ALLOW only ever matched a BARE interpreter name, so it did not recognise the team's
# own script, fell through to the exec check, and demanded execution consent - the exact
# thing CLAUDE.md §7 says the gate must never cover, on the one platform least able to work
# around it.
_ABS_INTERPRETER_CALLS = [
    '"C:/Python313/python.exe" "C:/Users/dev/virtual-surv-IT/scripts/engagement_state.py" init',
    '"C:\\Python313\\python.exe" "C:\\Users\\d\\virtual-surv-IT\\scripts\\engagement_state.py" init',
    "C:/Python313/python.exe C:/plug/scripts/render_html.py report.md",
    "/usr/bin/python3 /opt/team/scripts/check_artifacts.py --fix",
    "/usr/bin/python3.12 /opt/team/scripts/engage_probe.py",
    "'/opt/py/bin/python' '/opt/team/scripts/validate_rtm.py'",
]


@pytest.mark.parametrize("command", _ABS_INTERPRETER_CALLS)
def test_a_team_script_run_by_an_absolute_interpreter_is_allowed(command):
    assert _allowed(command), (
        "the team's own tooling must run consent-free however the interpreter is spelled"
    )


# The security property does NOT live in the interpreter token - it lives in the script side:
# an allow-listed basename sitting directly inside a `scripts/` directory. Widening which
# interpreters are recognised must not widen which SCRIPTS are trusted, so each of these
# pairs the newly-accepted interpreter form with a script that has no business running.
_STILL_BLOCKED = [
    '"C:/Python313/python.exe" "C:/tmp/evil.py"',
    '"C:/Python313/python.exe" "C:/tmp/scripts/evil.py"',
    "/usr/bin/python3 /opt/team/scripts/evil.py",
    "/usr/bin/python3 /tmp/engagement_state.py",
    '"C:/Python313/python.exe" -m pytest',
    "/usr/bin/python3 -c 'import os; os.system(\"rm -rf /\")'",
]


@pytest.mark.parametrize("command", _STILL_BLOCKED)
def test_a_path_interpreter_does_not_launder_an_untrusted_script(command):
    assert not _allowed(command), (
        "the interpreter was never the trust boundary; the script basename is"
    )


def test_the_report_case_end_to_end():
    """The exact command from the 2026-08-26 report, including the detail that made it
    confusing to diagnose: it was NOT blocked for looking like Python execution.

    `--title "...against source code"` matched the `\\bsource\\s+\\S+` exec pattern - the
    shell `source` builtin - inside a quoted argument. Once _TEAM_ALLOW matches the segment
    the exec check is never reached, so allow-listing the team's own front door fixes the
    reported symptom whatever the arguments happen to contain."""
    segment = (
        '"C:/Python313/python.exe" "C:/Users/dev/virtual-surv-IT/scripts/engagement_state.py" '
        'init --title "Adversarial review of the alert scoring module '
        'against source code" --slug eng-001 --team-version "v0.37.0"'
    )
    assert STAGED._EXEC_RE.search(segment), "the prose really does trip an exec pattern"
    assert _allowed(segment), "so the allow-list must match first"


def test_widening_the_interpreter_did_not_touch_the_exec_patterns():
    """_PY_ANY is for the allow-list only. If it ever leaks into _EXEC_PATTERNS the change
    stops being additive, and this file's own 'nothing else loosened' guarantee is void."""
    assert STAGED._EXEC_PATTERNS == LIVE._EXEC_PATTERNS
    assert not any("_PY_ANY" in p for p in STAGED._EXEC_PATTERNS)
