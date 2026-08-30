#!/usr/bin/env python3
"""The one way to ask, and the two answers it can give.

These pin the VOCABULARY, not the pixels. Every launcher bug of the last week came from
sixteen screens each inventing their own way to say what happened - None, "", True/False,
APP_FALLBACK, SETUP_CANCEL, JIRA_CANCELLED, MONITOR_CLOSED - and the one that hurt most was
None meaning both "nothing chosen" and "this tier could not draw". So the tests that matter
here are the ones that hold those two apart: a caller must be unable to receive
"unavailable", and a cancel must survive every tier as a cancel.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for _p in (REPO / "vendor", REPO, REPO / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import questions as A  # noqa: E402


def _q(**kw):
    kw.setdefault("kind", A.CHOOSE)
    kw.setdefault("title", "Pick one")
    kw.setdefault("options", [("go", "do the thing", "what it does"), ("stop", "do not", "")])
    return A.Question(**kw)


class _Tty(io.StringIO):
    """A stream that claims to be a terminal, so ask_plain will speak to it."""

    def isatty(self):
        return True


def _plain(typed):
    """Run the plain tier against scripted keystrokes. Returns (answer, what it printed)."""
    err, out_in = _Tty(), _Tty()
    lines = iter(typed)
    real_err, real_in, real_input = (
        sys.stderr,
        sys.stdin,
        __builtins__["input"] if isinstance(__builtins__, dict) else __builtins__.input,
    )
    import builtins

    sys.stderr, sys.stdin = err, out_in
    builtins.input = lambda *a: next(lines)
    try:
        return A.ask_plain(_q()), err.getvalue()
    finally:
        sys.stderr, sys.stdin = real_err, real_in
        builtins.input = real_input


# --------------------------------------------------------------- the vocabulary


def test_there_are_exactly_two_answers():
    """Chosen or left. No third state reaches a caller, which is the entire point: a
    caller that cannot receive "unavailable" cannot mishandle it (the launcher did, four
    separate times, between 2026-08-20 and 2026-08-30)."""
    chosen, left = A.Answer.chosen("go"), A.Answer.left()
    assert chosen.value == "go" and chosen.cancelled is False
    assert left.value is None and left.cancelled is True


def test_an_answer_is_deliberately_not_truthy():
    """`if answer:` is the trap one level up, and it was in this module's first draft.

    On a choose() it would mean "they picked something". On a confirm() the human who
    answered NO produces Answer.chosen(False) - a real choice - which the same expression
    would read as "they didn't answer". One line, two meanings, decided by which question
    it happens to be attached to: the exact overloading the module exists to remove. So it
    raises, loudly and with the fix in the message, rather than quietly being wrong."""
    for answer in (A.Answer.chosen("go"), A.Answer.chosen(False), A.Answer.left()):
        try:
            bool(answer)
        except TypeError as exc:
            assert "answer.cancelled" in str(exc), "the error must say what to write instead"
            continue
        raise AssertionError(f"{answer!r} must not be usable as a boolean")


def test_a_chosen_false_is_a_real_answer():
    """The case that makes truthiness unworkable, asserted on its own so it is not just a
    line in someone else's test: answering "no" is answering."""
    no = A.Answer.chosen(False)
    assert no.cancelled is False and no.value is False


def test_a_question_that_cannot_be_answered_is_refused_at_construction():
    """Late is worse than never: a bad kind or an empty option list must fail where it is
    written, not on the terminal of whoever hit that branch."""
    for bad in ({"kind": "wizard"}, {"options": []}):
        try:
            _q(**bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad} should not be constructible")


def test_the_question_has_nowhere_to_hide_tier_only_text():
    """No intro, no detail, no preamble field. A field only some tiers could draw is how a
    screen comes to carry load-bearing text on one tier and lose it on another - the exact
    divergence this module exists to end, so the field must not exist to be misused."""
    import inspect

    params = inspect.signature(A.Question.__init__).parameters
    for banned in ("intro", "detail", "body", "blurb", "preamble", "note"):
        assert banned not in params, f"Question grew a {banned} field"


# --------------------------------------------------------------- the plain tier


def test_the_plain_tier_asks_and_answers():
    answer, shown = _plain(["2"])
    assert answer.value == "stop" and not answer.cancelled
    assert "Pick one" in shown and "[1] do the thing" in shown
    assert "what it does" in shown, "per-option help must survive to the humblest tier"


def test_leaving_is_a_decision_the_plain_tier_can_express():
    """Three ways out, all one answer. "b" is the footer's, "q" is the muscle memory from
    the full-screen tiers, and bare Enter is what someone types when they want out."""
    for typed in (["b"], ["q"], [""]):
        answer, _ = _plain(typed)
        assert answer.cancelled, f"{typed!r} should leave"
        assert answer.value is None


def test_a_closed_stdin_leaves_rather_than_crashing():
    import builtins

    real, sys_err, sys_in = builtins.input, sys.stderr, sys.stdin
    sys.stderr, sys.stdin = _Tty(), _Tty()

    def boom(*_a):
        raise EOFError

    builtins.input = boom
    try:
        assert A.ask_plain(_q()).cancelled
    finally:
        builtins.input, sys.stderr, sys.stdin = real, sys_err, sys_in


def test_nonsense_re_asks_instead_of_guessing():
    """A typo must never be read as a choice. It re-prompts, and the range is restated -
    on a screen whose whole job is a decision, silently taking option one would be the
    worst possible recovery."""
    answer, shown = _plain(["banana", "9", "0", "1"])
    assert answer.value == "go"
    assert shown.count("1-2 or b, please.") == 3


def test_no_tty_is_nobody_to_ask():
    """Piped, redirected, or under a scheduler: there is no human, so there is no answer -
    and specifically not a default, which would be a decision nobody made."""
    saved_in, saved_err = sys.stdin, sys.stderr
    sys.stdin, sys.stderr = io.StringIO(), io.StringIO()  # isatty() is False on both
    try:
        assert A.ask_plain(_q()).cancelled
    finally:
        sys.stdin, sys.stderr = saved_in, saved_err


def test_the_plain_tier_never_writes_to_stdout():
    """stdout is the launcher's decision channel - `virt-surv go` captures it with $(...)
    and evals the result. A menu printed there is not cosmetic, it is executed."""
    import inspect

    src = inspect.getsource(A.ask_plain)
    assert "file=err" in src
    assert "print(" in src and src.count("file=err") == src.count("print(")


# --------------------------------------------------------------- the dispatcher


def test_the_dispatcher_owns_the_fall_through_so_callers_never_see_unavailable():
    """The load-bearing test. A tier that cannot draw returns None; that must be consumed
    here and never handed on, because every call site that had to handle it got it wrong
    at least once."""
    calls = []

    class Silent:
        @staticmethod
        def render_question(q, mod):
            calls.append("silent")
            return None

    class Works:
        @staticmethod
        def render_question(q, mod):
            calls.append("works")
            return A.Answer.chosen("go")

    saved = A._import
    A._import = lambda name: {"silent": Silent, "works": Works}[name]
    try:
        answer = A.ask(_q(), None, tiers=("silent", "works"))
    finally:
        A._import = saved
    assert calls == ["silent", "works"], "it must try the richer tier first, then fall through"
    assert answer.value == "go"


def test_a_tier_that_raises_is_a_tier_that_cannot_draw():
    """Not a crash in the caller's face. A missing curses, a locked-down console, a Textual
    that will not start on a corporate box - all the same thing from here: try the next
    one, and there is always a next one."""

    class Explodes:
        @staticmethod
        def render_question(q, mod):
            raise RuntimeError("no terminal")

    saved = A._import
    A._import = lambda name: Explodes
    saved_in, saved_err = sys.stdin, sys.stderr
    sys.stdin, sys.stderr = io.StringIO(), io.StringIO()
    try:
        assert A.ask(_q(), None, tiers=("explodes",)).cancelled  # fell all the way to plain
    finally:
        A._import = saved
        sys.stdin, sys.stderr = saved_in, saved_err


def test_a_cancel_from_a_tier_stops_the_fall_through():
    """Because a cancel is an ANSWER. Treating it as "this tier didn't work" would redraw
    the next tier's version of the screen the human just left - which is what happened on
    2026-08-20, and is the single most confusing thing a launcher can do."""
    tried = []

    class Cancels:
        @staticmethod
        def render_question(q, mod):
            tried.append("cancels")
            return A.Answer.left()

    class Never:
        @staticmethod
        def render_question(q, mod):
            tried.append("never")
            return A.Answer.chosen("go")

    saved = A._import
    A._import = lambda name: {"cancels": Cancels, "never": Never}[name]
    try:
        answer = A.ask(_q(), None, tiers=("cancels", "never"))
    finally:
        A._import = saved
    assert tried == ["cancels"], "a cancel is an answer, not a failure to draw"
    assert answer.cancelled


def test_the_no_app_switch_reaches_the_framework_too():
    """VIRT_SURV_NO_APP is how a user with a hostile terminal gets a working launcher, and
    how the test suite stays deterministic. A framework that ignored it would reintroduce
    the full-screen apps through the back door."""

    class Loud:
        @staticmethod
        def render_question(q, mod):
            raise AssertionError("no tier may run under VIRT_SURV_NO_APP")

    saved, saved_env = A._import, os.environ.get("VIRT_SURV_NO_APP")
    saved_in, saved_err = sys.stdin, sys.stderr
    A._import = lambda name: Loud
    os.environ["VIRT_SURV_NO_APP"] = "1"
    sys.stdin, sys.stderr = io.StringIO(), io.StringIO()
    try:
        assert A.ask(_q(), None, tiers=("loud",)).cancelled
    finally:
        A._import = saved
        sys.stdin, sys.stderr = saved_in, saved_err
        if saved_env is None:
            os.environ.pop("VIRT_SURV_NO_APP", None)
        else:
            os.environ["VIRT_SURV_NO_APP"] = saved_env


# --------------------------------------------------------------- the tier bridge


def test_rows_carry_the_help_and_claim_no_writes():
    """The `writes` column warns before a destructive installer key. A framework question
    touches nothing outside the repo, so it must stay empty - a warning on every row is a
    warning on none."""
    rows, back = A.chooser_rows(_q())
    assert [r[1] for r in rows] == ["do the thing", "do not"]
    assert [r[2] for r in rows] == ["what it does", ""]
    assert all(r[3] == "" for r in rows)
    assert back == {"1": "go", "2": "stop"}


def test_selection_keys_never_collide_with_the_way_out():
    """b and q both leave on the full-screen tiers. A key that chooses an option AND
    cancels the screen is the same overloading this whole module exists to remove, one
    keystroke smaller."""
    assert "b" not in A._KEYS and "q" not in A._KEYS
    many = _q(options=[(i, f"option {i}", "") for i in range(len(A._KEYS))])
    _rows, back = A.chooser_rows(many)
    assert len(set(back)) == len(A._KEYS), "keys must be unique"


def test_the_three_way_return_is_collapsed_in_exactly_one_place():
    """from_chooser is where None/""/key becomes the two-answer vocabulary. It is the only
    place that translation happens, which is why no caller has to get it right again."""
    _rows, back = A.chooser_rows(_q())
    assert A.from_chooser(_q(), None, back) is None, "None must stay None so ask() falls through"
    assert A.from_chooser(_q(), "", back).cancelled
    assert A.from_chooser(_q(), "2", back).value == "stop"
    # A key the screen could not have produced is treated as leaving: the safe direction,
    # since doing nothing is always recoverable and acting on a guess is not.
    assert A.from_chooser(_q(), "zzz", back).cancelled


def test_both_full_screen_tiers_translate_identically():
    """The tiers may differ in how they paint and in nothing else. If they diverge here, a
    question means different things depending on what the terminal supports - which is the
    bug class, not a cosmetic difference."""
    import inspect

    import installer_app
    import launcher_textual

    bodies = []
    for mod in (launcher_textual, installer_app):
        src = inspect.getsource(mod.render_question)
        assert "_ask.chooser_rows(question)" in src
        assert "_ask.from_chooser(question, picked, back)" in src
        bodies.append(src.split('"""')[-1])
    assert bodies[0] == bodies[1], "the two tiers' translation must be the same code"


def test_a_missing_host_costs_the_version_line_not_the_screen():
    """Found live on 2026-08-30 and the reason this test exists: ask() has no installer to
    hand, InstallerHost is the first thing the prompt_toolkit chooser builds, and one
    AttributeError inside it made the entire tier look merely unavailable. The caller saw a
    plain numbered prompt on a terminal that could have drawn a screen, with nothing
    anywhere to say why - "broken looks unavailable" again, the same shape that hid the
    launcher's screens for a week."""
    import installer_app

    host = installer_app.InstallerHost(None, None)
    assert host._can_encode("abc") is True, "it must probe the console itself"
    assert host._can_encode("\U0001f4e6") in (True, False), "and never raise"
    for method in (host._morgan_line, host._plugin_version, host._git_branch):
        assert method() == "", "an unanswerable field is empty, not an exception"


def test_the_full_screen_tiers_need_no_installer_to_ask_a_question():
    """The framework is not part of the installer, so the tiers must not require one. This
    is the assertion that keeps ask() usable from the launcher, from a script, or from
    anywhere else - which is the whole reason it is a framework and not a fourth menu."""
    import installer_app
    import launcher_textual

    q = _q()
    # No tty here, so both correctly report "cannot draw" - the point is that they get
    # that far by DECIDING it, rather than by raising on a None host.
    for mod in (launcher_textual, installer_app):
        assert mod.render_question(q, None) is None


def test_more_options_than_keys_refuses_where_it_is_written():
    """zip() would silently drop the tail. A menu that quietly loses its last few options
    is worse than one that will not draw, because nobody can see what is missing - least
    of all the caller who wrote them and believes they are on screen.

    Refused at construction, not at draw time, for the same reason a bad kind is: this is
    a mistake in the code, so it belongs on the author's screen and not on a user's."""
    try:
        _q(options=[(i, f"option {i}", "") for i in range(len(A._KEYS) + 1)])
    except ValueError as exc:
        assert "list screen" in str(exc), "the error must say what to do instead"
        return
    raise AssertionError("an over-long question must not be constructible")


def test_every_key_the_chooser_offers_maps_back_to_exactly_one_option():
    """The full length, since that is where an off-by-one would hide."""
    most = _q(options=[(i, f"option {i}", "") for i in range(len(A._KEYS))])
    rows, back = A.chooser_rows(most)
    assert len(rows) == len(A._KEYS), "no option may be dropped"
    assert sorted(back.values()) == list(range(len(A._KEYS)))
    assert [r[0] for r in rows] == list(A._KEYS)
