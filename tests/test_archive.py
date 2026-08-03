"""Archive marker + closed-pack fingerprint (0.33.2): `.archive` excludes a directory
from every scanner (in-place, no moves); a closed pack whose stat-only fingerprint
still matches its gate-passing close is skipped without content reads. Safeguard:
an archived-but-open pack is ARCHIVED-OPEN on CLI checker runs, never a silent skip."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_artifacts import (
    archived_open_packs,
    engagement_packs,
    main as ca_main,
)
from scripts.engagement_state import (
    archived_slugs,
    compute_fingerprint,
    is_archived,
    load_state,
    main as es_main,
)

MORGAN_EMAIL = (
    "Done.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n"
)


def _closed_pack(root: Path, slug: str) -> Path:
    pack = root / slug
    assert es_main(["--dir", str(pack), "init", "--title", slug, "--slug", slug]) == 0
    (pack / f"engagement-summary-{slug}.txt").write_text(MORGAN_EMAIL, encoding="utf-8")
    es_main(
        [
            "--dir",
            str(pack),
            "add-artifact",
            f"engagement-summary-{slug}.txt",
            "--title",
            "Email",
            "--final",
        ]
    )
    es_main(["--dir", str(pack), "set-team", "Ana (analysis)"])
    es_main(["--dir", str(pack), "finalise-artifacts"])
    assert es_main(["--dir", str(pack), "set-status", "closed", "--verdict", "done"]) == 0
    return pack


# ------------------------------------------------------------------ the verbs


def test_archive_closed_pack_writes_marker_and_registry_line(tmp_path):
    root = tmp_path / "artifacts"
    pack = _closed_pack(root, "old-review")
    assert es_main(["--dir", str(root), "archive", "old-review"]) == 0
    assert is_archived(pack)
    marker = (pack / ".archive").read_text(encoding="utf-8")
    assert "engagement_state archive" in marker and "closed" in marker
    assert archived_slugs(root) == ["old-review"]
    registry = (root / "ENGAGEMENTS.md").read_text(encoding="utf-8")
    assert "Archived: 1" in registry and "old-review" in registry


def test_archive_refuses_open_pack_without_force(tmp_path, capsys):
    root = tmp_path / "artifacts"
    assert es_main(["--dir", str(root / "live"), "init", "--title", "L", "--slug", "live"]) == 0
    assert es_main(["--dir", str(root), "archive", "live"]) == 2
    assert "refusing to archive" in capsys.readouterr().err
    assert not is_archived(root / "live")


def test_archive_force_logs_the_exception(tmp_path):
    root = tmp_path / "artifacts"
    assert es_main(["--dir", str(root / "aband"), "init", "--title", "A", "--slug", "aband"]) == 0
    assert es_main(["--dir", str(root), "archive", "aband", "--force"]) == 0
    assert is_archived(root / "aband")
    state = load_state(root / "aband")
    assert any("archived while 'in_progress'" in line for line in state["log"])


def test_archive_all_closed_skips_open_packs(tmp_path):
    root = tmp_path / "artifacts"
    _closed_pack(root, "done-1")
    _closed_pack(root, "done-2")
    assert es_main(["--dir", str(root / "live"), "init", "--title", "L", "--slug", "live"]) == 0
    assert es_main(["--dir", str(root), "archive", "--all-closed"]) == 0
    assert is_archived(root / "done-1") and is_archived(root / "done-2")
    assert not is_archived(root / "live")


def test_unarchive_round_trip(tmp_path):
    root = tmp_path / "artifacts"
    pack = _closed_pack(root, "old")
    es_main(["--dir", str(root), "archive", "old"])
    assert es_main(["--dir", str(root), "unarchive", "old"]) == 0
    assert not is_archived(pack)
    assert archived_slugs(root) == []


# --- --slug accepted as an alias on archive/unarchive/set-active (2026-08-03) -------------
# Live report: every other resolvable subcommand accepts `--slug TARGET_SLUG`, but these
# three took their slug positionally with no --slug alias at all - `archive --slug X`
# exited 2 with no hint that the flag wasn't accepted there.


def test_archive_accepts_slug_flag_like_every_other_subcommand(tmp_path):
    root = tmp_path / "artifacts"
    pack = _closed_pack(root, "old-review")
    assert es_main(["--dir", str(root), "archive", "--slug", "old-review"]) == 0
    assert is_archived(pack)


def test_unarchive_accepts_slug_flag(tmp_path):
    root = tmp_path / "artifacts"
    pack = _closed_pack(root, "old")
    es_main(["--dir", str(root), "archive", "old"])
    assert es_main(["--dir", str(root), "unarchive", "--slug", "old"]) == 0
    assert not is_archived(pack)


def test_set_active_accepts_slug_flag(tmp_path):
    from scripts.engagement_state import read_active

    root = tmp_path / "artifacts"
    _closed_pack(root, "engagement-a")
    assert es_main(["--dir", str(root), "set-active", "--slug", "engagement-a"]) == 0
    assert read_active(root) == "engagement-a"


def test_archive_slug_flag_works_after_the_subcommand_too(tmp_path):
    # The positional already worked in this position; --slug previously did not (it was
    # simply never declared on archive's own subparser).
    root = tmp_path / "artifacts"
    pack = _closed_pack(root, "old-review")
    assert es_main(["--dir", str(root), "archive", "--slug", "old-review"]) == 0
    assert is_archived(pack)


def test_archive_still_refuses_with_neither_slug_nor_all_closed(tmp_path, capsys):
    root = tmp_path / "artifacts"
    assert es_main(["--dir", str(root), "archive"]) == 2
    assert "give a" in capsys.readouterr().err


def test_unarchive_still_refuses_with_no_slug(tmp_path, capsys):
    root = tmp_path / "artifacts"
    assert es_main(["--dir", str(root), "unarchive"]) == 2
    assert "give a" in capsys.readouterr().err


def test_set_active_still_refuses_with_no_slug(tmp_path, capsys):
    root = tmp_path / "artifacts"
    assert es_main(["--dir", str(root), "set-active"]) == 2
    assert "give a" in capsys.readouterr().err


def test_archive_positional_still_works_unchanged(tmp_path):
    """Backward compatibility: the pre-existing positional form is untouched."""
    root = tmp_path / "artifacts"
    pack = _closed_pack(root, "old-review")
    assert es_main(["--dir", str(root), "archive", "old-review"]) == 0
    assert is_archived(pack)


# ------------------------------------------------------------------ scan exclusion


def test_archived_pack_invisible_to_scanners(tmp_path, capsys):
    root = tmp_path / "artifacts"
    pack = _closed_pack(root, "old")
    # plant a defect that WOULD fire: an unrendered md
    (pack / "notes.md").write_text("# notes\n", encoding="utf-8")
    assert any("MISSING-HTML" in f for f in _run_checker(root, capsys))
    es_main(["--dir", str(root), "archive", "old"])
    assert engagement_packs(root) == []
    findings = _run_checker(root, capsys)
    assert not any("MISSING-HTML" in f for f in findings)


def test_plain_directory_with_marker_is_skipped(tmp_path, capsys):
    """The generalisation: any directory (not just packs) is excludable by marker."""
    root = tmp_path / "artifacts"
    _closed_pack(root, "current")
    junk = root / "legacy-export"
    junk.mkdir()
    (junk / ".archive").write_text("", encoding="utf-8")
    (junk / "dump.md").write_text("# junk\n", encoding="utf-8")  # no .html sibling
    findings = _run_checker(root, capsys)
    assert not any("dump.md" in f for f in findings)


def test_archived_open_pack_is_flagged_not_silent(tmp_path):
    root = tmp_path / "artifacts"
    assert es_main(["--dir", str(root / "dodge"), "init", "--title", "D", "--slug", "dodge"]) == 0
    (root / "dodge" / ".archive").write_text("", encoding="utf-8")  # bare touch, no verb
    findings = archived_open_packs(root)
    assert any("ARCHIVED-OPEN" in f and "dodge" in f for f in findings)


def _run_checker(root: Path, capsys) -> list[str]:
    ca_main(["check_artifacts", str(root)])
    return capsys.readouterr().out.splitlines()


# ------------------------------------------------------------------ fingerprint fast path


def test_close_stores_fingerprint_and_checker_skips(tmp_path, capsys):
    root = tmp_path / "artifacts"
    pack = _closed_pack(root, "fast")
    state = load_state(pack)
    assert state.get("scan_fingerprint")
    assert state["scan_fingerprint"] == compute_fingerprint(pack)
    ca_main(["check_artifacts", str(root)])
    out = capsys.readouterr().out
    assert "1 closed pack(s) skipped via fingerprint" in out
    assert "DoD artifact gate: OK" in out


def test_edited_deliverable_invalidates_fingerprint(tmp_path, capsys):
    root = tmp_path / "artifacts"
    pack = _closed_pack(root, "edited")
    email = next(pack.glob("engagement-summary-*.txt"))
    email.write_text(
        MORGAN_EMAIL + "\nP.S. edited after close, much longer now\n", encoding="utf-8"
    )
    ca_main(["check_artifacts", str(root)])
    out = capsys.readouterr().out
    assert "skipped via fingerprint" not in out  # the pack was genuinely re-scanned


def test_fingerprint_ignores_state_and_renders(tmp_path):
    root = tmp_path / "artifacts"
    pack = _closed_pack(root, "stable")
    before = compute_fingerprint(pack)
    # mutating the state re-renders START-HERE; neither may shift the fingerprint
    es_main(["--dir", str(pack), "log-note", "post-close note"])
    assert compute_fingerprint(pack) == before


def test_stale_closed_nudge_after_five_packs(tmp_path, capsys):
    root = tmp_path / "artifacts"
    for i in range(5):
        pack = _closed_pack(root, f"old-{i}")
        state = load_state(pack)
        state.pop("scan_fingerprint", None)  # simulate pre-0.33.2 closes
        (pack / "engagement-state.json").write_text(json.dumps(state), encoding="utf-8")
    ca_main(["check_artifacts", str(root)])
    out = capsys.readouterr().out
    assert "archive --all-closed" in out
