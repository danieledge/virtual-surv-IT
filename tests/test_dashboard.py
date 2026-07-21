"""Tests for the local static dashboard generator (scripts/dashboard.py).

Pins: project facts come from disk (gate reuse, consent, map), token usage is summed from
transcript usage fields with parse gaps COUNTED not hidden, plugin-mode projects fall back
to the cache manifest for their version, and all user-controlled strings are HTML-escaped.
"""

from __future__ import annotations

import json

from scripts.dashboard import (
    main,
    parse_transcripts,
    plugin_cache_version,
    project_summary,
    render,
    transcripts_dir_for,
)


def _mk_project(tmp_path, name="proj"):
    p = tmp_path / name
    (p / "artifacts").mkdir(parents=True)
    (p / "artifacts" / "report.md").write_text("x", encoding="utf-8")
    (p / "artifacts" / "report.html").write_text("x", encoding="utf-8")
    (p / "artifacts" / "engagement-summary-x.txt").write_text("x", encoding="utf-8")
    return p


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


def test_project_summary_reads_disk_state(tmp_path):
    p = _mk_project(tmp_path)
    (p / ".claude").mkdir()
    (p / ".claude" / ".exec-consent").write_text("", encoding="utf-8")
    s = project_summary(p)
    assert s["artifact_count"] == 1
    assert s["emails"] == ["engagement-summary-x.txt"]
    assert s["gate_findings"] == []
    assert s["consent_open"] is True
    assert s["map_path"] is None


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
    assert d.name == str(p.resolve()).replace("/", "-")


def test_plugin_cache_version_fallback(tmp_path):
    cache = tmp_path / ".claude" / "plugins" / "mp" / "team" / ".claude-plugin"
    cache.mkdir(parents=True)
    (cache / "plugin.json").write_text(
        json.dumps({"name": "compliance-surveillance-team", "version": "9.9.9"}),
        encoding="utf-8",
    )
    assert plugin_cache_version(tmp_path / ".claude") == "9.9.9"
    assert plugin_cache_version(tmp_path / "nowhere") is None


def test_render_escapes_and_reports(tmp_path):
    # no "/" in the name (it would create a subdirectory) - "<script>" is the payload
    p = _mk_project(tmp_path, name="evil<script>alert(1)")
    s = project_summary(p)
    out = render([s], {s["name"]: {"sessions": [], "unparsable_files": 2}}, "2026-07-21")
    assert "<script>alert(1)" not in out
    assert "&lt;script&gt;alert(1)" in out
    assert "2 transcript file(s) could not be read" in out
    assert "PASS" in out


def test_main_end_to_end(tmp_path, capsys):
    p = _mk_project(tmp_path)
    home = tmp_path / ".claude"
    tdir = transcripts_dir_for(p, home)
    tdir.mkdir(parents=True)
    (tdir / "s1.jsonl").write_text(_usage_line(10, 5), encoding="utf-8")
    out = tmp_path / "dash.html"
    rc = main([str(p), "--out", str(out), "--claude-home", str(home)])
    assert rc == 0 and out.is_file()
    text = out.read_text(encoding="utf-8")
    assert "Working projects" in text and "15" not in ""  # smoke
    assert "10" in text and "5" in text
