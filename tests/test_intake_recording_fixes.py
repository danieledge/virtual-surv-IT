"""Two intake-time recording fixes from the 2026-08-16 corp-Windows live session.

1. Consent-shaped decision keys are refused by set-decision(s): the model recorded the
   intake consent answer as `set-decision "execution-consent" "Yes - marker present at
   .claude/.exec-consent"` and the consent-write guard default-denied the whole Bash
   call (an interpreter command whose argument text names the protected marker is, to a
   lexical guard, a write attempt). The sanctioned command is `record-consent-outcome
   asked|declined`, which never carries the marker path; engagement_state now makes the
   safe path the only path. The guard itself is untouched (hardening is additive).

2. add-artifact heals the two path misspellings that double-resolved: a
   PROJECT-relative path re-naming the pack ("artifacts/<slug>/x.md" while --dir
   already points at artifacts/<slug>/) and an absolute path inside the pack - both
   used to wrongly flag a real, existing artifact added_before_file_existed.
"""

from __future__ import annotations

import json

from scripts.engagement_state import load_state, main as es_main


def _init(tmp_path, slug="pack"):
    art = tmp_path / "artifacts"
    assert es_main(["--dir", str(art / slug), "init", "--title", slug, "--slug", slug]) == 0
    return art / slug


def test_set_decision_refuses_consent_shaped_keys(tmp_path, capsys):
    ws = _init(tmp_path)
    rc = es_main(["--dir", str(ws), "set-decision", "execution-consent", "Yes"])
    err = capsys.readouterr().err
    assert rc == 2
    assert "record-consent-outcome" in err
    assert "execution-consent" not in load_state(ws).get("decisions", {})


def test_set_decisions_batch_refuses_consent_shaped_keys(tmp_path, capsys):
    ws = _init(tmp_path)
    payload = json.dumps({"data-attestation": "synthetic", "exec consent": "yes"})
    rc = es_main(["--dir", str(ws), "set-decisions", "--json", payload])
    err = capsys.readouterr().err
    assert rc == 2
    assert "record-consent-outcome" in err
    # Refused atomically - the innocent key must not half-land while the batch errors.
    assert "data-attestation" not in load_state(ws).get("decisions", {})


def test_ordinary_decision_keys_still_record(tmp_path):
    ws = _init(tmp_path)
    assert es_main(["--dir", str(ws), "set-decision", "data-attestation", "synthetic only"]) == 0
    assert load_state(ws)["decisions"]["data-attestation"] == "synthetic only"


def _artifact_rows(ws):
    return {row["path"]: row for row in load_state(ws).get("artifacts", [])}


def test_add_artifact_heals_project_relative_path(tmp_path, capsys):
    ws = _init(tmp_path)
    (ws / "engagement-brief.md").write_text("# brief\n", encoding="utf-8")
    rc = es_main(
        [
            "--dir",
            str(ws),
            "add-artifact",
            "artifacts/pack/engagement-brief.md",
            "--title",
            "Engagement Brief",
        ]
    )
    assert rc == 0
    assert "healed project-relative path" in capsys.readouterr().err
    rows = _artifact_rows(ws)
    assert "engagement-brief.md" in rows
    assert "added_before_file_existed" not in rows["engagement-brief.md"]


def test_add_artifact_heals_absolute_path_inside_the_pack(tmp_path):
    ws = _init(tmp_path)
    (ws / "brief.md").write_text("# brief\n", encoding="utf-8")
    assert es_main(["--dir", str(ws), "add-artifact", str(ws / "brief.md"), "--title", "B"]) == 0
    rows = _artifact_rows(ws)
    assert "brief.md" in rows
    assert "added_before_file_existed" not in rows["brief.md"]


def test_add_artifact_keeps_honestly_missing_path_and_flag(tmp_path, capsys):
    """Healing only rewrites when the healed form actually resolves - a genuinely
    missing file keeps its given path and its added_before_file_existed flag (the R8
    crash-recovery contract is unchanged)."""
    ws = _init(tmp_path)
    rc = es_main(["--dir", str(ws), "add-artifact", "artifacts/pack/nope.md", "--title", "N"])
    assert rc == 0
    assert "added_before_file_existed" in capsys.readouterr().err
    rows = _artifact_rows(ws)
    assert rows["artifacts/pack/nope.md"]["added_before_file_existed"] is True
