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
    _active_seconds,
    _cost_by_model_rows,
    _day_span,
    _engagement_cost_rollup,
    _engagement_extras,
    _heatmap_html,
    _humanize_agents,
    _kpi_strip_html,
    _match_engagement,
    _price_usage,
    _roster_bars_html,
    _session_json,
    _team_role_map,
    _timeline_events,
    emit_json,
    engagement_rows,
    gate_findings_for,
    hook_wiring,
    main,
    obligation_coverage,
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


def _usage_line(inp, out, cr=0, cw=0, model=None):
    message = {
        "usage": {
            "input_tokens": inp,
            "output_tokens": out,
            "cache_read_input_tokens": cr,
            "cache_creation_input_tokens": cw,
        }
    }
    if model is not None:
        message["model"] = model
    return json.dumps({"type": "assistant", "message": message})


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
    assert [e.name for e in s["emails"]] == ["engagement-summary-eng-a.txt"]  # list[Path], not str
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


def test_parse_transcripts_prices_a_known_model(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    (tdir / "s1.jsonl").write_text(
        _usage_line(1_000_000, 1_000_000, model="claude-sonnet-5") + "\n", encoding="utf-8"
    )
    stats = parse_transcripts(tdir)
    (s,) = stats["sessions"]
    # 1M in @ $3 + 1M out @ $15 = $18 flat (no cache activity in this line)
    assert s["cost_usd"] == pytest.approx(18.0)
    assert s["cost_partial"] is False


def test_parse_transcripts_flags_partial_cost_for_unpriced_model(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    (tdir / "s1.jsonl").write_text(
        _usage_line(100, 50, model="<synthetic>") + "\n", encoding="utf-8"
    )
    stats = parse_transcripts(tdir)
    (s,) = stats["sessions"]
    assert s["cost_usd"] == 0.0
    assert s["cost_partial"] is True


def test_price_usage_none_for_unknown_or_missing_model():
    usage = {"input_tokens": 100, "output_tokens": 50}
    assert _price_usage(None, usage) is None
    assert _price_usage("claude-nonexistent-9", usage) is None


def test_price_usage_covers_fable_and_mythos():
    """Regression: caught live via real transcript data showing claude-fable-5 tokens
    priced at $0 - the pricing table only had Opus/Sonnet/Haiku on the first pass."""
    usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000}
    assert _price_usage("claude-fable-5", usage) == pytest.approx(60.0)  # $10 + $50
    assert _price_usage("claude-mythos-5", usage) == pytest.approx(60.0)


def test_price_usage_splits_5m_and_1h_cache_write_rates():
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation": {
            "ephemeral_5m_input_tokens": 1_000_000,
            "ephemeral_1h_input_tokens": 1_000_000,
        },
    }
    # Sonnet 5: $3.75/MTok (5m) + $6.00/MTok (1h)
    assert _price_usage("claude-sonnet-5", usage) == pytest.approx(3.75 + 6.00)


def test_parse_transcripts_breaks_down_cost_by_model(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    lines = "\n".join(
        [
            _usage_line(1_000_000, 0, model="claude-sonnet-5"),  # $3.00
            _usage_line(1_000_000, 0, model="claude-haiku-4-5"),  # $1.00
            _usage_line(100, 50, model="<synthetic>"),  # unpriced -> "unknown" bucket... no,
            # model IS present here ("<synthetic>") so it buckets under that literal string,
            # not "unknown" - see the next test for the missing-model case
        ]
    )
    (tdir / "s1.jsonl").write_text(lines + "\n", encoding="utf-8")
    stats = parse_transcripts(tdir)
    (s,) = stats["sessions"]
    by_model = s["cost_by_model"]
    assert set(by_model.keys()) == {"claude-sonnet-5", "claude-haiku-4-5", "<synthetic>"}
    assert by_model["claude-sonnet-5"]["in"] == 1_000_000
    assert by_model["claude-sonnet-5"]["cost_usd"] == pytest.approx(3.00)
    assert by_model["claude-haiku-4-5"]["cost_usd"] == pytest.approx(1.00)
    assert by_model["<synthetic>"]["in"] == 100
    assert by_model["<synthetic>"]["cost_usd"] == 0.0  # unpriced model -> no cost, not a guess
    assert s["cost_usd"] == pytest.approx(4.00)  # only the two priced models contribute
    assert s["cost_partial"] is True


def test_parse_transcripts_missing_model_buckets_as_unknown(tmp_path):
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    (tdir / "s1.jsonl").write_text(_usage_line(10, 5) + "\n", encoding="utf-8")  # no model field
    stats = parse_transcripts(tdir)
    (s,) = stats["sessions"]
    assert set(s["cost_by_model"].keys()) == {"unknown"}
    assert s["cost_by_model"]["unknown"]["in"] == 10


def test_session_json_camel_cases_cost_by_model():
    s = {
        "session": "abc",
        "cost_by_model": {
            "claude-sonnet-5": {"in": 10, "out": 5, "cache_read": 1, "cache_write": 2, "cost_usd": 0.5}
        },
    }
    out = _session_json(s, engagement_slug=None)
    assert out["costByModel"] == {
        "claude-sonnet-5": {"in": 10, "out": 5, "cacheRead": 1, "cacheWrite": 2, "costUsd": 0.5}
    }


def test_cost_by_model_rows_aggregates_across_sessions_and_projects():
    usage_by_project = {
        "proj-a": {
            "sessions": [
                {"cost_by_model": {"claude-sonnet-5": {"in": 100, "out": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 1.0}}},
                {"cost_by_model": {"claude-sonnet-5": {"in": 50, "out": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 0.5}}},
            ]
        },
        "proj-b": {
            "sessions": [
                {"cost_by_model": {"claude-opus-5": {"in": 10, "out": 0, "cache_read": 0, "cache_write": 0, "cost_usd": 5.0}}},
            ]
        },
    }
    rows = _cost_by_model_rows(usage_by_project)
    # sorted by costUsd descending
    assert rows == [
        {"model": "claude-opus-5", "in": 10, "out": 0, "cacheRead": 0, "cacheWrite": 0, "costUsd": 5.0},
        {"model": "claude-sonnet-5", "in": 150, "out": 0, "cacheRead": 0, "cacheWrite": 0, "costUsd": 1.5},
    ]


def test_emit_json_top_level_carries_cost_by_model(tmp_path):
    p = _mk_project(tmp_path)
    s = project_summary(p)
    usage = {
        s["name"]: {
            "sessions": [
                {
                    "session": "abc",
                    "date": "2026-08-08",
                    "in": 100,
                    "out": 0,
                    "cache_read": 0,
                    "cache_write": 0,
                    "bad_lines": 0,
                    "span_seconds": 1.0,
                    "cost_usd": 0.3,
                    "cost_partial": False,
                    "cost_by_model": {
                        "claude-sonnet-5": {
                            "in": 100,
                            "out": 0,
                            "cache_read": 0,
                            "cache_write": 0,
                            "cost_usd": 0.3,
                        }
                    },
                }
            ],
            "unparsable_files": 0,
            "total_seconds": 1.0,
        }
    }
    payload = emit_json([s], usage, "2026-08-08 12:00")
    assert payload["costByModel"] == [
        {"model": "claude-sonnet-5", "in": 100, "out": 0, "cacheRead": 0, "cacheWrite": 0, "costUsd": 0.3}
    ]


# --------------------------------------------------------------- engagement cost-scoping (🧠 inferred)


def _eng(slug, opened, closed=None, log=None, artifacts=None):
    return {"slug": slug, "opened": opened, "closed": closed, "log": log or [], "artifacts": artifacts or []}


def test_match_engagement_falls_inside_open_window():
    engagements = [_eng("eng-a", "2026-08-01", "2026-08-05")]
    assert _match_engagement("2026-08-03", engagements) == "eng-a"


def test_match_engagement_none_before_opened_or_after_closed():
    engagements = [_eng("eng-a", "2026-08-01", "2026-08-05")]
    assert _match_engagement("2026-07-31", engagements) is None
    assert _match_engagement("2026-08-06", engagements) is None


def test_match_engagement_still_open_extends_only_to_last_activity_plus_grace():
    # 2026-08-09: a still-open engagement's window used to extend through "today" unbounded -
    # replaced with a cap at (last known activity + _STILL_OPEN_GRACE_DAYS), see
    # _match_engagement's own docstring for the live incident that motivated this. No log/
    # artifacts here, so "last known activity" falls back to `opened` itself: 2026-08-01 + 3
    # days grace = matches through 2026-08-04, not indefinitely.
    engagements = [_eng("eng-a", "2026-08-01", closed=None)]
    assert _match_engagement("2026-08-04", engagements) == "eng-a"  # exactly at the cap
    assert _match_engagement("2026-08-05", engagements) is None  # one day past the cap
    assert _match_engagement("2026-08-08", engagements) is None  # the old unbounded behavior


def test_match_engagement_still_open_window_uses_latest_log_or_artifact_date_not_just_opened():
    # Real activity well after `opened` (a log line, here) pushes the cap forward with it -
    # the window tracks the engagement's own real evidence, not just its start date.
    engagements = [
        _eng("eng-a", "2026-08-01", closed=None, log=["2026-08-06: still working on this"]),
    ]
    assert _match_engagement("2026-08-09", engagements) == "eng-a"  # 3 days after the 08-06 log line
    assert _match_engagement("2026-08-10", engagements) is None

    artifact_engagements = [
        _eng(
            "eng-b",
            "2026-08-01",
            closed=None,
            artifacts=[{"added": "2026-08-07"}],
        ),
    ]
    assert _match_engagement("2026-08-10", artifact_engagements) == "eng-b"  # 3 days after the artifact
    assert _match_engagement("2026-08-11", artifact_engagements) is None


def test_match_engagement_no_opened_date_never_a_candidate():
    engagements = [_eng("eng-a", opened=None)]
    assert _match_engagement("2026-08-03", engagements) is None


def test_match_engagement_overlap_prefers_most_recently_opened():
    engagements = [_eng("eng-old", "2026-08-01"), _eng("eng-new", "2026-08-02")]
    assert _match_engagement("2026-08-03", engagements) == "eng-new"


def test_match_engagement_no_session_date_is_unattributed():
    assert _match_engagement(None, [_eng("eng-a", "2026-08-01")]) is None


def test_engagement_cost_rollup_sums_matched_sessions_only():
    sessions = [
        {
            "in": 10,
            "out": 5,
            "cacheRead": 1,
            "cacheWrite": 2,
            "costUsd": 0.5,
            "costPartial": False,
            "engagementSlug": "eng-a",
        },
        {
            "in": 100,
            "out": 50,
            "cacheRead": 0,
            "cacheWrite": 0,
            "costUsd": 1.5,
            "costPartial": True,
            "engagementSlug": "eng-a",
        },
        {
            "in": 999,
            "out": 999,
            "cacheRead": 0,
            "cacheWrite": 0,
            "costUsd": 99.0,
            "costPartial": False,
            "engagementSlug": None,  # unattributed - must not leak into eng-a's rollup
        },
    ]
    rollup = _engagement_cost_rollup(sessions, "eng-a")
    assert rollup == {
        "sessionCount": 2,
        "tokensIn": 110,
        "tokensOut": 55,
        "cacheRead": 1,
        "cacheWrite": 2,
        "costUsd": 2.0,
        "costPartial": True,
    }


def test_engagement_cost_rollup_none_when_no_session_matches():
    sessions = [
        {
            "in": 10,
            "out": 5,
            "cacheRead": 0,
            "cacheWrite": 0,
            "costUsd": 0.1,
            "costPartial": False,
            "engagementSlug": None,
        }
    ]
    assert _engagement_cost_rollup(sessions, "eng-a") is None


def test_emit_json_sessions_carry_engagement_slug_and_rollup_attaches(tmp_path):
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    s = project_summary(p)
    (eng_before,) = s["engagements"]
    opened = eng_before["opened"]
    assert opened  # sanity: the fixture pack must have recorded an opened date to match on
    usage = {
        s["name"]: {
            "sessions": [
                {
                    "session": "abc",
                    "date": opened,
                    "in": 10,
                    "out": 5,
                    "cache_read": 0,
                    "cache_write": 0,
                    "bad_lines": 0,
                    "span_seconds": 1.0,
                    "cost_usd": 0.05,
                    "cost_partial": False,
                }
            ],
            "unparsable_files": 0,
            "total_seconds": 1.0,
        }
    }
    payload = emit_json([s], usage, "2026-08-08 12:00")
    (session,) = payload["usageByProject"][s["name"]]["sessions"]
    assert session["engagementSlug"] == "eng-a"
    (eng,) = payload["projects"][0]["engagements"]
    assert eng["costRollup"] == {
        "sessionCount": 1,
        "tokensIn": 10,
        "tokensOut": 5,
        "cacheRead": 0,
        "cacheWrite": 0,
        "costUsd": 0.05,
        "costPartial": False,
    }


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

    # Config-enabled AND actually used - "config" basis requires both, not enablement alone
    # (2026-08-09: enablement-only produced "0 engagements" noise cards for every project the
    # plugin merely happens to be turned on in - confirmed via AskUserQuestion to drop it).
    cfg_proj = tmp_path / "work-projects" / "estate"
    cfg_proj.mkdir(parents=True)
    _closed_engagement(cfg_proj, "eng-cfg")

    # Config-enabled but never actually used - must NOT appear at all.
    cfg_idle = tmp_path / "work-projects" / "idle"
    cfg_idle.mkdir(parents=True)

    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {
                "projects": {
                    str(cfg_proj): {"enabledPlugins": ["compliance-surveillance-team@mp"]},
                    str(cfg_idle): {"enabledPlugins": ["compliance-surveillance-team@mp"]},
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
    assert str(cfg_idle) not in bases


def test_discovery_config_known_but_deleted_project_stays_historical(tmp_path):
    """A config-known project directory that's since been deleted/moved can't be checked for
    a usage trace (the filesystem is gone) - kept rather than dropped, same "can't rule usage
    out" reasoning the fingerprint path already applies to deleted transcript-known dirs."""
    from scripts.dashboard import discover_projects

    home = tmp_path / ".claude"
    (home / "projects").mkdir(parents=True)

    gone = tmp_path / "work-projects" / "moved-away"
    (tmp_path / ".claude.json").write_text(
        json.dumps(
            {"projects": {str(gone): {"enabledPlugins": ["compliance-surveillance-team@mp"]}}}
        ),
        encoding="utf-8",
    )

    found = discover_projects(home)
    bases = {str(d["path"]): d["basis"] for d in found}
    assert bases[str(gone)] == "historical"


def test_fingerprint_no_longer_counts_bare_exec_consent(tmp_path):
    # 2026-08-09: replaced the exec-consent-marker signal with artifacts/engagements.json's own
    # `engagements` list (the user's own suggestion, live finding: budget/email/ha-dash/server/
    # tradingagent all had a granted-but-unused consent marker with zero real engagements).
    from scripts.dashboard import _has_team_fingerprint

    p = _mk_project(tmp_path)
    (p / ".claude").mkdir()
    (p / ".claude" / ".exec-consent").write_text("", encoding="utf-8")
    assert _has_team_fingerprint(p) is False


def test_fingerprint_counts_a_nonempty_engagements_registry(tmp_path):
    # An in-progress engagement (no closing email yet, so the OTHER fingerprint check wouldn't
    # catch it either) is still real usage - artifacts/engagements.json (regenerated by
    # engagement_state.py on every mutation) is ground truth for this, not a heuristic.
    from scripts.dashboard import _has_team_fingerprint

    p = _mk_project(tmp_path)
    _open_engagement(p, "eng-in-progress")
    assert _has_team_fingerprint(p) is True


def test_fingerprint_ignores_an_all_archived_registry(tmp_path):
    # engagements.json regenerates to {"engagements": []} once every real pack is archived
    # (render_registry) - correctly reads as "nothing real happening here right now" rather
    # than "was used once, forever counts".
    from scripts.dashboard import _has_team_fingerprint
    from scripts.engagement_state import main as es_main

    p = _mk_project(tmp_path)
    _open_engagement(p, "eng-to-archive")
    assert es_main(["--dir", str(p / "artifacts"), "archive", "eng-to-archive", "--force"]) == 0
    assert _has_team_fingerprint(p) is False


def test_fingerprint_no_longer_counts_a_bare_closing_email(tmp_path):
    # 2026-08-09 (same session, live finding): a bare engagement-summary-*.txt used to count
    # on its own - not a strong signal (an in-progress engagement legitimately has none yet),
    # and it didn't respect archival status at all: archiving a pack (which correctly empties
    # engagements.json) left the closing-email FILE itself sitting on disk untouched, so this
    # signal alone kept a project "discovered" forever after every engagement in it was
    # archived - the exact live case (virt-survtecb/dashboard-demo) that surfaced this. Dropped
    # entirely; the engagements.json registry check is the real, archive-aware signal for
    # closed engagements now.
    from scripts.dashboard import _has_team_fingerprint
    from scripts.engagement_state import main as es_main

    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    assert es_main(["--dir", str(p / "artifacts"), "archive", "eng-a", "--force"]) == 0
    # The closing email file is still physically on disk (archiving doesn't delete it) - only
    # the registry entry is gone. Confirms the bare file alone no longer counts.
    assert (p / "artifacts" / "eng-a" / "engagement-summary-eng-a.txt").is_file()
    assert _has_team_fingerprint(p) is False


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


# ---------------------------------------------------------------- measured active time (dashboard v2)
#
# _active_seconds is the fix for a live-caught bug: first-to-last timestamp span produced
# "171h 55m" for one real session because Claude Code sessions routinely sit open for hours
# or days between messages (resume-later is normal). These pin the gap-cap behaviour.


def test_active_seconds_sums_gaps_under_cap(tmp_path):
    import datetime as _dt

    base = _dt.datetime(2026, 8, 8, 10, 0, 0)
    ts = [base, base + _dt.timedelta(minutes=5), base + _dt.timedelta(minutes=12)]
    assert _active_seconds(ts) == 12 * 60


def test_active_seconds_excludes_gaps_over_the_idle_cap(tmp_path):
    """The regression case: a session resumed a day later must not count that day as
    active work - only the sub-cap gaps sum."""
    import datetime as _dt

    base = _dt.datetime(2026, 8, 8, 10, 0, 0)
    resumed = base + _dt.timedelta(days=1, hours=3)
    ts = [base, base + _dt.timedelta(minutes=5), resumed, resumed + _dt.timedelta(minutes=2)]
    assert _active_seconds(ts) == (5 + 2) * 60  # NOT the ~27-hour span


def test_active_seconds_zero_for_fewer_than_two_timestamps():
    assert _active_seconds([]) == 0.0
    import datetime as _dt

    assert _active_seconds([_dt.datetime(2026, 8, 8)]) == 0.0


def test_parse_transcripts_reports_active_seconds_not_span(tmp_path):
    """End-to-end: a transcript with a wide idle gap must not inflate span_seconds."""
    tdir = tmp_path / "transcripts"
    tdir.mkdir()
    lines = [
        json.dumps({"timestamp": "2026-08-08T10:00:00Z", **json.loads(_usage_line(10, 5))}),
        json.dumps({"timestamp": "2026-08-08T10:05:00Z"}),
        json.dumps({"timestamp": "2026-08-10T09:00:00Z"}),  # ~47h later - must not count
    ]
    (tdir / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    stats = parse_transcripts(tdir)
    (s,) = stats["sessions"]
    assert s["span_seconds"] == 5 * 60
    assert stats["total_seconds"] == 5 * 60


# --------------------------------------------------------------------------- day span (🧠 inferred)


def test_day_span_closed_engagement():
    assert _day_span("2026-08-01", "2026-08-05") == "4d"


def test_day_span_open_engagement_reads_so_far():
    span = _day_span("2026-08-01", None)
    assert span is not None and span.endswith("d so far")


def test_day_span_missing_or_bad_dates_is_none():
    assert _day_span(None, "2026-08-05") is None
    assert _day_span("not-a-date", None) is None
    assert _day_span("2026-08-01", "not-a-date") is None


# ------------------------------------------------------------------- agent-humanized timeline


def test_team_role_map_parses_name_role_pairs():
    assert _team_role_map(["Mateo (rules-developer)", "Ravi (code-reviewer)"]) == {
        "rules-developer": "Mateo",
        "code-reviewer": "Ravi",
    }
    assert _team_role_map(None) == {}
    assert _team_role_map(["not a valid pair"]) == {}


def test_team_role_map_parses_the_eval_harness_comma_convention():
    # 2026-08-09 live finding: scripts/eval_engage.py writes team entries as "🤖 Name, Role
    # (Team)" - a different, real convention from "Name (role-slug)" above. Before this was
    # handled, "🤖 Ravi, Code Reviewer (Virtual Surveillance IT)" parsed to
    # {"Virtual Surveillance IT": "🤖 Ravi, Code Reviewer"} - neither field useful, and real
    # review-loop handoffs referencing people by slug token ("code-reviewer") could never
    # resolve against it.
    assert _team_role_map(["🤖 Ravi, Code Reviewer (Virtual Surveillance IT)"]) == {
        "code-reviewer": "Ravi",
    }
    assert _team_role_map(["🤖 Morgan, Project Manager (Virtual Surveillance IT)"]) == {
        "project-manager": "Morgan",
    }
    # Same convention works without the leading 🤖 too.
    assert _team_role_map(["Linh, QA Engineer (Virtual Surveillance IT)"]) == {
        "qa-engineer": "Linh",
    }


def test_humanize_agents_resolves_eval_harness_style_roster():
    role_map = _team_role_map(["🤖 Ravi, Code Reviewer (Virtual Surveillance IT)", "🤖 Kenji, Platform Engineer (Virtual Surveillance IT)"])
    out = _humanize_agents("code-reviewer -> platform-engineer: resubmit", role_map)
    assert out == "Ravi (code review) -> Kenji (data pipelines): resubmit"


def test_humanize_agents_uses_engagement_team_names():
    role_map = _team_role_map(["Mateo (rules-developer)", "Ravi (code-reviewer)"])
    out = _humanize_agents("code-reviewer -> rules-developer: resubmit", role_map)
    assert out == "Ravi (code review) -> Mateo (detection rules): resubmit"


def test_humanize_agents_falls_back_to_label_only_when_name_unknown():
    out = _humanize_agents("code-reviewer flagged it", {})
    assert out == "(code review) flagged it"


def test_humanize_agents_leaves_unrelated_text_untouched():
    assert _humanize_agents("no roles mentioned here", {}) == "no roles mentioned here"


def test_timeline_events_ordering_and_review_loop_flag():
    e = {
        "opened": "2026-08-01",
        "closed": "2026-08-05",
        "team": ["Mateo (rules-developer)", "Ravi (code-reviewer)"],
        "artifacts": [{"added": "2026-08-02", "title": "Spec", "status": "final"}],
        "log": [
            "2026-08-03: Mateo drafted v1",
            "2026-08-03 [review-loop]: code-reviewer -> rules-developer: resubmit",
        ],
    }
    events = _timeline_events(e)
    dates = [ev["date"] for ev in events]
    assert dates == sorted(dates)  # chronological
    assert dates[0] == "2026-08-01" and dates[-1] == "2026-08-05"
    loop_events = [ev for ev in events if ev["loop"]]
    assert len(loop_events) == 1
    assert "Ravi (code review)" in loop_events[0]["text"]
    assert not any(ev["loop"] for ev in events if ev is not loop_events[0])


def test_timeline_events_empty_engagement_has_no_events():
    assert _timeline_events({}) == []


# ------------------------------------------------------------------------ engagement extras


def test_engagement_extras_carries_team_artifacts_settings_log(tmp_path):
    pack = _closed_engagement(tmp_path, "eng-x")
    from scripts.engagement_state import main as es_main

    es_main(["--dir", str(pack), "log-note", "note one"])
    es_main(["--dir", str(pack), "log-note", "handback", "--tag", "review-loop"])
    extras = _engagement_extras(pack)
    assert extras["team"] == ["Ana (analysis)"]
    assert len(extras["artifacts"]) == 1
    assert extras["artifacts"][0]["title"] == "Email"
    # set-status closed auto-logs its own close note - so this is "my 2 notes" + that one.
    assert any(entry.endswith(": note one") for entry in extras["log"])
    assert any("[review-loop]: handback" in entry for entry in extras["log"])
    # settings_snapshot: None is valid here (no .claude/team-preferences.json in this
    # fixture's project) - the field just needs to be present and not crash the row.
    assert "settings_snapshot" in extras


def test_engagement_extras_unreadable_state_yields_empty_not_crash(tmp_path):
    pack = tmp_path / "broken"
    pack.mkdir()
    extras = _engagement_extras(pack)
    assert extras == {
        "outstanding": 0,
        "pending_ratifications": 0,
        "consent_outcome": None,
        "team": [],
        "artifacts": [],
        "settings_snapshot": None,
        "log": [],
    }


# ------------------------------------------------------------------------------------ KPI strip


def test_kpi_strip_counts_engagements_and_obligations(tmp_path):
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    _open_engagement(p, "eng-b")
    s = project_summary(p)
    html_out = _kpi_strip_html([s], [{"citation": "MAR Art.12(1)(a)", "count": 1, "verified": True}])
    assert '<div class="kpi-value">2</div>' in html_out  # 2 engagements
    assert '<div class="kpi-value">1</div>' in html_out  # 1 obligation cited


def test_kpi_strip_empty_portfolio_does_not_crash():
    out = _kpi_strip_html([], [])
    assert "kpi-strip" in out


# ------------------------------------------------------------------------ obligation coverage


def test_obligation_coverage_reuses_check_citations_matcher(tmp_path):
    p = _mk_project(tmp_path)
    pack = p / "artifacts" / "eng-a"
    from scripts.engagement_state import main as es_main

    assert es_main(["--dir", str(pack), "init", "--title", "Eng A", "--slug", "eng-a"]) == 0
    (pack / "spec.md").write_text(
        "Serves MAR Art.12(1)(a) (spoofing) and a made-up cite XYZ-999.\n", encoding="utf-8"
    )
    es_main(["--dir", str(pack), "add-artifact", "spec.md", "--title", "Spec"])

    s = project_summary(p)
    rows = obligation_coverage([s])
    by_citation = {r["citation"]: r for r in rows}
    assert "Art.12(1)(a)" in by_citation
    assert by_citation["Art.12(1)(a)"]["verified"] is True


def test_obligation_coverage_sources_dedupe_within_one_engagement(tmp_path):
    """Two artifacts in the SAME engagement citing the same obligation must produce ONE
    source entry, not two - count still reflects both citations, but 'which engagement cited
    this' is a set, not a per-citation log."""
    p = _mk_project(tmp_path)
    pack = p / "artifacts" / "eng-a"
    from scripts.engagement_state import main as es_main

    assert es_main(["--dir", str(pack), "init", "--title", "Eng A", "--slug", "eng-a"]) == 0
    (pack / "spec.md").write_text("Serves MAR Art.12(1)(a) (spoofing).\n", encoding="utf-8")
    (pack / "spec2.md").write_text("Also MAR Art.12(1)(a) here.\n", encoding="utf-8")
    es_main(["--dir", str(pack), "add-artifact", "spec.md", "--title", "Spec"])
    es_main(["--dir", str(pack), "add-artifact", "spec2.md", "--title", "Spec2"])

    s = project_summary(p)
    rows = obligation_coverage([s])
    (row,) = rows
    assert row["count"] == 2
    assert row["sources"] == [{"project": "proj", "slug": "eng-a", "title": "Eng A"}]


def test_obligation_coverage_empty_portfolio_is_empty_list():
    assert obligation_coverage([]) == []


# ------------------------------------------------------------------------- roster / heatmap smoke


def test_roster_bars_html_tallies_team_across_engagements(tmp_path):
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    s = project_summary(p)
    out = _roster_bars_html([s])
    assert "Ana (analysis)" in out
    assert "bar-row" in out


def test_roster_bars_html_no_team_yet():
    out = _roster_bars_html([{"engagements": []}])
    assert "No team attributions" in out


def test_heatmap_html_renders_cells_for_dated_activity():
    out = _heatmap_html({"2026-08-08": 3, "2026-08-07": 1})
    assert "heat-2" in out or "heat-3" in out  # 3 events -> level 2 (2 <= c <= 3)
    assert "heat-1" in out  # 1 event -> level 1


def test_heatmap_html_no_activity():
    out = _heatmap_html({})
    assert "No dated activity" in out


# ------------------------------------------------------------------------- full render smoke


def test_render_includes_dashboard_v2_sections(tmp_path):
    p = _mk_project(tmp_path)
    pack = _closed_engagement(p, "eng-a")
    from scripts.engagement_state import main as es_main

    es_main(["--dir", str(pack), "log-note", "handback", "--tag", "review-loop"])
    s = project_summary(p)
    out = render([s], {}, "2026-08-08")
    for marker in (
        "kpi-strip",
        "Portfolio",
        "Roster involvement",
        "Obligation coverage",
        "table-wrap",
        "class='timeline'",
    ):
        assert marker in out, f"missing {marker!r} from rendered page"


# --------------------------------------------------------------------------- emit_json (dashboard-ui)
#
# dashboard-ui/src/lib/types.ts mirrors this shape by hand (no schema generator) - these tests
# pin the exact camelCase contract so a drift is caught here, in Python, not as a silent
# runtime `undefined` somewhere in the React tree.


def test_emit_json_top_level_shape():
    payload = emit_json([], {}, "2026-08-08 12:00")
    assert set(payload.keys()) == {
        "generated",
        "roleLabels",
        "projects",
        "usageByProject",
        "costByModel",
        "obligations",
    }
    assert payload["generated"] == "2026-08-08 12:00"
    assert payload["projects"] == []
    assert payload["usageByProject"] == {}
    assert payload["costByModel"] == []
    assert payload["obligations"] == []
    assert payload["roleLabels"]["rules-developer"] == "detection rules"


def test_emit_json_engagement_is_camel_cased_and_complete(tmp_path):
    p = _mk_project(tmp_path)
    pack = _closed_engagement(p, "eng-a")
    from scripts.engagement_state import main as es_main

    es_main(["--dir", str(pack), "log-note", "handback", "--tag", "review-loop"])
    s = project_summary(p)
    payload = emit_json([s], {}, "2026-08-08 12:00")
    (proj,) = payload["projects"]
    assert proj["name"] == s["name"]
    assert proj["path"] == str(s["path"])  # Path -> str at the JSON boundary
    (eng,) = proj["engagements"]
    assert set(eng.keys()) == {
        "slug",
        "dir",
        "title",
        "status",
        "profile",
        "opened",
        "closed",
        "outstanding",
        "pendingRatifications",
        "consentOutcome",
        "team",
        "artifacts",
        "settingsSnapshot",
        "log",
        "costRollup",
    }
    assert eng["slug"] == "eng-a"
    assert eng["team"] == ["Ana (analysis)"]
    assert any(a["title"] == "Email" for a in eng["artifacts"])
    assert any("[review-loop]" in entry for entry in eng["log"])
    for art in eng["artifacts"]:
        assert set(art.keys()) == {"path", "absPath", "title", "status", "added"}
        assert art["absPath"] == str(pack / art["path"])  # resolves against the pack dir


def test_emit_json_flat_pack_artifact_links_resolve_to_artifacts_root(tmp_path):
    """A legacy flat pack (dir is None/"(flat)") must link into artifacts/ itself, not a
    nonexistent artifacts/None/ or artifacts/(flat)/ subdirectory."""
    p = _mk_project(tmp_path)
    from scripts.engagement_state import main as es_main

    flat = p / "artifacts"
    assert es_main(["--dir", str(flat), "init", "--title", "Flat", "--slug", "flat"]) == 0
    (flat / "spec.md").write_text("spec", encoding="utf-8")
    es_main(["--dir", str(flat), "add-artifact", "spec.md", "--title", "Spec"])
    s = project_summary(p)
    payload = emit_json([s], {}, "2026-08-08 12:00")
    (eng,) = payload["projects"][0]["engagements"]
    (art,) = eng["artifacts"]
    assert art["absPath"] == str(flat / "spec.md")


def test_emit_json_emails_carry_name_and_absolute_path(tmp_path):
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    s = project_summary(p)
    payload = emit_json([s], {}, "2026-08-08 12:00")
    (proj,) = payload["projects"]
    (email,) = proj["emails"]
    assert set(email.keys()) == {"name", "absPath"}
    assert email["name"] == "engagement-summary-eng-a.txt"
    assert email["absPath"] == str(p / "artifacts" / "eng-a" / "engagement-summary-eng-a.txt")


def test_emit_json_is_actually_json_serializable(tmp_path):
    """The real failure mode this guards against: project_summary()'s `path`/`map_path` are
    Path objects, not strings - json.dumps must not be handed one directly."""
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    s = project_summary(p)
    payload = emit_json([s], {}, "2026-08-08 12:00")
    json.dumps(payload)  # raises TypeError if anything non-serializable slipped through


def test_emit_json_usage_by_project_is_camel_cased():
    usage = {
        "proj": {
            "sessions": [
                {
                    "session": "abc123",
                    "date": "2026-08-08",
                    "in": 10,
                    "out": 5,
                    "cache_read": 1,
                    "cache_write": 2,
                    "bad_lines": 0,
                    "span_seconds": 300.0,
                    "cost_usd": 0.0021,
                    "cost_partial": True,
                }
            ],
            "unparsable_files": 1,
            "total_seconds": 300.0,
        }
    }
    payload = emit_json([], usage, "2026-08-08 12:00")
    stats = payload["usageByProject"]["proj"]
    assert stats["unparsableFiles"] == 1
    assert stats["totalSeconds"] == 300.0
    (session,) = stats["sessions"]
    assert session == {
        "session": "abc123",
        "date": "2026-08-08",
        "in": 10,
        "out": 5,
        "cacheRead": 1,
        "cacheWrite": 2,
        "badLines": 0,
        "spanSeconds": 300.0,
        "costUsd": 0.0021,
        "costPartial": True,
        "engagementSlug": None,
        "costByModel": {},
    }


def test_emit_json_obligations_precomputed_portfolio_wide(tmp_path):
    p = _mk_project(tmp_path)
    pack = p / "artifacts" / "eng-a"
    from scripts.engagement_state import main as es_main

    assert es_main(["--dir", str(pack), "init", "--title", "Eng A", "--slug", "eng-a"]) == 0
    (pack / "spec.md").write_text("Serves MAR Art.12(1)(a) (spoofing).\n", encoding="utf-8")
    es_main(["--dir", str(pack), "add-artifact", "spec.md", "--title", "Spec"])
    s = project_summary(p)
    payload = emit_json([s], {}, "2026-08-08 12:00")
    assert payload["obligations"] == [
        {
            "citation": "Art.12(1)(a)",
            "count": 1,
            "verified": True,
            "sources": [{"project": "proj", "slug": "eng-a", "title": "Eng A"}],
        }
    ]


def test_json_cli_flag_writes_data_not_html(tmp_path, monkeypatch):
    p = _mk_project(tmp_path)
    _closed_engagement(p, "eng-a")
    home = tmp_path / ".claude"
    out = tmp_path / "data.json"
    default_html = tmp_path / "dashboard.html"
    monkeypatch.chdir(tmp_path)  # --out's relative default resolves against cwd
    rc = main([str(p), "--json", str(out), "--claude-home", str(home)])
    assert rc == 0 and out.is_file()
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["projects"][0]["engagements"][0]["slug"] == "eng-a"
    # --json wins: --out's own default ("dashboard.html") must NOT also get written.
    assert not default_html.exists()
