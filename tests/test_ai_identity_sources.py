"""DoD checks that have SOURCE support - the gate is not where a rule should first appear.

Started as an AI-identity file (2026-08-20) and generalised the next day, because the two
failure modes turned out to be the same shape seen from opposite sides:

  * a check nothing upstream helps you satisfy fires on nearly every engagement
    (AGENT-UNMARKED, QA-LEVEL-UNDECLARED), and
  * a check whose instruction admits no exceptions gets satisfied with invented content
    (FINDINGS-NO-DEV-GUIDANCE on an analysis with no code in it).

Both are fixed at the source - a template, a generator, or the wording an agent reads - and
pinned here so the fix cannot quietly regress.

AI identity at the SOURCE, not just at the gate.

2026-08-20 user report: "across a number of engagements the DoD check picks up lacking
robot emojis on agent names - most engagements see that."

That frequency is the finding. AGENT-UNMARKED firing on most engagements does not mean
most engagements are careless; it means the artifacts are being authored unmarked and the
Definition-of-Done gate is doing cleanup that should never have been necessary. A gate that
catches the same defect every time is measuring an upstream gap.

An audit of the sources found two: `codebase-map.md` and `codebase-map-area.md` both
attributed ownership to `Morgan (PM)` with no marker anywhere in the file, so every codebase
map authored from them started unmarked; and of the artifact GENERATORS only
engagement_state emitted a marker at all. These tests pin the sources shut so the gate goes
back to being an exception path.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.check_artifacts import _AI_MARKER, _KNOWN_PERSONAS, _PERSONA_RE  # noqa: E402

_ROSTER = {name.capitalize() for name in _KNOWN_PERSONAS}


def _roster_attributions(text: str) -> list[str]:
    """Persona attributions the DoD check would recognise: 'Name (Role)' where Name is on
    the roster. Exactly the shape AGENT-UNMARKED keys on."""
    return [
        m.group(0) for m in _PERSONA_RE.finditer(text) if m.group(1).strip() in _ROSTER
    ]


def test_no_template_attributes_work_to_an_agent_without_the_marker():
    """A template is the first draft of an artifact. One that names a roster persona with
    no 🤖 anywhere hands every artifact derived from it a guaranteed AGENT-UNMARKED."""
    offenders = []
    for path in sorted((REPO_ROOT / "docs" / "templates").rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        hits = _roster_attributions(text)
        if hits and _AI_MARKER not in text:
            offenders.append(f"{path.relative_to(REPO_ROOT)} -> {hits[:3]}")
    assert not offenders, "templates that would start an artifact unmarked:\n" + "\n".join(
        offenders
    )


def test_the_generators_that_author_a_whole_document_state_their_origin():
    """Artifacts the framework GENERATES must say they are AI-produced - the reader never
    sees the pack they came from. START-HERE (engagement_state) and the rendered review
    document (render_findings) are the two a human opens first, and neither said so until
    2026-08-20.

    render_html and render_docx are deliberately excluded: they convert an existing
    document, so the marker belongs to the source they are given, not to them."""
    for name in ("engagement_state", "render_findings"):
        source = (REPO_ROOT / "scripts" / f"{name}.py").read_text(encoding="utf-8")
        assert _AI_MARKER in source, f"{name}.py generates a whole artifact but never marks it"


def test_the_generated_start_here_actually_carries_it(tmp_path):
    """Belt and braces: assert the OUTPUT, not just that the marker appears in the source."""
    import subprocess

    workspace = tmp_path / "artifacts" / "demo"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.engagement_state",
            "init",
            "--dir",
            str(workspace),
            "--slug",
            "demo",
            "--title",
            "Demo",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        check=True,
    )
    text = (workspace / "START-HERE.md").read_text(encoding="utf-8")
    assert _AI_MARKER in text, "the generated START-HERE does not say it is AI-produced"
    assert "Virtual Surveillance IT" in text


def test_the_check_and_these_tests_agree_on_what_an_attribution_is():
    """If _PERSONA_RE ever changes shape, these tests must move with it rather than
    silently stop matching anything and pass vacuously."""
    assert _roster_attributions("Reviewed by Morgan (PM) today") == ["Morgan (PM)"]
    assert _roster_attributions("Reviewed by Daniel (CIO) today") == []


# --- the same lens applied to the other gates (2026-08-20) ------------------------------------


def test_the_qa_handover_template_prompts_for_the_level_the_gate_requires():
    """Same class of gap as the unmarked templates, found by asking the question generally:
    QA-LEVEL-UNDECLARED reads `qa_depth` from engagement state whenever a QA handover
    exists, but the handover template never mentioned the level or the command that records
    it - so satisfying the gate depended on the author remembering a step nothing prompted.
    A check with no source support fires on almost every engagement by construction."""
    text = (REPO_ROOT / "docs" / "templates" / "qa-handover.md").read_text(encoding="utf-8")
    assert "set-qa-depth" in text, "the template never names the command the gate reads"
    for level in ("quick", "deep", "audit"):
        assert level in text, f"the template does not offer the {level!r} level"
    assert "PARTIAL" in text, "the template must say that a quick pass closes PARTIAL"


def test_the_report_templates_prompt_for_developer_guidance():
    """FINDINGS-NO-DEV-GUIDANCE has source support - pinned so it keeps it."""
    for name in ("review-report.md", "delivery-report.md"):
        text = (REPO_ROOT / "docs" / "templates" / name).read_text(encoding="utf-8")
        assert "Developer guidance" in text, f"{name} stopped prompting for developer guidance"


# --- a mandatory section must not become invented content (2026-08-21) -------------------------


def test_the_output_format_tells_a_reviewer_what_to_do_when_there_is_no_code():
    """2026-08-21 live report: an ANALYSIS engagement produced a developer-notes section
    although the task involved no code. The gate was not at fault - a one-line "not
    applicable" already satisfies it. The INSTRUCTION was: it said the section is mandatory
    and that "the developer always leaves with something to learn", with no provision for a
    deliverable that has no code and no author, so the agent manufactured some.

    A review-shaped artifact is anything with a '## Findings' section, and plenty carry no
    code at all - FP investigations, data-quality assessments, threshold reviews."""
    text = (REPO_ROOT / "docs" / "review" / "output-format.md").read_text(encoding="utf-8")
    assert "No code in scope" in text, "the non-code case is still undocumented"
    assert "never invent developer notes" in text.lower() or "never invent" in text.lower()
    assert "Not applicable" in text, "no example of the one-line declaration to copy"


def test_the_definition_of_done_scopes_developer_guidance_to_code():
    text = (REPO_ROOT / "docs" / "DEFINITION-OF-DONE.md").read_text(encoding="utf-8")
    assert "contains no code" in text, "DoD still reads as an unconditional requirement"
    assert "invented coding advice" in text


def test_a_not_applicable_declaration_actually_satisfies_the_gate(tmp_path):
    """The guidance above is only honest if the checker accepts what it tells people to
    write. Asserted against the real matchers rather than assumed."""
    import re

    from scripts.check_artifacts import (
        _DEV_GUIDANCE_HEADING_RE,
        _DEV_GUIDANCE_PLACEHOLDER,
        _FINDINGS_SECTION_RE,
    )

    text = (
        "# Alert false-positive analysis\n\n## Findings\n\n"
        "### 🔴 Threshold too tight\n**Impact if unaddressed:** volume.\n\n"
        "## 🔵 Developer guidance - improving future code\n\n"
        "Not applicable: this analysis reviewed alert output, no code in scope.\n"
    )
    assert _FINDINGS_SECTION_RE.search(text), "fixture is not review-shaped"
    heading = _DEV_GUIDANCE_HEADING_RE.search(text)
    assert heading, "the heading must still be present - only its CONTENT is conditional"
    rest = text[heading.end() :]
    nxt = re.search(r"^## ", rest, re.M)
    body = rest[: nxt.start()] if nxt else rest
    assert body.strip() and body.strip() != _DEV_GUIDANCE_PLACEHOLDER, (
        "a one-line not-applicable declaration must satisfy FINDINGS-NO-DEV-GUIDANCE"
    )


# --- what a tracker comment must carry (2026-08-21) -------------------------------------------


def test_jira_comments_carry_a_summary_and_say_where_results_are_when_attaching_fails():
    """2026-08-21 user requirement. Two properties, both aimed at the same reader - someone
    looking at a ticket who was never in the session:

      * every comment opens with a summary from Morgan, not a bare status token;
      * a failed attachment says so and gives the absolute workspace path, rather than
        silently pasting the whole report body into a corporate tracker (noise, and an
        uncontrolled copy of the content)."""
    ref = (
        REPO_ROOT / ".claude" / "skills" / "engage" / "references" / "integrations.md"
    ).read_text(encoding="utf-8")
    assert "summary from Morgan" in ref
    assert "could not be uploaded" in ref or "could-not-attach" in ref
    assert "absolute" in ref and "artifacts/<slug>/" in ref
    assert "Do not dump the report body" in ref, "the anti-paste rule is gone"


def test_the_team_raised_close_attaches_like_the_inbound_one_does():
    """The asymmetry this removes: identical work reached a ticket in full or in outline
    depending only on which door it came in by."""
    ref = (
        REPO_ROOT / ".claude" / "skills" / "engage" / "references" / "integrations.md"
    ).read_text(encoding="utf-8")
    at_close = ref[ref.index("**At close**") :][:600]
    assert "attach the delivery report" in at_close, "team-raised close still summary-only"


def test_unattended_detail_is_deferred_not_carried_at_every_open():
    """--auto is off by default and rare, so its rules live behind a read-trigger rather
    than in SKILL.md where every engagement open would pay for them (+532 tokens when they
    were inline). The trigger has to actually name the file, or the detail is unreachable."""
    skill = (REPO_ROOT / ".claude" / "skills" / "engage" / "SKILL.md").read_text(encoding="utf-8")
    assert "references/auto-mode.md" in skill, "SKILL.md no longer points at the detail"
    detail = REPO_ROOT / ".claude" / "skills" / "engage" / "references" / "auto-mode.md"
    assert detail.is_file()
    body = detail.read_text(encoding="utf-8")
    for rule in ("assumed-", "PARTIAL", "blocked", "never create it"):
        assert rule in body, f"the deferred reference dropped {rule!r}"
