"""AI identity at the SOURCE, not just at the gate.

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
