#!/usr/bin/env python3
"""One way to ask a person something, and one vocabulary for what they answered.

WHY THIS EXISTS, and it is not consistency of appearance.

Sixteen screens each invented their own way of saying what happened: None, "", True/False,
APP_FALLBACK, SETUP_CANCEL, JIRA_CANCELLED, BROWSE_CANCELLED, AUTO_CANCELLED,
MONITOR_CLOSED, (ref, True), ("supersede", slug). Every launcher bug of the last week came
out of that, and none of them came out of drawing:

  * Esc launched a session, because SETUP_SKIP was used where cancel was meant and skip
    means "launch without configuring" (2026-08-29).
  * Cancelling a screen drew the same screen again underneath it, because "" meant cancel
    in one screen and "could not draw" in another (2026-08-20).
  * Blank-Enter backed out of the alias manager instead of taking the default, because ""
    from a prompt and "" from a screen are identical strings meaning opposite things
    (2026-08-30).
  * Whole screens were silently unreachable, because None means both "nothing chosen" and
    "this tier could not draw" and the second was swallowed (2026-08-28).

THE FIX IS THE THIRD ANSWER, NOT THE FIRST TWO. "Could not draw" only has to exist as an
answer because the fallback is written at every call site. The plain tier below always
works - a numbered prompt needs nothing but stdin - so a dispatcher that owns the
fall-through can resolve it internally and hand back exactly two outcomes. A caller that
cannot receive "unavailable" cannot mishandle it.

    answer = questions.choose("Update the team", [(value, label, help), ...])
    if answer.cancelled:
        ...            # the human left. Whatever that means HERE is the caller's business
    use(answer.value)  # they chose this

The module is `questions` and not `ask` for a reason worth the extra keystrokes:
install_helper already has an `ask()` that prompts for a LINE OF TEXT, and two functions
called ask() meaning different things is the same overloading, one level up.

Tiers are asked in order and the first that can draw wins. A tier that cannot draw returns
None from `render`; that never reaches a caller.
"""

from __future__ import annotations

import os
import string
import sys
from pathlib import Path

# Screens this module knows how to ask. Deliberately a closed set: a `kind` that is not
# here has no plain-text rendering, and a question that cannot be asked without a
# full-screen app is a question this framework should refuse rather than half-support.
CHOOSE = "choose"
CONFIRM = "confirm"

_KINDS = (CHOOSE, CONFIRM)

# Selection keys, in the order a person reaches for them: the digits, then the letters
# except "b" and "q". Those two are excluded on purpose - both full-screen tiers already
# spend them on leaving, and a key that both chooses an option and cancels the screen is
# the same overloading in miniature.
#
# Spelled as a rule rather than as the resulting string, which says what is going on and
# has the side benefit of not looking like a leaked credential to a secret scanner
# (gitleaks scored the literal at 5.04 entropy and blocked the commit, 2026-08-30).
_LEAVE_KEYS = "bq"
_KEYS = "123456789" + "".join(c for c in string.ascii_lowercase if c not in _LEAVE_KEYS)


class Question:
    """What is being asked, with no idea how it will be drawn.

    `options` is [(value, label, help)] - the VALUE is what the caller gets back, so it can
    be anything the caller finds useful (a slug, a Path, an enum member) rather than a
    string the caller then has to map. `help` is the pane text for that row and may be "".

    `cancel_hint` is what the footer calls leaving - "back", "cancel", "back to the shell".
    It is wording only: what cancelling MEANS is decided by the caller reading the answer,
    which is the whole point of having one vocabulary.

    There is deliberately nowhere to put a paragraph of preamble. Every tier renders the
    title and the per-option help; a field only some tiers could draw would let a screen
    carry load-bearing text on one tier and lose it on another, which is the class of
    divergence this module exists to end. If a person needs to know something to choose,
    it belongs against the option they would choose because of it.
    """

    def __init__(
        self,
        kind: str,
        title: str,
        options,
        *,
        cancel_hint: str = "back",
        project_dir: Path | None = None,
    ) -> None:
        if kind not in _KINDS:
            raise ValueError(f"unknown question kind: {kind!r}")
        if not options:
            raise ValueError("a question with no options is not a question")
        if len(options) > len(_KEYS):
            # Checked HERE rather than when a tier draws it, for the reason the kind check
            # above is: a question nobody can answer is a mistake in the code that wrote
            # it, and it should fail on the author's screen, not on a user's. Drawing it
            # would mean zip() silently dropping the tail, and a menu that quietly loses
            # its last options is worse than one that refuses - nobody can see what is
            # missing, least of all the caller who believes they are on screen.
            raise ValueError(
                f"{len(options)} options is more than the {len(_KEYS)} selectable keys - "
                "a question this long needs a list screen, not a chooser"
            )
        self.kind = kind
        self.title = title
        self.options = [tuple(row) + ("",) * (3 - len(row)) for row in options]
        self.cancel_hint = cancel_hint
        self.project_dir = project_dir

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Question({self.kind!r}, {self.title!r}, {len(self.options)} options)"


class Answer:
    """What the human did. Two outcomes, and no third.

    `cancelled` is a real answer - the human looked and chose to leave - and is NOT the
    same as "the screen could not run", which never escapes the dispatcher. Callers that
    conflated those two are the reason this class exists.
    """

    __slots__ = ("value", "cancelled")

    def __init__(self, value=None, cancelled: bool = False) -> None:
        self.value = value
        self.cancelled = bool(cancelled)

    @classmethod
    def chosen(cls, value) -> "Answer":
        return cls(value=value, cancelled=False)

    @classmethod
    def left(cls) -> "Answer":
        return cls(value=None, cancelled=True)

    # NO __bool__, on purpose, and it is the same lesson one level up. `if answer:` reads
    # beautifully until the question is a confirm: a human who deliberately answered "no"
    # produces Answer.chosen(False), which is a CHOICE and would have to be truthy - while
    # the identical line on a choose() means "they picked something". One expression, two
    # meanings, decided by which question it happens to be attached to. That is precisely
    # the overloading this module exists to remove, so the convenience is refused and
    # callers say which they mean: `answer.cancelled`, then `answer.value`.
    def __bool__(self):
        raise TypeError(
            "read answer.cancelled or answer.value - an Answer is deliberately not truthy "
            "(a chosen False is a real answer, and `if answer:` cannot say so)"
        )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Answer(cancelled)" if self.cancelled else f"Answer({self.value!r})"


def _tiers():
    """The renderers to try, best first.

    Named rather than discovered: the order is a decision (richest that can draw), and a
    plugin-style scan would make it an accident of import order.
    """
    return ("launcher_textual", "installer_app")


def _import(name: str):
    """A tier module, or None. Never raises - a tier that cannot import cannot draw."""
    here = Path(__file__).resolve().parent
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    try:
        return __import__(name)
    except Exception:
        return None


def ask(question: Question, mod, tiers=None) -> Answer:
    """Put `question` to the human on the best tier that can draw it.

    Always returns an Answer. There is no failure mode a caller has to handle: the plain
    tier needs nothing but stdin, and when even that is unavailable - a piped run, no tty -
    the answer is `left`, because nobody was there to choose.
    """
    if not os.environ.get("VIRT_SURV_NO_APP"):
        for name in tiers if tiers is not None else _tiers():
            module = _import(name)
            render = getattr(module, "render_question", None) if module else None
            if render is None:
                continue
            try:
                answer = render(question, mod)
            except Exception:
                continue  # a tier that raises is a tier that cannot draw
            if answer is not None:
                return answer
    return ask_plain(question)


def ask_plain(question: Question) -> Answer:
    """The tier that always works: a numbered list on stderr, an answer on stdin.

    On stderr because stdout is the launcher's decision channel, a rule this repo has
    broken once and paid for. No tty means nobody is there to answer, which is `left` -
    not a default, and not a crash.
    """
    err = sys.stderr
    try:
        if not sys.stdin.isatty():
            return Answer.left()
    except Exception:
        return Answer.left()

    print("", file=err)
    print(f"  {question.title}", file=err)
    for number, (_value, label, help_text) in enumerate(question.options, 1):
        print(f"    [{number}] {label}", file=err)
        if help_text:
            print(f"        {help_text}", file=err)
    print(f"    [b] {question.cancel_hint}", file=err)

    while True:
        try:
            print("    Choice: ", end="", file=err)
            raw = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("", file=err)
            return Answer.left()
        if raw in ("", "b", "q"):
            return Answer.left()
        try:
            index = int(raw) - 1
        except ValueError:
            print(f"    1-{len(question.options)} or b, please.", file=err)
            continue
        if 0 <= index < len(question.options):
            return Answer.chosen(question.options[index][0])
        print(f"    1-{len(question.options)} or b, please.", file=err)


def chooser_rows(question: Question):
    """([(key, label, help, writes)], {key: value}) - the row shape both full-screen
    tiers already draw for installer menus.

    `writes` is always "" because a framework question touches nothing outside the repo;
    the column exists so an installer menu can warn before a destructive key, and inventing
    a warning here would make the real ones mean less. The second return value maps back to
    the caller's own values, so a tier never has to know what an option MEANS.
    """
    rows, back = [], {}
    for key, (value, label, help_text) in zip(_KEYS, question.options):
        rows.append((key, label, help_text, ""))
        back[key] = value
    return rows, back


def from_chooser(question: Question, picked, back):
    """A chooser's answer in the shared vocabulary, or None if it could not draw.

    The one place the old three-way return is collapsed to two, and the reason no caller
    has to get it right again: None stays None so `ask` tries the next tier, "" is the
    human leaving, and anything else is their choice.
    """
    if picked is None:
        return None
    if picked in back:
        return Answer.chosen(back[picked])
    return Answer.left()


def choose(title: str, options, *, cancel_hint: str = "back", mod=None, project_dir=None) -> Answer:
    """Ask someone to pick one of `options`. The whole framework in one call.

    `options` is [(value, label, help)]. The answer is theirs or it is `left`; there is no
    third case to handle, and nothing for a call site to get wrong.
    """
    return ask(
        Question(CHOOSE, title, options, cancel_hint=cancel_hint, project_dir=project_dir), mod
    )


def confirm(
    title: str, yes: str, no: str, *, help_yes: str = "", help_no: str = "", mod=None
) -> Answer:
    """A two-way decision, both sides named. Returns True/False, or `left` for Esc.

    Both answers get a LABEL rather than one being "the other one": "delete it" / "keep it"
    is a decision someone can make at a glance, where "are you sure? y/n" is one they make
    by guessing which way round it reads.
    """
    return ask(
        Question(
            CONFIRM, title, [(True, yes, help_yes), (False, no, help_no)], cancel_hint="cancel"
        ),
        mod,
    )


class scripted:
    """A stand-in for this module that answers from a list. For TESTS.

    A framework with one way in needs one way to answer, or every migrated screen's tests
    go back to faking a tty and stubbing builtins.input - which is what they did before,
    and which is why two of them pinned semantics the framework had already removed
    (2026-08-30).

    It lives here rather than in a conftest so that it stays honest: it is the same
    Answer, and a screen's test therefore exercises the same two outcomes a person can
    produce. Each entry is either an option VALUE to choose or `None` to leave.

        monkeypatch.setattr(install_helper, "_ask", lambda: questions.scripted(["1"]))

    Deliberately NOT a hook inside ask(): production code that consults a test channel can
    be steered by anything that can set it, and the seam is the thing most likely to be
    forgotten when reasoning about what a user can actually cause.
    """

    def __init__(self, answers):
        self._answers = list(answers)
        self.asked = []  # the Questions it was given, for tests that check the wording

    def _next(self, question):
        self.asked.append(question)
        if not self._answers:
            raise AssertionError(f"unscripted question: {question.title!r}")
        picked = self._answers.pop(0)
        if picked is None:
            return Answer.left()
        allowed = [value for value, _label, _help in question.options]
        if picked not in allowed:
            raise AssertionError(
                f"{picked!r} is not on offer for {question.title!r} - options are {allowed!r}"
            )
        return Answer.chosen(picked)

    def choose(self, title, options, *, cancel_hint="back", mod=None, project_dir=None):
        return self._next(Question(CHOOSE, title, options, cancel_hint=cancel_hint))

    def confirm(self, title, yes, no, *, help_yes="", help_no="", mod=None):
        return self._next(Question(CONFIRM, title, [(True, yes, help_yes), (False, no, help_no)]))
