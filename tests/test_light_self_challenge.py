"""The light profile's compensating control for the reviewer it does not run.

Standard `/engage` gets an independent challenge from a review agent. Light drops that by
design and, until 2026-08-26, put nothing in its place - so the cheapest possible substitute
is a single structured question the orchestrator answers about its own work before closing.
It is not a reviewer and does not pretend to be one; it exists so that "no independent
reviewer" does not silently become "no review at all".

These tests pin the properties that make it a control rather than a ritual: it is asked
before the close (after it, nothing can act on the answer), each verdict has a defined
consequence, and the unsafe verdict routes into the upgrade rule instead of a caveat.

Fragments, not sentences: the source is hard-wrapped, so asserting a long phrase tests where
the line breaks fall rather than what the text means.
"""

from __future__ import annotations

from pathlib import Path

_SKILL = Path(__file__).resolve().parents[1] / ".claude" / "skills" / "engage-light" / "SKILL.md"


def _text() -> str:
    return _SKILL.read_text(encoding="utf-8")


def test_light_asks_the_self_challenge_question():
    """The question itself, in the one form that covers all three failure directions."""
    text = _text()
    assert "wrong, incomplete or unsafe?" in text
    assert "independent reviewer" in text, "must say WHY it exists, or it reads as ceremony"


def test_the_challenge_is_asked_before_the_close_not_after():
    """Ordering IS the control. `set-status closed` runs the DoD gate and ends the
    engagement; a challenge answered after that point cannot re-tag a claim, add residual
    risk to the email, or trigger an upgrade - it can only produce a regret."""
    text = _text()
    challenge = text.index("Challenge it once")
    close = text.index("**5. Close-lite.**")
    assert challenge < close, "the self-challenge must precede the close, not follow it"
    assert "set-status closed" in text[close:], "close-lite still owns the terminal call"


def test_each_verdict_carries_a_consequence():
    """A self-check whose answers change nothing is theatre. Each of the three has a defined
    next action, so 'yes, a bit' cannot be a complete answer."""
    text = _text()
    step = text[text.index("Challenge it once") : text.index("**5. Close-lite.**")]
    assert "re-tag or" in step, "wrong -> fix the tag before closing"
    assert "residual risk" in step, "incomplete -> declared in the summary email"
    assert "upgrade trigger" in step, "unsafe -> upgrade, not a caveat"
    assert "never a confidence claim" in step, "light must not read as 'I am sure'"


def test_the_upgrade_rule_and_the_challenge_agree():
    """Two places describe the same escalation. If the challenge routes unsafe findings to
    the upgrade rule but the upgrade rule does not list them as a trigger, the documents
    contradict each other and the route is only advisory."""
    rule = _text()
    rule = rule[rule.index("**Upgrade rule (standing):**") :]
    assert "challenge" in rule, "the upgrade rule must name the challenge as a trigger"
    assert "set-profile standard" in rule, "and name the mechanism it uses"
