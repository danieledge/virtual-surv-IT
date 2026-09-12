"""Tests for scripts/tier_probe.py (T-2, 2026-09-12 test-quality audit).

tier_probe.py is a manual, human-run diagnostic ("why did (or didn't) the Textual tier
draw?", per its own docstring) - it is not dead code: it is deliberately reached only by a
developer typing `python scripts/tier_probe.py` in the terminal they are asking about, never
by any command, skill, or another script (confirmed by grep - its only other repo mentions
are the exec-consent allow-list entry that lets it run without asking, which is exactly why
that allow-list entry needs its OWN test too - see test_guard_exec_team_allow.py). These pin
its core reporting logic and its own opt-out/verdict behaviour so that manual-only status
does not also mean untested.
"""

from __future__ import annotations

import sys

import scripts.tier_probe as tp


# ------------------------------------------------------------------ _line


def test_line_formats_label_value_with_padding(capsys):
    tp._line("some.label", "OK")
    out = capsys.readouterr().out
    assert "some.label" in out
    assert "OK" in out
    assert out.rstrip("\n").endswith("OK")


def test_line_appends_a_note_when_given(capsys):
    tp._line("some.label", "OK", "<- a note")
    out = capsys.readouterr().out
    assert "<- a note" in out


def test_line_omits_the_note_tail_when_not_given(capsys):
    tp._line("some.label", "OK")
    out = capsys.readouterr().out
    assert "<-" not in out


# ------------------------------------------------------------------ main(): opt-outs section


def test_opt_out_env_vars_are_flagged_when_set(monkeypatch, capsys):
    monkeypatch.setenv("VIRT_SURV_NO_APP", "1")
    monkeypatch.delenv("VIRT_SURV_NO_TEXTUAL", raising=False)
    monkeypatch.delenv("VIRT_SURV_FORCE_PTK", raising=False)
    assert tp.main() == 0
    out = capsys.readouterr().out
    assert "VIRT_SURV_NO_APP" in out
    lines = {line.split()[0]: line for line in out.splitlines() if "VIRT_SURV" in line}
    assert "<- this alone disables a tier" in lines["VIRT_SURV_NO_APP"]


def test_opt_out_env_vars_show_unset_and_no_note_when_absent(monkeypatch, capsys):
    for name in ("VIRT_SURV_NO_APP", "VIRT_SURV_NO_TEXTUAL", "VIRT_SURV_FORCE_PTK"):
        monkeypatch.delenv(name, raising=False)
    assert tp.main() == 0
    out = capsys.readouterr().out
    unset_lines = [line for line in out.splitlines() if "VIRT_SURV" in line]
    assert unset_lines, "expected the three opt-out vars to be reported"
    for line in unset_lines:
        assert "(unset)" in line
        assert "<- this alone disables a tier" not in line


# ------------------------------------------------------------------ main(): streams section


def test_main_reports_isatty_for_every_stream(capsys):
    assert tp.main() == 0
    out = capsys.readouterr().out
    for name in ("stdin", "stdout", "stderr"):
        assert f"sys.{name}.isatty()" in out


def test_a_stream_that_cannot_answer_isatty_is_reported_not_raised(monkeypatch, capsys):
    class _Explodes:
        def isatty(self):
            raise RuntimeError("no tty concept here")

    monkeypatch.setattr(sys, "stdin", _Explodes())
    assert tp.main() == 0
    out = capsys.readouterr().out
    assert "sys.stdin.isatty()" in out
    assert "error:" in out


# ------------------------------------------------------------------ main(): imports section


def test_main_reports_ok_for_a_real_importable_module(capsys):
    assert tp.main() == 0
    out = capsys.readouterr().out
    # launcher_tiers ships in scripts/, so it is always importable in this repo's own tests.
    assert "launcher_tiers" in out
    line = next(line for line in out.splitlines() if line.strip().startswith("launcher_tiers"))
    assert "OK" in line


def test_main_reports_fails_for_a_module_that_cannot_import(monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "rich":
            raise ImportError("simulated: not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    assert tp.main() == 0
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if line.strip().startswith("rich"))
    assert "FAILS" in line
    assert "ImportError" in line


# ------------------------------------------------------------------ main(): the verdict


def test_the_verdict_reports_available_true_or_false(capsys):
    assert tp.main() == 0
    out = capsys.readouterr().out
    assert "launcher_textual.available()" in out


def test_the_verdict_reports_a_failure_without_raising(monkeypatch, capsys):
    import types

    fake = types.ModuleType("launcher_textual")

    def _boom():
        raise RuntimeError("simulated probe failure")

    fake.available = _boom
    monkeypatch.setitem(sys.modules, "launcher_textual", fake)
    assert tp.main() == 0
    out = capsys.readouterr().out
    line = next(
        line
        for line in out.splitlines()
        if "launcher_textual.available()" in line and "FAILS" in line
    )
    assert "RuntimeError" in line


# ------------------------------------------------------------------ main(): never raises overall


def test_main_never_raises_and_always_returns_zero(monkeypatch, capsys):
    """The whole point of the probe is to report a broken environment, not join it: even
    with every opt-out set and streams that error, main() must complete and return 0."""
    monkeypatch.setenv("VIRT_SURV_NO_APP", "1")
    monkeypatch.setenv("VIRT_SURV_NO_TEXTUAL", "1")
    monkeypatch.setenv("VIRT_SURV_FORCE_PTK", "1")
    assert tp.main() == 0
    capsys.readouterr()
