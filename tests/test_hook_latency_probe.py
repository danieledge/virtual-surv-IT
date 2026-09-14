"""scripts/hook_latency_probe.py - the "why are Bash/Read calls slow?" diagnostic.

Every subprocess the probe would spawn is replaced by a fake box whose clock advances by a
cost chosen per layer, so the decomposition, the attribution arithmetic (layers add up to the
end-to-end total), the verdict ranking, the environment facts and the JSON shape are all
covered on a fast Linux runner with no slow environment anywhere near it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import hook_latency_probe as hlp

# The interpreter the fake box "runs" and the one written into the fake interpreter cache: the
# probe checks that a cached absolute path exists, so it has to be a real file on every CI leg
# (Windows included; a fixed /usr/bin/python3 read as "does not resolve" there).
INTERP = sys.executable
SH = "/bin/sh"


def _classify(argv: list) -> str:
    """Which layer a fake spawn stands for, from the argv the probe built."""
    joined = " ".join(str(a) for a in argv)
    if len(argv) > 1 and str(argv[1]).endswith("run-guard.sh"):
        return "e2e"
    if argv[0] == INTERP:
        if argv[-1] == "pass":
            return "python_cold_start"
        if "import json, os, socket" in joined:
            return "client_import_raw"
        if "importlib.util" in joined:
            return "dispatcher_imports_raw"
        if str(argv[-1]).endswith("bash_hook_dispatcher.py"):
            return "dispatcher_run_raw"
        return "python_other"
    if argv[0] == SH and len(argv) > 2 and argv[1] == "-c":
        script = argv[2]
        if script == ":":
            return "sh_startup"
        if "MSYSTEM" in script:
            return "env_probe"
        if "read -r c" in script:
            return "interp_resolution"
        if "cat" in script:
            return "interp_resolution"
        if "for i in" in script:
            return "interp_resolution_cold"
        if "mkdir" in script:
            return "lock_cycle"
    return "other"


class FakeBox:
    """A machine where each layer costs a chosen number of milliseconds, deterministically.
    The probe's clock is this object's clock, so elapsed time is exactly the cost."""

    def __init__(self, costs: dict, e2e_rc: int = 0, first_penalty: dict | None = None):
        self.costs = costs
        self.e2e_rc = e2e_rc
        self.first_penalty = first_penalty or {}
        self.now_ms = 0.0
        self.calls: list = []

    def monotonic(self) -> float:
        return self.now_ms / 1000.0

    def run(self, argv, **kwargs):
        layer = _classify(list(argv))
        cost = self.costs.get(layer, 1.0)
        if layer in self.first_penalty and layer not in self.calls:
            cost += self.first_penalty[layer]
        self.calls.append(layer)
        self.now_ms += cost
        rc = self.e2e_rc if layer == "e2e" else 0
        return SimpleNamespace(returncode=rc, stdout="", stderr="")


def _layout(tmp_path: Path, prefs: str | None = '{"guard_daemon": true}') -> Path:
    root = tmp_path / "proj"
    (root / ".claude" / "hooks").mkdir(parents=True)
    (root / ".claude" / "hooks" / "run-guard.sh").write_text(
        "#!/bin/sh\nexit 0\n", encoding="utf-8"
    )
    (root / "scripts").mkdir()
    (root / "scripts" / "bash_hook_dispatcher.py").write_text("", encoding="utf-8")
    (root / "README.md").write_text("x", encoding="utf-8")
    (root / ".claude" / ".guard-interpreter").write_text(INTERP, encoding="utf-8")
    if prefs is not None:
        (root / ".claude" / "team-preferences.json").write_text(prefs, encoding="utf-8")
    return root


def _reach(reachable: bool, roundtrip=4.0, failure=2.0, backoff=False):
    def fn(_plugin, _project, _payload):
        return {
            "port_file_present": reachable,
            "start_backoff_marker_present": backoff,
            "reachable": reachable,
            "roundtrip_samples_ms": [roundtrip] * 5 if reachable else [],
            "connect_failure_samples_ms": [] if reachable else [failure] * 5,
        }

    return fn


def _probe(
    monkeypatch,
    tmp_path,
    box: FakeBox,
    reachable=True,
    prefs='{"guard_daemon": true}',
    runs=8,
    fanout=3,
    backoff=False,
):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))  # no real installer.json
    monkeypatch.delenv("CLAUDE_CODE_GIT_BASH_PATH", raising=False)
    monkeypatch.setattr(hlp.time, "monotonic", box.monotonic)
    root = _layout(tmp_path, prefs)
    return hlp.Probe(
        root,
        root,
        runs=runs,
        fanout=fanout,
        runner=box.run,
        interpreter=INTERP,
        sh_path=SH,
        reachability_fn=_reach(reachable, backoff=backoff),
    )


# A slow corporate box on the daemon route: e2e must equal the sum of what one call does.
DAEMON_COSTS = {
    "e2e": 700.0,
    "sh_startup": 400.0,
    "interp_resolution": 410.0,  # sh + 10ms of read/command -v
    "python_cold_start": 200.0,
    "client_import_raw": 230.0,  # python + 30ms of imports
    "dispatcher_imports_raw": 300.0,
    "dispatcher_run_raw": 350.0,
    "interp_resolution_cold": 650.0,
    "lock_cycle": 460.0,
}


# ------------------------------------------------------------------ statistics


def test_statistics_helpers():
    assert hlp.median([3, 1, 2]) == 2
    assert hlp.median([1, 2, 3, 4]) == 2.5
    assert hlp.median([None, None]) == 0.0
    assert hlp.percentile([10, 20, 30, 40, 50, 60, 70, 80, 90, 100], 90) == 90
    assert hlp.percentile([5], 90) == 5
    # steady drops the single slowest sample once there are four or more
    assert hlp.steady([10, 10, 10, 1000]) == 10
    assert hlp.steady([10, 1000, 10]) == 10
    s = hlp.summarise([10.0, None, 30.0, 20.0, 500.0])
    assert s["n"] == 5 and s["failed"] == 1
    assert s["p50_ms"] == 25.0 and s["max_ms"] == 500.0 and s["first_ms"] == 10.0
    assert s["steady_ms"] == 20.0
    assert s["samples_ms"] == [10.0, None, 30.0, 20.0, 500.0]


def test_warm_vs_cold_names_a_first_spawn_penalty_and_a_flat_series():
    penalty = hlp.warm_vs_cold([900.0, 100.0, 110.0, 105.0, 100.0])
    assert penalty["verdict"] == "first-spawn-penalty"
    assert penalty["first_ms"] == 900.0 and penalty["ratio"] >= 8
    flat = hlp.warm_vs_cold([100.0, 100.0, 110.0, 105.0, 100.0])
    assert flat["verdict"] == "flat"
    assert hlp.warm_vs_cold([1.0, 2.0])["verdict"] == "insufficient"
    # small absolute numbers never count as a penalty even when the ratio is high
    assert hlp.warm_vs_cold([20.0, 2.0, 2.0, 2.0])["verdict"] == "flat"


# ------------------------------------------------------------------ environment facts


def test_daemon_preference_follows_the_launcher_precedence(tmp_path):
    root = tmp_path / "p"
    (root / ".claude").mkdir(parents=True)
    installer = tmp_path / "installer.json"
    # default on
    pref = hlp.daemon_preference(root, installer)
    assert pref["enabled"] is True and "default" in pref["source"]
    # machine default off
    installer.write_text('{"default_guard_daemon": false}', encoding="utf-8")
    assert hlp.daemon_preference(root, installer)["enabled"] is False
    # the project wins in both directions, whitespace and line breaks tolerated
    prefs = root / ".claude" / "team-preferences.json"
    prefs.write_text('{\n  "guard_daemon" :\n true\n}', encoding="utf-8")
    pref = hlp.daemon_preference(root, installer)
    assert pref["enabled"] is True and pref["prefs_value"] is True
    prefs.write_text('{"other_guard_daemon": false, "guard_daemon": false}', encoding="utf-8")
    installer.unlink()
    pref = hlp.daemon_preference(root, installer)
    assert pref["enabled"] is False and pref["prefs_value"] is False


def test_route_for():
    assert hlp.route_for(False, True) == hlp.ROUTE_COLD
    assert hlp.route_for(True, True) == hlp.ROUTE_DAEMON
    assert hlp.route_for(True, False) == hlp.ROUTE_DAEMON_UNREACHABLE


def test_resolve_sh_honours_the_git_bash_override(tmp_path, monkeypatch):
    sh = tmp_path / "sh.exe"
    sh.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(sh))
    assert hlp.resolve_sh() == str(sh)
    bash = tmp_path / "bash.exe"
    bash.write_text("", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(bash))
    assert hlp.resolve_sh() == str(sh)  # sibling sh.exe wins over the bash.exe itself
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", str(tmp_path))
    assert hlp.resolve_sh() == str(sh)


def test_is_git_bash_inference():
    assert hlp._is_git_bash(r"C:\Program Files\Git\bin\sh.exe", "") is True
    assert hlp._is_git_bash("/usr/bin/sh", "MINGW64\nmsys") is True
    assert hlp._is_git_bash(None, "") is None
    assert hlp._is_git_bash("/usr/bin/sh", "\nlinux-gnu\n5.2") is False


def test_gather_environment_tags_every_fact(monkeypatch, tmp_path):
    box = FakeBox(DAEMON_COSTS)
    probe = _probe(monkeypatch, tmp_path, box)
    monkeypatch.setenv("CLAUDE_CODE_GIT_BASH_PATH", r"C:\Git\bin\bash.exe")
    facts = hlp.gather_environment(
        probe.plugin_root, probe.project_root, SH, INTERP, runner=box.run
    )
    by_name = {f["name"]: f for f in facts}
    assert set(f["tag"] for f in facts) <= {"observed", "inferred"}
    for name in (
        "os",
        "interpreter_cache_present",
        "interpreter_how_resolved",
        "sh_path",
        "sh_is_git_bash",
        "CLAUDE_CODE_GIT_BASH_PATH",
        "guard_daemon_enabled",
        "av_endpoint_hints",
    ):
        assert name in by_name, name
    assert by_name["interpreter_cache_present"]["value"] is True
    assert by_name["interpreter_how_resolved"]["value"] == "cache hit"
    assert by_name["guard_daemon_enabled"]["value"] is True
    assert by_name["guard_daemon_enabled"]["tag"] == "observed"
    assert by_name["CLAUDE_CODE_GIT_BASH_PATH"]["value"] == r"C:\Git\bin\bash.exe"
    assert by_name["sh_is_git_bash"]["tag"] == "inferred"
    assert by_name["av_endpoint_hints"]["tag"] == "inferred"


def test_gather_environment_reports_a_missing_cache(monkeypatch, tmp_path):
    box = FakeBox(DAEMON_COSTS)
    probe = _probe(monkeypatch, tmp_path, box)
    (probe.project_root / ".claude" / ".guard-interpreter").unlink()
    facts = hlp.gather_environment(
        probe.plugin_root, probe.project_root, SH, INTERP, runner=box.run
    )
    by_name = {f["name"]: f for f in facts}
    assert by_name["interpreter_cache_present"]["value"] is False
    assert "no cache" in by_name["interpreter_how_resolved"]["value"]


def test_payload_is_benign_with_a_fresh_session_id(tmp_path):
    root = _layout(tmp_path)
    a = json.loads(hlp._payload(root, "Read"))
    b = json.loads(hlp._payload(root, "Bash"))
    assert a["tool_name"] == "Read" and a["tool_input"]["file_path"].endswith("README.md")
    assert b["tool_name"] == "Bash" and b["tool_input"]["command"] == "true"
    assert a["session_id"] != b["session_id"]
    assert a["session_id"].startswith("probe-")


# ------------------------------------------------------------------ attribution arithmetic


def _raw(costs: dict, n=8) -> dict:
    raw = {k: [v] * n for k, v in costs.items() if k != "e2e"}
    raw["daemon_roundtrip"] = [4.0] * 5
    raw["connect_failure"] = [2.0] * 5
    return raw


def test_attribute_daemon_route_layers_sum_to_the_total():
    att = hlp.attribute(hlp.ROUTE_DAEMON, _raw(DAEMON_COSTS), DAEMON_COSTS["e2e"])
    layers = {item["layer"]: item["ms"] for item in att["layers"]}
    assert layers["sh_startup"] == 400.0
    assert layers["interp_resolution"] == 10.0  # minus the sh baseline
    assert layers["python_cold_start"] == 200.0
    assert layers["client_import"] == 30.0  # minus the python baseline
    assert layers["daemon_roundtrip"] == 4.0
    assert "lock_cycle" not in layers and "dispatcher_imports" not in layers
    assert att["attributed_ms"] == 644.0
    assert att["residual_ms"] == 56.0
    assert layers["unattributed"] == 56.0
    assert att["sums_within_tolerance"] is True
    assert abs(sum(item["share_pct"] for item in att["layers"]) - 100.0) < 0.5
    alt = att["alternatives"]
    assert alt["daemon_route_ms"] == 644.0
    assert alt["cold_route_ms"] == 400 + 10 + 60 + 200 + 100 + 50
    assert alt["daemon_unreachable_route_ms"] == 400 + 10 + 200 + 30 + 2 + 200 + 100 + 50


def test_attribute_cold_route_includes_lock_imports_and_logic():
    att = hlp.attribute(hlp.ROUTE_COLD, _raw(DAEMON_COSTS), 830.0)
    layers = {item["layer"]: item["ms"] for item in att["layers"]}
    assert layers["lock_cycle"] == 60.0
    assert layers["dispatcher_imports"] == 100.0
    assert layers["guard_logic"] == 50.0
    assert "daemon_roundtrip" not in layers
    assert att["attributed_ms"] == 820.0
    assert att["sums_within_tolerance"] is True


def test_attribute_unreachable_route_counts_two_python_starts():
    att = hlp.attribute(hlp.ROUTE_DAEMON_UNREACHABLE, _raw(DAEMON_COSTS), 1000.0)
    names = [item["layer"] for item in att["layers"]]
    assert names.count("python_cold_start") == 1 and "python_cold_start_fallback" in names
    assert "connect_failure" in names and "dispatcher_imports" in names


def test_attribute_clamps_negative_derivations_and_flags_a_bad_sum():
    costs = dict(DAEMON_COSTS)
    costs["client_import_raw"] = 150.0  # faster than the python baseline: noise, not a saving
    att = hlp.attribute(hlp.ROUTE_DAEMON, _raw(costs), 3000.0)
    layers = {item["layer"]: item["ms"] for item in att["layers"]}
    assert layers["client_import"] == 0.0
    assert att["sums_within_tolerance"] is False
    assert layers["unattributed"] > 2000


def test_attribute_without_a_cache_uses_the_cold_resolution_layer():
    raw = _raw(DAEMON_COSTS)
    del raw["interp_resolution"]
    att = hlp.attribute(hlp.ROUTE_DAEMON, raw, 900.0)
    layers = {item["layer"]: item["ms"] for item in att["layers"]}
    assert layers["interp_resolution_cold"] == 250.0


# ------------------------------------------------------------------ verdict ranking


@pytest.mark.parametrize(
    "slow_layer, expected_top",
    [
        ("sh_startup", "sh_startup"),
        ("python_cold_start", "python_cold_start"),
        ("client_import_raw", "client_import"),
        ("e2e", "unattributed"),
    ],
)
def test_verdict_ranks_the_dominant_layer_first(slow_layer, expected_top):
    costs = {
        "e2e": 200.0,
        "sh_startup": 30.0,
        "interp_resolution": 35.0,
        "python_cold_start": 60.0,
        "client_import_raw": 70.0,
        "dispatcher_imports_raw": 90.0,
        "dispatcher_run_raw": 100.0,
        "lock_cycle": 40.0,
    }
    if slow_layer == "e2e":
        costs["e2e"] = 3000.0  # nothing measured explains it: AV per-spawn shape
    else:
        costs[slow_layer] += 2000.0
        if slow_layer == "sh_startup":
            costs["interp_resolution"] += 2000.0
        if slow_layer == "python_cold_start":
            costs["client_import_raw"] += 2000.0
        costs["e2e"] += 2000.0
    att = hlp.attribute(hlp.ROUTE_DAEMON, _raw(costs), costs["e2e"])
    facts = [
        {"name": "os", "value": "Windows-10", "tag": "observed"},
        {"name": "sh_is_git_bash", "value": True, "tag": "inferred"},
    ]
    lines = hlp.verdict(att, facts, {"reachable": True}, costs["e2e"], {"verdict": "flat"})
    assert lines[0]["rank"] == 1
    assert lines[0]["layer"] == expected_top
    assert lines[0]["share_pct"] > 50
    assert lines[0]["remediation"]


def test_verdict_remediations_point_at_the_existing_fixes():
    facts = {"sh_is_git_bash": True, "os": "Windows-10", "CLAUDE_CODE_GIT_BASH_PATH": None}
    sh_fix = hlp._remediation("sh_startup", hlp.ROUTE_DAEMON, facts, {})
    assert "Advanced menu #9" in sh_fix and "core.fscache" in sh_fix
    assert "CLAUDE_CODE_GIT_BASH_PATH" in sh_fix
    facts["CLAUDE_CODE_GIT_BASH_PATH"] = r"C:\Git\bin\sh.exe"
    assert "CLAUDE_CODE_GIT_BASH_PATH" not in hlp._remediation(
        "sh_startup", hlp.ROUTE_DAEMON, facts, {}
    )
    cold_imports = hlp._remediation("dispatcher_imports", hlp.ROUTE_COLD, facts, {})
    assert "guard_daemon" in cold_imports
    unreachable = hlp._remediation("dispatcher_imports", hlp.ROUTE_DAEMON_UNREACHABLE, facts, {})
    assert "option 7" in unreachable
    assert "option 7" in hlp._remediation(
        "python_cold_start_fallback", hlp.ROUTE_DAEMON_UNREACHABLE, facts, {}
    )
    assert "guard_daemon" in hlp._remediation("lock_cycle", hlp.ROUTE_COLD, facts, {})
    assert "AV" in hlp._remediation("unattributed", hlp.ROUTE_DAEMON, facts, {})


def test_verdict_leads_with_the_route_when_the_daemon_is_enabled_but_unreachable():
    att = hlp.attribute(hlp.ROUTE_DAEMON_UNREACHABLE, _raw(DAEMON_COSTS), 1000.0)
    facts = [{"name": "guard_daemon_enabled", "value": True, "tag": "observed"}]
    lines = hlp.verdict(
        att,
        facts,
        {"reachable": False, "start_backoff_marker_present": True},
        1000.0,
        {"verdict": "flat"},
    )
    assert lines[0]["layer"] == "route"
    assert "option 7" in lines[0]["remediation"]
    assert lines[1]["layer"] == "sh_startup"  # the biggest measured layer follows


def test_verdict_adds_the_daemon_off_and_first_spawn_lines():
    att = hlp.attribute(hlp.ROUTE_COLD, _raw(DAEMON_COSTS), 830.0)
    facts = [{"name": "guard_daemon_enabled", "value": False, "tag": "observed"}]
    lines = hlp.verdict(
        att,
        facts,
        {"reachable": False},
        830.0,
        {"verdict": "first-spawn-penalty", "first_ms": 2500.0, "steady_ms": 800.0},
    )
    layers = [line["layer"] for line in lines]
    assert "route" in layers and "warm_vs_cold" in layers
    route_line = next(line for line in lines if line["layer"] == "route")
    assert '"guard_daemon": true' in route_line["remediation"]


# ------------------------------------------------------------------ the whole report


def test_build_report_reproduces_decomposes_and_serialises(monkeypatch, tmp_path):
    box = FakeBox(DAEMON_COSTS)
    probe = _probe(monkeypatch, tmp_path, box, runs=8, fanout=3)
    report = hlp.build_report(probe)

    rep = report["reproduce"]
    assert rep["n"] == 8 and rep["failed"] == 0
    assert rep["p50_ms"] == 700.0 and rep["p90_ms"] == 700.0 and rep["max_ms"] == 700.0
    assert rep["flavours"] == ["Read", "Bash"] * 4
    assert rep["by_flavour_p50_ms"] == {"Read": 700.0, "Bash": 700.0}
    assert rep["exit_codes"] == [0] * 8
    assert report["fanout"]["concurrency"] == 3 and report["fanout"]["n"] == 3

    att = report["attribution"]
    assert att["route"] == hlp.ROUTE_DAEMON
    assert att["end_to_end_ms"] == 700.0
    assert att["sums_within_tolerance"] is True
    assert report["verdict"][0]["layer"] == "sh_startup"
    assert report["verdict"][0]["rank"] == 1

    # every raw layer carries its samples, so the root cause can be checked off the box
    for key in (
        "sh_startup",
        "python_cold_start",
        "interp_resolution",
        "lock_cycle",
        "dispatcher_imports_raw",
        "dispatcher_run_raw",
        "client_import_raw",
        "interp_resolution_cold",
    ):
        assert key in report["layers_raw"], key
        assert len(report["layers_raw"][key]["samples_ms"]) >= 3
        assert "warm_vs_cold" in report["layers_raw"][key]
    assert report["layers_raw"]["python_cold_start"]["samples_ms"] == [200.0] * 8

    names = {f["name"] for f in report["environment"]}
    assert {
        "os",
        "sh_path",
        "guard_daemon_enabled",
        "interpreter_cache_present",
        "warm_up_call_ms",
    } <= names
    text = json.dumps(report)  # serialisable as-is
    assert "probe_version" in text
    assert report["notes"] == []

    console = hlp.render_console(report)
    for heading in ("1. reproduce", "2. environment", "3. decompose", "4. verdict"):
        assert heading in console
    assert "p50 700ms" in console
    assert "sh startup" in console
    assert "the same call by route" in console


def test_build_report_notes_non_zero_exit_codes(monkeypatch, tmp_path):
    box = FakeBox(DAEMON_COSTS, e2e_rc=2)
    probe = _probe(monkeypatch, tmp_path, box, runs=4, fanout=0)
    report = hlp.build_report(probe)
    assert report["fanout"] is None
    assert report["reproduce"]["exit_codes"] == [2] * 4
    assert any("exited non-zero" in note for note in report["notes"])


def test_build_report_takes_the_cold_route_when_the_daemon_is_off(monkeypatch, tmp_path):
    box = FakeBox(DAEMON_COSTS)
    probe = _probe(
        monkeypatch,
        tmp_path,
        box,
        reachable=False,
        prefs='{"guard_daemon": false}',
        runs=6,
        fanout=0,
    )
    report = hlp.build_report(probe)
    assert report["attribution"]["route"] == hlp.ROUTE_COLD
    layers = [item["layer"] for item in report["attribution"]["layers"]]
    assert "lock_cycle" in layers and "guard_logic" in layers
    # on the cold route the resolution layer is measured the way the launcher does it: two cats
    assert "interp_resolution" in box.calls
    assert any(
        line["layer"] == "route" and "guard_daemon is off" in line["title"]
        for line in report["verdict"]
    )


def test_build_report_unreachable_daemon_is_the_headline(monkeypatch, tmp_path):
    box = FakeBox(DAEMON_COSTS)
    probe = _probe(monkeypatch, tmp_path, box, reachable=False, runs=6, fanout=0, backoff=True)
    report = hlp.build_report(probe)
    assert report["attribution"]["route"] == hlp.ROUTE_DAEMON_UNREACHABLE
    assert report["verdict"][0]["layer"] == "route"
    assert "option 7" in report["verdict"][0]["remediation"]
    assert report["daemon"]["start_backoff_marker_present"] is True
    console = hlp.render_console(report)
    assert "start-backoff marker present" in console


def test_first_spawn_penalty_shows_in_the_layer_table(monkeypatch, tmp_path):
    box = FakeBox(DAEMON_COSTS, first_penalty={"python_cold_start": 1500.0})
    probe = _probe(monkeypatch, tmp_path, box, runs=6, fanout=0)
    report = hlp.build_report(probe)
    wvc = report["layers_raw"]["python_cold_start"]["warm_vs_cold"]
    assert wvc["verdict"] == "first-spawn-penalty"
    assert wvc["first_ms"] == 1700.0 and wvc["steady_ms"] == 200.0
    # the steady figure is what gets attributed, not the penalised first sample
    layers = {item["layer"]: item["ms"] for item in report["attribution"]["layers"]}
    assert layers["python_cold_start"] == 200.0
    assert "first  1700ms" in hlp.render_console(report)


# ------------------------------------------------------------------ CLI


def test_main_writes_json_and_echoes_it(monkeypatch, tmp_path, capsys):
    box = FakeBox(DAEMON_COSTS)
    root = _layout(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(hlp.time, "monotonic", box.monotonic)
    monkeypatch.setattr(hlp.subprocess, "run", box.run)
    monkeypatch.setattr(hlp, "resolve_sh", lambda: SH)
    monkeypatch.setattr(hlp, "daemon_reachability", _reach(True))
    out_file = tmp_path / "out.json"
    rc = hlp.main(
        [
            "--runs",
            "4",
            "--fanout",
            "0",
            "--json",
            str(out_file),
            "--plugin-root",
            str(root),
            "--project-dir",
            str(root),
        ]
    )
    assert rc == 0
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["attribution"]["route"] == hlp.ROUTE_DAEMON
    assert data["reproduce"]["n"] == 4
    out = capsys.readouterr().out
    assert "hook_latency_probe JSON" in out
    assert f"JSON written to {out_file}" in out
    assert "4. verdict" in out


def test_main_quiet_json_and_runs_floor(monkeypatch, tmp_path, capsys):
    box = FakeBox(DAEMON_COSTS)
    root = _layout(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(hlp.time, "monotonic", box.monotonic)
    monkeypatch.setattr(hlp.subprocess, "run", box.run)
    monkeypatch.setattr(hlp, "resolve_sh", lambda: SH)
    monkeypatch.setattr(hlp, "daemon_reachability", _reach(True))
    rc = hlp.main(
        [
            "--runs",
            "1",
            "--fanout",
            "0",
            "--quiet-json",
            "--plugin-root",
            str(root),
            "--project-dir",
            str(root),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "===== hook_latency_probe JSON" not in out
    assert "runs: 3" in out  # a floor of three so p50/p90 mean something


def test_main_refuses_without_a_shell_or_a_launcher(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(hlp, "resolve_sh", lambda: None)
    root = _layout(tmp_path)
    assert hlp.main(["--plugin-root", str(root), "--project-dir", str(root)]) == 2
    assert "no POSIX sh" in capsys.readouterr().err
    monkeypatch.setattr(hlp, "resolve_sh", lambda: SH)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert hlp.main(["--plugin-root", str(empty), "--project-dir", str(empty)]) == 2
    assert "launcher or dispatcher missing" in capsys.readouterr().err


def test_measure_repeated_records_failures_as_none(monkeypatch):
    import subprocess

    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 1)

    assert hlp.measure_repeated(lambda: (["x"], {}), 3, runner=boom) == [None, None, None]
    samples, codes = hlp.measure_repeated_rc(lambda: (["x"], {}), 2, runner=boom)
    assert samples == [None, None] and codes == [None, None]
    samples, total = hlp.measure_concurrent(lambda: (["x"], {}), 2, runner=boom)
    assert samples == [None, None] and total >= 0
