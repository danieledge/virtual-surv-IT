"""Single-deliverable close (2026-08-18): the mechanical gates must not demand a
delivery report when one artifact already carries the engagement's substance.

Live report: a /why-no-alert close claimed an 'engagement report' was pending over a
diagnosis that covered everything. The doctrine fix lives in the bookends; THIS pins the
mechanical half - a diagnosis + summary email close passes check_artifacts and
set-status closed with no delivery-report file anywhere."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _es(art: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "scripts.engagement_state", "--dir", str(art), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=120,
    )


def test_diagnosis_plus_email_closes_without_a_delivery_report(tmp_path):
    project = tmp_path / "proj"
    art = project / "artifacts"
    art.mkdir(parents=True)
    assert _es(art, "init", "--title", "Why no alert: demo", "--slug", "wna").returncode == 0

    (art / "DIAGNOSIS-wna.md").write_text(
        "# Alert-absence diagnosis\n\n**Status:** Final · **Verdict:** calibration "
        "outcome, not a defect\n\nBody (synthetic).\n\n## Close\n\n- Team: Morgan (PM) 🤖 "
        "· Ana (data-analyst) 🤖 - Virtual Surveillance IT\n- Next steps: BTL-first "
        "threshold review.\n",
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, "-m", "scripts.render_html", str(art / "DIAGNOSIS-wna.md")],
        capture_output=True,
        cwd=REPO_ROOT,
        timeout=120,
    )
    assert _es(art, "add-artifact", "DIAGNOSIS-wna.md", "--title", "Diagnosis (the delivery)", "--slug", "wna").returncode == 0
    assert _es(art, "set-status", "closing", "--slug", "wna").returncode == 0
    _es(art, "resolve-outstanding", "independent QA", "--slug", "wna")
    _es(art, "resolve-outstanding", "DoD", "--slug", "wna")
    (art / "engagement-summary-email-wna.txt").write_text(
        "Subject: diagnosis complete\n\nHi,\n\nDiagnosis delivered - calibration "
        "outcome (see the report). Next: BTL-first review.\n\nI'm an AI agent with "
        "Virtual Surveillance IT.\nMorgan (PM) 🤖\n",
        encoding="utf-8",
    )
    assert _es(art, "add-artifact", "engagement-summary-email-wna.txt", "--title", "Engagement summary email", "--slug", "wna").returncode == 0
    assert _es(art, "set-team", "Morgan (PM) 🤖", "Ana (data-analyst) 🤖", "--slug", "wna").returncode == 0
    assert _es(art, "finalise-artifacts", "--slug", "wna").returncode == 0
    assert _es(art, "set-footprint", "--agents", "1", "--tokens", "~20k", "--slug", "wna").returncode == 0

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    check = subprocess.run(
        [sys.executable, "-m", "scripts.check_artifacts", "--fix"],
        capture_output=True,
        text=True,
        cwd=project,
        env=env,
        timeout=180,
    )
    assert "delivery" not in (check.stdout + check.stderr).lower().replace(
        "see the delivery report", ""
    ), f"a gate demanded a delivery report:\n{check.stdout}\n{check.stderr}"

    closed = _es(art, "set-status", "closed", "--slug", "wna")
    assert closed.returncode == 0, closed.stdout + closed.stderr
    state = json.loads((art / "engagement-state.json").read_text(encoding="utf-8"))
    assert state["status"] == "closed"
    paths = [a["path"] for a in state["artifacts"]]
    assert not any("delivery-report" in p for p in paths)  # the diagnosis IS the delivery
