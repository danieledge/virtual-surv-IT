"""The engagement budget checkpoint (2026-08-17, assessment recommendation 1).

set-budget records advisory pacing state in engagement-state.json; budget-status prices
this project's session transcripts (dashboard.py's own pricing, cache tiers included)
against the recorded caps and emits a categorical HEADROOM= line the PM states at every
gate. Advisory by design: prompt-only budgets demonstrably fail, so the hard stop stays
the org-side spend limit - this exists so the cap is SEEN coming and the degrade ladder
(light profile, sonnet-for-opus, defer a stage, park until tomorrow) is offered
deliberately instead of the session being hard-stopped mid-review.
"""

from __future__ import annotations

from scripts.engagement_state import load_state, main as es_main


def _init(tmp_path, slug="pack"):
    art = tmp_path / "artifacts"
    assert es_main(["--dir", str(art / slug), "init", "--title", slug, "--slug", slug]) == 0
    return art / slug


def _fake_transcripts(monkeypatch, sessions):
    """Point budget-status at a synthetic parse_transcripts result - the real parser is
    dashboard.py's own concern (tested in test_dashboard.py); here the subject is the
    cap arithmetic and the verdict."""
    import scripts.engagement_state as es

    fake = type(
        "FakeDash",
        (),
        {
            "transcripts_dir_for": staticmethod(lambda project, home: project),
            "parse_transcripts": staticmethod(lambda tdir: {"sessions": sessions}),
        },
    )
    monkeypatch.setattr(es, "_load_dashboard_module", lambda: fake)


def test_set_budget_records_and_renders_state(tmp_path):
    ws = _init(tmp_path)
    assert (
        es_main(["--dir", str(ws), "set-budget", "--daily-usd", "50", "--engagement-usd", "120"])
        == 0
    )
    budget = load_state(ws)["budget"]
    assert budget["daily_usd"] == 50.0
    assert budget["engagement_usd"] == 120.0
    assert budget["set"]


def test_budget_status_without_budget_points_at_set_budget(tmp_path, capsys):
    ws = _init(tmp_path)
    assert es_main(["--dir", str(ws), "budget-status"]) == 0
    assert "set-budget" in capsys.readouterr().out


def test_budget_status_ok_when_well_under_cap(tmp_path, monkeypatch, capsys):
    import datetime as dt

    ws = _init(tmp_path)
    assert es_main(["--dir", str(ws), "set-budget", "--daily-usd", "50"]) == 0
    today = dt.date.today().isoformat()
    _fake_transcripts(monkeypatch, [{"date": today, "cost_usd": 10.0}])
    assert es_main(["--dir", str(ws), "budget-status"]) == 0
    out = capsys.readouterr().out
    assert "DAILY cap=$50.00 spent_today=$10.00" in out
    assert "HEADROOM=ok" in out


def test_budget_status_approaching_at_seventy_percent(tmp_path, monkeypatch, capsys):
    import datetime as dt

    ws = _init(tmp_path)
    assert es_main(["--dir", str(ws), "set-budget", "--daily-usd", "50"]) == 0
    today = dt.date.today().isoformat()
    _fake_transcripts(
        monkeypatch, [{"date": today, "cost_usd": 20.0}, {"date": today, "cost_usd": 15.0}]
    )
    assert es_main(["--dir", str(ws), "budget-status"]) == 0
    assert "HEADROOM=approaching" in capsys.readouterr().out


def test_budget_status_exceeded_and_engagement_ceiling(tmp_path, monkeypatch, capsys):
    import datetime as dt

    ws = _init(tmp_path)
    assert (
        es_main(["--dir", str(ws), "set-budget", "--daily-usd", "50", "--engagement-usd", "60"])
        == 0
    )
    today = dt.date.today().isoformat()
    _fake_transcripts(monkeypatch, [{"date": today, "cost_usd": 65.0}])
    assert es_main(["--dir", str(ws), "budget-status"]) == 0
    out = capsys.readouterr().out
    assert "HEADROOM=exceeded" in out
    assert "ENGAGEMENT ceiling=$60.00" in out


def test_budget_status_fails_open_to_unknown_on_parser_trouble(tmp_path, monkeypatch, capsys):
    """A missing/broken transcript layer must never brick a gate - spend reports unknown,
    the verdict says unknown, exit stays 0."""
    import scripts.engagement_state as es

    ws = _init(tmp_path)
    assert es_main(["--dir", str(ws), "set-budget", "--daily-usd", "50"]) == 0
    monkeypatch.setattr(es, "_load_dashboard_module", lambda: None)
    assert es_main(["--dir", str(ws), "budget-status"]) == 0
    out = capsys.readouterr().out
    assert "spent_today=unknown" in out
    assert "HEADROOM=unknown" in out


def test_budget_survives_a_render_cycle(tmp_path):
    """The budget block must ride the state file through mutate/render cycles untouched -
    a later phase change must not drop it."""
    ws = _init(tmp_path)
    assert es_main(["--dir", str(ws), "set-budget", "--daily-usd", "50"]) == 0
    assert es_main(["--dir", str(ws), "set-phase", "delivery"]) == 0
    assert load_state(ws)["budget"]["daily_usd"] == 50.0
