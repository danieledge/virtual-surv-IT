"""Fail-safe fixes to the DoD artifact gate (2026-07-29 workflow-robustness register, phase 1).

Pins the checker-side holes the register reproduced against the real code:
  G1 - a pack with NO START-HERE routed down the "closed" branch, disarming every
       close-only guard exactly when the team forgot the index;
  G2 - in workspace mode, a file written to the artifacts ROOT was checked by nothing;
  G5 - three non-equivalent status parsers meant a words-only status armed one consumer
       and not another (the shared `pack_status` is now the single answer);
  G7 - the checker required a state file where the anchor accepted an index alone, so a
       hand-made pack was anchored but never gated;
  G9 - CODE-NO-QA was satisfied by ANY qa-handover in the tree, so code passed on a
       sibling engagement's paperwork (the reproduced vendorx leak);
  R5/R6 - a 'closing' transitional status makes the close window recognisable: close
       artifacts are legitimate during it, and nothing demands them yet.
"""

from __future__ import annotations

import json

from scripts.check_artifacts import (
    check,
    check_root_orphans,
    engagement_packs,
    main as ca_main,
    pack_status,
    workspace_dirs,
)


def _touch(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _index(art, status, listed=()):
    rows = "\n".join(f"- `{name}` - purpose" for name in listed)
    _touch(art / "START-HERE.md", f"# START HERE\n\n| **Status** | {status} |\n\n{rows}\n")
    _touch(art / "START-HERE.html")


def _ws(tmp_path, slug):
    from scripts.engagement_state import main as es_main

    art = tmp_path / "artifacts"
    es_main(["--dir", str(art / slug), "init", "--title", slug, "--slug", slug])
    return art


# --- G1: no index is NOT closed -----------------------------------------------------------


def test_no_index_pack_is_not_closed(tmp_path):
    """[reproduced] The register's live case: delivery report, no index. The old code read
    this as closed/legacy and demanded only the email; now it is fail-safe NOT closed."""
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md")
    _touch(art / "delivery-report.html")
    codes = "".join(check(art))
    assert "MISSING-INDEX" in codes and "FINAL-BEFORE-CLOSE" in codes
    assert "MISSING-SUMMARY-EMAIL" not in codes


def test_no_index_summary_email_is_premature_not_required(tmp_path):
    art = tmp_path / "artifacts"
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
    codes = "".join(check(art))
    assert "SUMMARY-BEFORE-CLOSE" in codes
    assert "MISSING-SUMMARY-EMAIL" not in codes


# --- G5: one shared status parser ---------------------------------------------------------


def test_pack_status_reads_words_only_line(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "START-HERE.md", "# S\n\nStatus: in progress\n")
    assert pack_status(art) == "open"


def test_pack_status_ignores_stray_emoji_outside_status_line(tmp_path):
    """The old hook sniff re-armed on an ⏳ ANYWHERE in a closed index (a history bullet,
    a legend). The shared parser reads the status line only."""
    art = tmp_path / "artifacts"
    _touch(
        art / "START-HERE.md",
        "# S\n\n| **Status** | ✅ CLOSED 2026-07-01 |\n\n- history: ⏳ was in progress\n",
    )
    assert pack_status(art) == "closed"


def test_pack_status_state_file_is_authoritative(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": "closed"}), encoding="utf-8"
    )
    _touch(art / "START-HERE.md", "Status: ⏳ in progress\n")
    assert pack_status(art) == "closed"


def test_pack_status_maps_closing(tmp_path):
    art = tmp_path / "artifacts"
    art.mkdir()
    (art / "engagement-state.json").write_text(
        json.dumps({"schema": 2, "status": "closing"}), encoding="utf-8"
    )
    assert pack_status(art) == "closing"


def test_pack_status_none_for_non_pack(tmp_path):
    (tmp_path / "artifacts").mkdir()
    assert pack_status(tmp_path / "artifacts") is None


# --- G7: one workspace-detection rule -----------------------------------------------------


def test_handmade_index_only_workspace_is_gated(tmp_path, capsys):
    """A hand-made artifacts/<slug>/ pack (index, no state file) was anchored but never
    checked. The gate must see everything the anchor sees."""
    art = _ws(tmp_path, "audit")
    manual = art / "manual"
    _index(manual, "⏳ IN PROGRESS", listed=["notes.md"])
    _touch(manual / "notes.md")  # defect: no .html sibling
    assert manual in engagement_packs(art)
    assert manual not in workspace_dirs(art)  # not registrable (no state file)
    rc = ca_main(["check_artifacts", str(art)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "[manual]" in out and "MISSING-HTML" in out


# --- G2: root orphans in workspace mode ---------------------------------------------------


def test_root_orphan_flagged_after_snapshot(tmp_path, capsys):
    art = _ws(tmp_path, "audit")
    ca_main(["check_artifacts", str(art)])  # first run takes the (empty) snapshot
    capsys.readouterr()
    _touch(art / "stray-report.md")
    rc = ca_main(["check_artifacts", str(art)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "ORPHAN-ARTIFACT" in out and "stray-report.md" in out


def test_preexisting_root_files_grandfathered(tmp_path, capsys):
    """D2 ruling 2026-07-29: historical flat files are exempt; only files added after the
    snapshot are orphans."""
    art = _ws(tmp_path, "audit")
    _touch(art / "old-legacy-report.md")  # exists before the rule's first run
    ca_main(["check_artifacts", str(art)])
    capsys.readouterr()
    _touch(art / "new-orphan.md")
    ca_main(["check_artifacts", str(art)])
    out = capsys.readouterr().out
    assert "new-orphan.md" in out and "ORPHAN-ARTIFACT" in out
    assert "old-legacy-report.md" not in out


def test_hook_side_root_scan_is_read_only(tmp_path):
    art = _ws(tmp_path, "audit")
    _touch(art / "stray.md")
    # No allowlist yet: the read-only consumer must neither write one nor flag anything.
    assert check_root_orphans(art) == []
    assert not (art / ".dod-root-allowlist.json").exists()


def test_flat_pack_alongside_workspaces_skips_orphan_scan(tmp_path, capsys):
    from scripts.engagement_state import main as es_main

    art = _ws(tmp_path, "audit")
    es_main(["--dir", str(art), "init", "--title", "Old", "--slug", "old"])  # flat
    rc = ca_main(["check_artifacts", str(art)])
    out = capsys.readouterr().out
    assert rc == 1
    assert "FLAT-PACK-UNMIGRATED" in out and "ORPHAN-ARTIFACT" not in out


# --- G9: QA lookup scoped per engagement --------------------------------------------------


def test_qa_leak_across_containers_flagged(tmp_path):
    """[reproduced] vendorx case: code in a subfolder passed CODE-NO-QA on a DIFFERENT
    engagement's qa-handover sitting at the root."""
    art = tmp_path / "artifacts"
    _touch(art / "vendor_ingest" / "ingest.py", "def run(): ...")
    _touch(art / "qa-handover-other-engagement.md")
    _touch(art / "qa-handover-other-engagement.html")
    _index(
        art,
        "⏳ IN PROGRESS",
        listed=["ingest.py", "qa-handover-other-engagement.md"],
    )
    codes = "".join(check(art))
    assert "CODE-NO-QA" in codes and "vendor_ingest" in codes


def test_qa_in_same_container_passes(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "vendor_ingest" / "ingest.py", "def run(): ...")
    _touch(art / "vendor_ingest" / "test_ingest.py", "def test_run(): ...")
    _touch(art / "vendor_ingest" / "qa-handover-vendor.md")
    _touch(art / "vendor_ingest" / "qa-handover-vendor.html")
    _index(
        art,
        "⏳ IN PROGRESS",
        listed=["ingest.py", "test_ingest.py", "qa-handover-vendor.md"],
    )
    codes = "".join(check(art))
    assert "CODE-NO-QA" not in codes and "CODE-NO-TESTS" not in codes


# --- R5/R6: the closing window ------------------------------------------------------------


def test_closing_status_allows_close_artifacts_without_demanding_them(tmp_path):
    """During 'closing', the delivery report and summary email are legitimate work in
    progress - neither premature (the old FINAL-BEFORE-CLOSE trap that told a resumed
    session to delete them) nor yet demanded (closed-only checks wait for the flip)."""
    art = tmp_path / "artifacts"
    _touch(art / "delivery-report.md")
    _touch(art / "delivery-report.html")
    _touch(
        art / "engagement-summary-x.txt",
        "Hi,\n\nAll done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
    )
    _index(
        art,
        "🔒 CLOSING - finishing close artifacts",
        listed=["delivery-report.md", "engagement-summary-x.txt"],
    )
    assert check(art) == []


def test_closing_without_close_artifacts_demands_nothing_yet(tmp_path):
    art = tmp_path / "artifacts"
    _touch(art / "review-pass-1.md")
    _touch(art / "review-pass-1.html")
    _index(art, "🔒 CLOSING - finishing close artifacts", listed=["review-pass-1.md"])
    assert check(art) == []
