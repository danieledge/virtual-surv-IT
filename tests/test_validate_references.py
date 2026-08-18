"""Tests for the internal reference checker (scripts/validate_references.py).

The repo's most common defect is a document pointing at something that moved, was renamed, or
never existed. Before this, each instance was caught by adding a bespoke assertion to
test_docs_consistency.py AFTER it broke; that file is twelve such hand-written checks while the
prompt surface references hundreds of paths.

These tests pin BOTH directions. A genuine break must be caught, and the three classes that are
correctly absent from this repo (runtime-created files, the user's own project files,
placeholders) must NOT be reported, because a checker that cries wolf gets switched off.
"""

from __future__ import annotations

import pytest

import scripts.validate_references as vr


# ------------------------------------------------------------------ extraction


def test_extracts_markdown_links_and_code_spans():
    text = "See [the guide](docs/team-operating-guide.md) and run `scripts/render_html.py`."
    refs = vr.extract_references(text)
    assert "docs/team-operating-guide.md" in refs
    assert "scripts/render_html.py" in refs


@pytest.mark.parametrize(
    "text",
    [
        "read [the docs](https://example.com/x.md)",  # external URL
        "mail [us](mailto:someone@example.com)",
        "the pack lives at `artifacts/<slug>/delivery-report.md`",  # placeholder
        "sweep `docs/*.md` for drift",  # glob
        "see `docs/adr/ADR-...-something.md`",  # ellipsis
        "the sentence ends. Then a new one starts.",  # prose with dots
        "`python -m scripts.render_html`",  # module form, not a path
    ],
)
def test_ignores_non_paths_and_patterns(text):
    assert vr.extract_references(text) == set()


def test_runtime_and_user_project_paths_are_not_references(tmp_path):
    """Files the TEAM creates during an engagement, or that live in the USER's project, are
    correctly absent from this repo and must never be reported."""
    for ref in (
        "artifacts/eng/delivery-report.md",
        "START-HERE.md",
        "engagement-state.json",
        "CODEBASE-MAP.md",
        "team-preferences.json",
        "review-pass-1.md",
    ):
        assert vr.extract_references(f"see `{ref}`") == set(), ref


# ------------------------------------------------------------------ resolution


def test_resolves_repo_relative_referrer_relative_and_by_basename(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("x", encoding="utf-8")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "tool.py").write_text("x", encoding="utf-8")
    referrer = tmp_path / "docs" / "other.md"
    referrer.write_text("x", encoding="utf-8")

    assert vr.resolves("docs/guide.md", referrer, tmp_path)  # repo-relative
    assert vr.resolves("guide.md", referrer, tmp_path)  # referrer-relative
    assert vr.resolves("tool.py", referrer, tmp_path)  # bare basename in a known dir
    assert not vr.resolves("docs/nope.md", referrer, tmp_path)


def test_known_absent_entries_all_carry_a_reason():
    """The allow-list is a judgement list, not a way to silence a genuine break. An entry with
    no reason should not survive review."""
    assert vr._KNOWN_ABSENT, "expected some documented exceptions"
    for ref, reason in vr._KNOWN_ABSENT.items():
        assert isinstance(reason, str) and len(reason.strip()) > 15, (
            f"{ref} is excused without a real reason"
        )


# ------------------------------------------------------------------ the live repo


def test_every_internal_reference_in_this_repo_resolves():
    """The point of the whole exercise.

    Caught on first run: ADR-005's Decision section named the hook `reanchor-persona.py` while
    the implementation is scripts/persona_anchor.py. The ADR's document-control rows were
    correct, so the stale name survived a dedicated documentation-drift sweep earlier the same
    day, and only a mechanical check found it.

    Clone caveat (found by the 2026-08-16 Windows VM run): docs/adr/ is deliberately
    untracked (internal docs, .gitignore 2026-08-13), so a fresh clone has none of the ADR
    files and every reference INTO docs/adr/ is unresolvable there by policy, not by drift.
    Full-strength validation runs wherever the files exist (the dev box); in a clone this
    skips rather than fails, which is the policy encoded, not coverage quietly lost - the
    skip reason says exactly what is missing.
    """
    import pathlib

    if not (pathlib.Path(vr.__file__).resolve().parents[1] / "docs" / "adr").is_dir():
        pytest.skip(
            "docs/adr/ is deliberately untracked (internal docs, .gitignore 2026-08-13) "
            "and absent in this clone - reference validation runs full-strength wherever "
            "the ADR files exist"
        )
    findings, checked = vr.check()
    assert checked > 100, f"only {checked} references found - the scanner is not seeing the docs"
    assert not findings, "unresolved internal references:\n" + "\n".join(
        f"  {f['reference']} <- {', '.join(f['referrers'][:2])}" for f in findings
    )
