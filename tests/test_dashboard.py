"""Tests for the local static dashboard generator (scripts/dashboard.py).

2026-07-31 rewrite pins: archived engagements are excluded from both the DoD-gate scan and
the per-engagement table (the pre-rewrite version was archive-blind); the per-engagement
breakdown (status/phase/title/outstanding/ratifications/consent-outcome) comes straight
from engagement_state's own scan_engagements + each pack's state file; project-setup facts
(preferences, tool-probe, hook-wiring, branch) are read defensively and never crash on a
missing/malformed file; the gate reaches full parity with check_artifacts.py's own CLI
(registry + orphans + ARCHIVED-OPEN, not just per-pack findings); token usage is summed from
transcript usage fields with parse gaps COUNTED not hidden; all user-controlled strings are
HTML-escaped.
"""

from __future__ import annotations

import json
import sys

import pytest

from scripts.dashboard import (
    engagement_rows,
    gate_findings_for,
    hook_wiring,
    main,
    parse_transcripts,
    plugin_cache_version,
    project_summary,
    read_team_preferences,
    read_tool_probe,
    render,
    transcripts_dir_for,
)


def _mk_project(tmp_path, name="proj"):
    """A minimal project with NO engagement packs (the common case for a fresh checkout) -
    the flat artifacts/ root is empty, so the gate passes trivially."""
    p = tmp_path / name
    (p / "artifacts").mkdir(parents=True)
    return p


def _closed_engagement(project, slug="eng-a"):
    """A workspace pack that satisfies the mechanical gate, via the real
    engagement_state CLI - mirrors what an actual engagement leaves on disk."""
    from scripts.engagement_state import main as es_main

    pack = project / "artifacts" / slug
    assert es_main(["--dir", str(pack), "init", "--title", "Eng A", "--slug", slug]) == 0
    (pack / f"engagement-summary-{slug}.txt").write_text(
        "Hi,\n\nDone.\n\n\U0001f916 Morgan\nPM & Orchestrator - Virtual Surveillance IT (AI agent)\n",
        encoding="utf-8",
    )
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


def _open_engagement(project, slug="eng-b"):
    from scripts.engagement_state import main as es_main

    pack = project / "artifacts" / slug
    assert es_main(["--dir", str(pack), "init", "--title", "Eng B", "--slug", slug]) == 0
    return pack


def _usage_line(inp, out, cr=0, cw=0):
    return json.dumps(
        {
            "type": "assistant",
            "message": {
                "usage": {
                    "input_tokens": inp,
                    "output_tokens": out,
                    "cache_read_input_tokens": cr,
                    "cache_creation_input_tokens": cw,
                }
            },
        }
    )


# ------------------------------------------------------------------ per-engagement breakdown


def test_engagement_rows_shows_open_and_closed(tmp_path):
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    _open_engagement(p, "eng-b")
    rows = engagement_rows(p / "artifacts")
    slugs = {r["slug"]: r["status"] for r in rows}
    assert slugs == {"eng-a": "closed", "eng-b": "in_progress"}


def test_engagement_rows_excludes_archived(tmp_path):
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    from scripts.engagement_state import main as es_main

    assert es_main(["--dir", str(p / "artifacts"), "archive", "eng-a"]) == 0
    rows = engagement_rows(p / "artifacts")
    assert rows == []


def test_engagement_rows_no_artifacts_dir_is_empty(tmp_path):
    assert engagement_rows(tmp_path / "artifacts") == []


def test_engagement_rows_carries_outstanding_and_ratifications(tmp_path):
    from scripts.engagement_state import main as es_main

    p = _mk_project(tmp_path)
    pack = _open_engagement(p, "eng-c")
    before = engagement_rows(p / "artifacts")[0]["outstanding"]  # init seeds 2 defaults
    es_main(["--dir", str(pack), "add-outstanding", "waiting on X"])
    es_main(["--dir", str(pack), "add-ratification", "assumed Y"])
    rows = engagement_rows(p / "artifacts")
    (row,) = rows
    assert row["outstanding"] == before + 1
    assert row["pending_ratifications"] == 1
    assert row["consent_outcome"] is None


def test_engagement_rows_records_consent_outcome(tmp_path):
    from scripts.engagement_state import main as es_main

    p = _mk_project(tmp_path)
    pack = _open_engagement(p, "eng-d")
    es_main(["--dir", str(pack), "record-consent-outcome", "declined"])
    (row,) = engagement_rows(p / "artifacts")
    assert row["consent_outcome"] == "declined"


def test_engagement_rows_unreadable_state_is_skipped_not_crashed(tmp_path):
    p = _mk_project(tmp_path)
    pack = p / "artifacts" / "broken"
    pack.mkdir(parents=True)
    (pack / "engagement-state.json").write_text("{not json", encoding="utf-8")
    # scan_engagements itself already tolerates this (reports slug/status "invalid"); the
    # extras reader must not crash on top of that.
    rows = engagement_rows(p / "artifacts")
    assert rows and rows[0]["outstanding"] == 0


# ------------------------------------------------------------------ full-parity gate


def test_gate_findings_full_parity_includes_registry_and_orphans(tmp_path):
    """The pre-rewrite dashboard only ever called per-pack check() - registry staleness
    and root-orphan findings were silently invisible even though check_artifacts.py's own
    CLI has always checked them. This pins that the dashboard now matches.

    check_root_orphans grandfathers whatever is at the root on its FIRST snapshot (a
    read-only caller, create_snapshot=False, never takes that snapshot itself - correct,
    it must never invent a grandfather list) - so a file predating any snapshot is never
    flagged. Seed an (empty) snapshot first to simulate "the CLI has already run once",
    matching how this behaves on a real, previously-checked project."""
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    (p / "artifacts" / ".dod-root-allowlist.json").write_text(
        json.dumps({"grandfathered": []}), encoding="utf-8"
    )
    (p / "artifacts" / "stray-orphan.md").write_text("x", encoding="utf-8")
    findings = gate_findings_for(p / "artifacts")
    assert any("ORPHAN-ARTIFACT" in f for f in findings)


def test_gate_findings_flags_archived_open_safeguard(tmp_path):
    p = _mk_project(tmp_path)
    pack = _open_engagement(p, "eng-e")
    (pack / ".archive").write_text("", encoding="utf-8")  # bare marker, never closed
    findings = gate_findings_for(p / "artifacts")
    assert any("ARCHIVED-OPEN" in f for f in findings)


def test_gate_findings_archived_closed_pack_excluded_from_per_pack_scan(tmp_path):
    p = _mk_project(tmp_path)
    from scripts.engagement_state import main as es_main

    _closed_engagement(p, "eng-a")
    assert es_main(["--dir", str(p / "artifacts"), "archive", "eng-a"]) == 0
    findings = gate_findings_for(p / "artifacts")
    assert not any("eng-a" in f and "ARCHIVED-OPEN" not in f for f in findings)


def test_gate_findings_no_artifacts_dir_is_empty(tmp_path):
    assert gate_findings_for(tmp_path / "artifacts") == []


def test_gate_findings_empty_project_passes(tmp_path):
    p = _mk_project(tmp_path)
    assert gate_findings_for(p / "artifacts") == []


# ------------------------------------------------------------------ project-setup facts


def test_read_team_preferences_defaults_when_absent(tmp_path):
    prefs = read_team_preferences(tmp_path)
    assert prefs == {"docx": False, "citations": True}


def test_read_team_preferences_reads_existing(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "team-preferences.json").write_text(
        json.dumps({"extra_formats": ["docx"], "regulatory_citations": False}),
        encoding="utf-8",
    )
    prefs = read_team_preferences(tmp_path)
    assert prefs == {"docx": True, "citations": False}


def test_read_team_preferences_malformed_file_falls_back_to_defaults(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "team-preferences.json").write_text("{not json", encoding="utf-8")
    assert read_team_preferences(tmp_path) == {"docx": False, "citations": True}


def test_read_tool_probe_none_when_never_probed(tmp_path):
    assert read_tool_probe(tmp_path) is None


def test_read_tool_probe_parses_cache(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / ".tool-availability").write_text(
        "=== Review/perf tooling check ===\nChecked: 2026-07-31 09:00\n\n"
        "✅ Installed (3):\n   - ruff (Python lint/style)\n\n"
        "⚠️  Missing (16) - reviews still run but degrade:\n   - mypy\n",
        encoding="utf-8",
    )
    probe = read_tool_probe(tmp_path)
    assert probe == {"installed": 3, "total": 19, "fresh": True}


def test_read_tool_probe_stale_when_old(tmp_path):
    import os
    import time

    claude = tmp_path / ".claude"
    claude.mkdir()
    cache = claude / ".tool-availability"
    cache.write_text("✅ Installed (1):\n⚠️  Missing (1)\n", encoding="utf-8")
    old = time.time() - (8 * 86400)
    os.utime(cache, (old, old))
    probe = read_tool_probe(tmp_path)
    assert probe["fresh"] is False


def test_read_tool_probe_unparsable_content_is_none(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / ".tool-availability").write_text("garbage", encoding="utf-8")
    assert read_tool_probe(tmp_path) is None


def test_hook_wiring_none_for_plugin_mode_install(tmp_path):
    """No hooks/hooks.json + settings.json pair at the project root = not a repo
    checkout - never report a misleading 0/9."""
    assert hook_wiring(tmp_path) is None


def test_hook_wiring_counts_wired_scripts(tmp_path):
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "hooks.json").write_text("{}", encoding="utf-8")
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [{"hooks": [{"command": "... dod_stop_gate.py ..."}]}],
                    "PreToolUse": [{"hooks": [{"command": "... locked_menu_guard.py ..."}]}],
                }
            }
        ),
        encoding="utf-8",
    )
    hw = hook_wiring(tmp_path)
    assert hw["wired"] == 2
    assert hw["total"] == 9


def test_hook_wiring_malformed_settings_fails_soft(tmp_path):
    (tmp_path / "hooks").mkdir()
    (tmp_path / "hooks" / "hooks.json").write_text("{}", encoding="utf-8")
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{not json", encoding="utf-8")
    assert hook_wiring(tmp_path) is None


# ------------------------------------------------------------------ project_summary integration


def test_project_summary_integrates_everything(tmp_path):
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    (p / ".claude").mkdir()
    (p / ".claude" / ".exec-consent").write_text("", encoding="utf-8")
    s = project_summary(p)
    assert len(s["engagements"]) == 1
    assert s["engagements"][0]["slug"] == "eng-a"
    assert s["archived_count"] == 0
    assert s["emails"] == ["engagement-summary-eng-a.txt"]
    assert s["gate_findings"] == []
    assert s["consent_open"] is True
    assert s["map_path"] is None
    assert s["preferences"] == {"docx": False, "citations": True}
    assert s["tool_probe"] is None
    assert s["hook_wiring"] is None


def test_project_summary_counts_archived_separately(tmp_path):
    from scripts.engagement_state import main as es_main

    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    _open_engagement(p, "eng-b")
    assert es_main(["--dir", str(p / "artifacts"), "archive", "eng-a"]) == 0
    s = project_summary(p)
    assert len(s["engagements"]) == 1  # only eng-b, the live one
    assert s["archived_count"] == 1


# ------------------------------------------------------------------ transcripts + discovery
# (unchanged behaviour - pins carried over from the pre-rewrite suite)


def test_parse_transcripts_sums_usage_and_counts_bad_lines(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    (tdir / "s1.jsonl").write_text(
        _usage_line(100, 50, cr=10, cw=5) + "\n" + _usage_line(200, 25) + "\nnot json\n",
        encoding="utf-8",
    )
    stats = parse_transcripts(tdir)
    assert stats["unparsable_files"] == 0
    (s,) = stats["sessions"]
    assert (s["in"], s["out"], s["cache_read"], s["cache_write"]) == (300, 75, 10, 5)
    assert s["bad_lines"] == 1


def test_transcript_slug_mirrors_claude_layout(tmp_path):
    p = tmp_path / "www" / "proj"
    p.mkdir(parents=True)
    d = transcripts_dir_for(p, tmp_path / ".claude")
    assert d.name == str(p.resolve()).replace("/", "-").replace("\\", "-").replace(":", "-")
    assert d.parent == tmp_path / ".claude" / "projects"


def test_plugin_cache_version_fallback(tmp_path):
    cache = tmp_path / ".claude" / "plugins" / "mp" / "team" / ".claude-plugin"
    cache.mkdir(parents=True)
    (cache / "plugin.json").write_text(
        json.dumps({"name": "compliance-surveillance-team", "version": "9.9.9"}),
        encoding="utf-8",
    )
    assert plugin_cache_version(tmp_path / ".claude") == "9.9.9"
    assert plugin_cache_version(tmp_path / "nowhere") is None


@pytest.mark.skipif(sys.platform == "win32", reason="'<' is not a legal Windows filename character")
def test_render_escapes_and_reports(tmp_path):
    p = _mk_project(tmp_path, name="evil<script>alert(1)")
    _closed_engagement(p, "eng-a")
    s = project_summary(p)
    out = render([s], {s["name"]: {"sessions": [], "unparsable_files": 2}}, "2026-07-31")
    assert "<script>alert(1)" not in out
    assert "&lt;script&gt;alert(1)" in out
    assert "2 transcript file(s) could not be read" in out
    assert "PASS" in out


def test_discovery_config_and_fingerprint_and_exclusion(tmp_path):
    from scripts.dashboard import discover_projects

    home = tmp_path / ".claude"
    (home / "projects").mkdir(parents=True)

    cfg_proj = tmp_path / "work-projects" / "estate"
    cfg_proj.mkdir(parents=True)
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {
                "projects": {
                    str(cfg_proj): {"enabledPlugins": ["compliance-surveillance-team@mp"]},
                    str(tmp_path / "plain"): {"allowedTools": []},
                }
            }
        ),
        encoding="utf-8",
    )

    fp_proj = _mk_project(tmp_path, name="fp-proj")
    _closed_engagement(fp_proj, "eng-a")
    tdir = home / "projects" / "slug-fp"
    tdir.mkdir(parents=True)
    (tdir / "s.jsonl").write_text(json.dumps({"cwd": str(fp_proj)}) + "\n", encoding="utf-8")

    plain = tmp_path / "plain"
    plain.mkdir()
    tdir2 = home / "projects" / "slug-plain"
    tdir2.mkdir(parents=True)
    (tdir2 / "s.jsonl").write_text(json.dumps({"cwd": str(plain)}) + "\n", encoding="utf-8")

    found = discover_projects(home)
    bases = {str(d["path"]): d["basis"] for d in found}
    assert bases[str(cfg_proj)] == "config"
    assert bases[str(fp_proj)] == "fingerprint"
    assert str(plain) not in bases


def test_main_end_to_end(tmp_path, capsys):
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    home = tmp_path / ".claude"
    tdir = transcripts_dir_for(p, home)
    tdir.mkdir(parents=True)
    (tdir / "s1.jsonl").write_text(_usage_line(10, 5), encoding="utf-8")
    out = tmp_path / "dash.html"
    rc = main([str(p), "--out", str(out), "--claude-home", str(home)])
    assert rc == 0 and out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "Projects" in text
    assert "eng-a" in text
    assert "10" in text and "5" in text
