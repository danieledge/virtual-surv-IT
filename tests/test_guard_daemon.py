"""Tests for the production guard daemon (scripts/staged_hooks/guard_daemon.py,
scripts/staged_hooks/guard_daemon_client.py) - promoted from the ADR-014 design
spike (see tests/test_adr014_guard_daemon_spike.py, which tests the now-archived
spike copy, not this one). No test file covered the production module directly
before this one - a gap the 2026-08-13 audit noted.

Tests the STAGED copies (same convention as tests/test_run_guard_interpreter_cache.py's
LAUNCHER constant) - functional correctness is verified here; a separate byte-identity
check (test_hooks_in_sync.py's test_staged_matches_live) enforces that a human has
applied staged to live before treating a fix as actually deployed.

Focus: the 2026-08-13 fix for the module_root/state_root conflation - a live audit
caught that guard_daemon.py and guard_daemon_client.py used ONE root for two
different things (locating the plugin-shipped dispatcher vs. this project's own
port file), the same bug class run-guard.sh's own $_root/$_project_root split had
already fixed one layer up. These tests exist specifically to make that conflation
impossible to silently reintroduce.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STAGED_DIR = REPO_ROOT / "scripts" / "staged_hooks"


def _load_guard_daemon(monkeypatch):
    """Load scripts/staged_hooks/guard_daemon.py by explicit file path, registered
    into sys.modules under the bare name "guard_daemon" so guard_daemon_client.py's
    own `from guard_daemon import read_port_and_token` resolves to THIS instance -
    same collision-proofing rationale as the spike test file's loader (see its
    docstring: two same-named modules on sys.path is a real, previously-hit bug)."""
    path = STAGED_DIR / "guard_daemon.py"
    spec = importlib.util.spec_from_file_location("guard_daemon", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "guard_daemon", module)
    spec.loader.exec_module(module)
    return module


def _load_guard_daemon_client(monkeypatch):
    _load_guard_daemon(monkeypatch)
    path = STAGED_DIR / "guard_daemon_client.py"
    spec = importlib.util.spec_from_file_location("guard_daemon_client", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "guard_daemon_client", module)
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------- read_port_and_token


def test_read_port_and_token_none_when_file_absent(tmp_path, monkeypatch):
    gd = _load_guard_daemon(monkeypatch)
    assert gd.read_port_and_token(tmp_path) == (None, None)


def test_read_port_and_token_none_on_corrupt_content(tmp_path, monkeypatch):
    gd = _load_guard_daemon(monkeypatch)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / gd.PORT_FILE_NAME).write_text("garbage", encoding="utf-8")
    assert gd.read_port_and_token(tmp_path) == (None, None)


def test_read_port_and_token_returns_written_values(tmp_path, monkeypatch):
    gd = _load_guard_daemon(monkeypatch)
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / gd.PORT_FILE_NAME).write_text("54321\nabc123\n", encoding="utf-8")
    assert gd.read_port_and_token(tmp_path) == (54321, "abc123")


def test_client_loads_and_reads_port_without_importing_guard_daemon_at_all(tmp_path):
    """H2 (2026-08-14 perf audit): the client used to `from guard_daemon import
    read_port_and_token`, which required guard_daemon.py to be importable (a
    sys.path.insert hack) and executed its WHOLE module - a real TCP server
    implementation (socketserver/threading/secrets/io) - just to reach a 10-line file
    read. Deliberately does NOT call _load_guard_daemon first (unlike every other test
    in this file): loading the client with "guard_daemon" genuinely absent from
    sys.modules must still succeed, and its own inlined read_port_and_token must still
    work correctly - proving the two are no longer coupled at import time."""
    assert "guard_daemon" not in sys.modules  # nothing pre-loaded it - the point of this test

    path = STAGED_DIR / "guard_daemon_client.py"
    spec = importlib.util.spec_from_file_location("guard_daemon_client_standalone", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # must not raise ModuleNotFoundError: guard_daemon

    assert "guard_daemon" not in sys.modules  # still never imported, even by loading it

    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / module.PORT_FILE_NAME).write_text("54321\nabc123\n", encoding="utf-8")
    assert module.read_port_and_token(tmp_path) == (54321, "abc123")


# --------------------------------------------------------------- run(): the actual fix


def test_run_writes_port_file_under_state_root_not_module_root(tmp_path, monkeypatch):
    """The regression this whole fix exists for, reproduced directly: a REAL daemon
    process, started with module_root != state_root, must place its port file under
    state_root - never module_root."""
    gd = _load_guard_daemon(monkeypatch)

    module_root = tmp_path / "plugin-install"
    state_root = tmp_path / "project"
    module_root.mkdir()
    state_root.mkdir()

    result = {}

    def _run():
        result["code"] = gd.run(module_root, state_root, idle_timeout=1)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    try:
        deadline = time.monotonic() + 10
        port_file = state_root / ".claude" / gd.PORT_FILE_NAME
        while time.monotonic() < deadline and not port_file.is_file():
            time.sleep(0.05)
        assert port_file.is_file(), "port file never appeared under state_root"
        assert not (module_root / ".claude").exists(), (
            "port file (or its parent dir) leaked under module_root"
        )
        port, token = gd.read_port_and_token(state_root)
        assert port is not None and token
    finally:
        t.join(timeout=5)


def test_run_defaults_state_root_to_module_root_when_omitted(tmp_path, monkeypatch):
    """Backward compatibility: a caller that still passes only one root (today's
    project-mode invocation) keeps writing the port file where it always did."""
    gd = _load_guard_daemon(monkeypatch)

    result = {}

    def _run():
        result["code"] = gd.run(tmp_path, idle_timeout=1)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    try:
        deadline = time.monotonic() + 10
        port_file = tmp_path / ".claude" / gd.PORT_FILE_NAME
        while time.monotonic() < deadline and not port_file.is_file():
            time.sleep(0.05)
        assert port_file.is_file()
    finally:
        t.join(timeout=5)


# --------------------------------------------------------------- multi-target dispatch


def _send_raw_request(port: int, token: str, request: dict) -> dict:
    """Talks to a real running daemon directly over its own protocol - the same
    newline-delimited JSON request/response shape guard_daemon_client.py uses -
    without going through the client at all, so these tests exercise the daemon's
    OWN dispatch/handle logic precisely."""
    import json
    import socket as _socket

    with _socket.create_connection(("127.0.0.1", port), timeout=2) as sock:
        sock.settimeout(5)
        sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
        sock.shutdown(_socket.SHUT_WR)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return json.loads(b"".join(chunks).decode("utf-8"))


def _start_real_daemon(gd, module_root, state_root, idle_timeout=5):
    """Starts a real daemon thread with module_root (where target scripts are
    imported from - REPO_ROOT, so every real target script genuinely exists) kept
    SEPARATE from state_root (where the port file lands - always a throwaway
    tmp_path in these tests, never REPO_ROOT's own real .claude/ directory, which
    this session's own real daemon may already be using - writing there would risk
    colliding with it). Returns (port, token) once the port file appears. Caller
    doesn't need to join the thread - idle_timeout keeps it short-lived and it's a
    daemon thread either way."""
    t = threading.Thread(
        target=lambda: gd.run(module_root, state_root, idle_timeout=idle_timeout), daemon=True
    )
    t.start()
    port_file = state_root / ".claude" / gd.PORT_FILE_NAME
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not port_file.is_file():
        time.sleep(0.05)
    assert port_file.is_file(), "daemon never started"
    lines = port_file.read_text(encoding="utf-8").splitlines()
    return int(lines[0]), lines[1]


def test_daemon_dispatches_to_the_named_target_not_always_bash_hook_dispatcher(
    tmp_path, monkeypatch
):
    """The actual point of the whole extension: two DIFFERENT targets in the same
    request set must each get answered by their OWN script, not silently both
    dispatched to bash_hook_dispatcher. Uses REPO_ROOT (this real repo) as
    module_root so every real target script genuinely exists to import."""
    gd = _load_guard_daemon(monkeypatch)
    port, token = _start_real_daemon(gd, REPO_ROOT, tmp_path)

    harmless = '{"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}}'
    resp1 = _send_raw_request(
        port, token, {"token": token, "target": "bash_hook_dispatcher", "payload": harmless}
    )
    assert resp1["exit_code"] == 0
    assert not resp1.get("daemon_stale")

    ask_payload = '{"tool_name": "AskUserQuestion", "tool_input": {"questions": []}}'
    resp2 = _send_raw_request(
        port, token, {"token": token, "target": "locked_menu_guard", "payload": ask_payload}
    )
    assert resp2["exit_code"] == 0
    assert not resp2.get("daemon_stale")


def test_daemon_dispatches_to_persona_anchor(tmp_path, monkeypatch):
    """persona_anchor.py added after its own two daemon-safety fixes (deduped
    sys.path insert, check_artifacts.py in the staleness watch list) - a dormant
    session (no artifacts/ dir, its own genuine no-op path) proves dispatch reaches
    the real script and returns cleanly, without needing a live engagement pack."""
    gd = _load_guard_daemon(monkeypatch)
    port, token = _start_real_daemon(gd, REPO_ROOT, tmp_path)

    payload = ('{"cwd": "%s"}' % str(tmp_path)).replace("\\", "\\\\")
    resp = _send_raw_request(
        port, token, {"token": token, "target": "persona_anchor", "payload": payload}
    )
    assert resp["exit_code"] == 0
    assert not resp.get("daemon_stale")


def test_check_artifacts_is_in_the_daemon_staleness_watch_list(monkeypatch):
    """persona_anchor.py's own _load_checker caches check_artifacts.py at module
    level in its fallback path - a live edit to it must restart the whole daemon
    (the general mechanism, not bespoke per-hook invalidation), or a stale cached
    checker could silently keep answering with outdated engagement-state logic."""
    gd = _load_guard_daemon(monkeypatch)
    paths = gd._guard_module_paths(REPO_ROOT)
    assert REPO_ROOT / "scripts" / "check_artifacts.py" in paths


def test_daemon_captures_stdout_for_stop_hook_dispatcher(tmp_path, monkeypatch):
    """stop_hook_dispatcher.py answers via stdout (Stop hooks signal that way), not
    stderr like every other target - the daemon must capture and return it, not
    swallow it or leak it to the daemon process's own real stdout."""
    gd = _load_guard_daemon(monkeypatch)
    port, token = _start_real_daemon(gd, REPO_ROOT, tmp_path)

    # A payload with no stop_hook_active and no gated engagement pack in tmp_path -
    # the dispatcher's own fail-open/nothing-to-do path, which still answers via a
    # real (if minimal) stdout write, proving the capture mechanism itself works.
    payload = '{"stop_hook_active": false, "cwd": "%s"}' % str(tmp_path).replace("\\", "\\\\")
    resp = _send_raw_request(
        port, token, {"token": token, "target": "stop_hook_dispatcher", "payload": payload}
    )
    assert not resp.get("daemon_stale")
    assert "stdout" in resp  # the field exists at all - the actual protocol widening


def test_daemon_unknown_target_fails_open_via_daemon_stale_signal(tmp_path, monkeypatch):
    """A genuinely unknown target (protocol mismatch, typo, anything) must never
    crash the daemon or hang the connection - it reuses the existing daemon_stale
    signal, which the client already treats as "cold-start this call safely"."""
    gd = _load_guard_daemon(monkeypatch)
    port, token = _start_real_daemon(gd, REPO_ROOT, tmp_path)

    resp = _send_raw_request(
        port, token, {"token": token, "target": "not_a_real_target", "payload": "{}"}
    )
    assert resp.get("daemon_stale") is True
    assert resp["exit_code"] == 0  # fails open, never blocks


def test_daemon_backward_compat_defaults_to_bash_hook_dispatcher_when_target_omitted(
    tmp_path, monkeypatch
):
    """A request with NO "target" field at all (an older client that predates this
    extension) must still be served correctly - defaulting to bash_hook_dispatcher,
    today's only behaviour before this extension existed."""
    gd = _load_guard_daemon(monkeypatch)
    port, token = _start_real_daemon(gd, REPO_ROOT, tmp_path)

    harmless = '{"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}}'
    resp = _send_raw_request(port, token, {"token": token, "payload": harmless})  # no "target"
    assert not resp.get("daemon_stale")
    assert resp["exit_code"] == 0


# --------------------------------------------------------------- client: state vs module root


def test_client_try_daemon_reads_port_from_state_root(tmp_path, monkeypatch):
    client = _load_guard_daemon_client(monkeypatch)

    module_root = tmp_path / "plugin-install"
    state_root = tmp_path / "project"
    module_root.mkdir()
    (state_root / ".claude").mkdir(parents=True)
    # Port 1 is privileged/unlikely-bound - connection refused is the fast,
    # deterministic failure this exercises (same technique as the spike test).
    (state_root / ".claude" / "guard-daemon-port").write_text("1\ndeadbeef\n", encoding="utf-8")

    assert client._try_daemon(state_root, "bash_hook_dispatcher", '{"tool_name": "Read"}') is None
    # Never looked under module_root at all.
    assert not (module_root / ".claude").exists()


def test_client_cold_start_fallback_uses_module_root_for_the_real_dispatcher(monkeypatch):
    """The fallback must find the REAL, plugin-shipped dispatcher via module_root -
    proven by pointing module_root at the actual repo root and getting a real,
    correct (non-error) result back."""
    client = _load_guard_daemon_client(monkeypatch)

    exit_code, _stderr, _stdout = client._cold_start_fallback(
        REPO_ROOT,
        "bash_hook_dispatcher",
        '{"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}}',
    )
    assert exit_code == 0


def test_client_cold_start_fallback_dispatches_by_target_name(monkeypatch):
    """A DIFFERENT target name must resolve to that script, not always
    bash_hook_dispatcher.py - the actual point of the multi-target extension. Uses
    locked_menu_guard.py (also a real, current script) to prove it's target-driven,
    not hardcoded to one filename."""
    client = _load_guard_daemon_client(monkeypatch)

    exit_code, _stderr, _stdout = client._cold_start_fallback(
        REPO_ROOT,
        "locked_menu_guard",
        '{"tool_name": "AskUserQuestion", "tool_input": {"questions": []}}',
    )
    assert exit_code in (0, 2)  # a real answer either way, not a "file not found" crash


def test_client_start_daemon_detached_passes_both_roots_to_the_subprocess(tmp_path, monkeypatch):
    """The actual regression, one layer up: the spawned daemon subprocess must
    receive BOTH module_root and state_root as separate argv entries, not
    collapsed into one."""
    client = _load_guard_daemon_client(monkeypatch)

    captured = {}

    def fake_popen(argv, **kwargs):
        captured["argv"] = argv

        class _P:
            pass

        return _P()

    monkeypatch.setattr(client.subprocess, "Popen", fake_popen)

    module_root = tmp_path / "plugin-install"
    state_root = tmp_path / "project"
    client._start_daemon_detached(module_root, state_root)

    assert captured["argv"][-2:] == [str(module_root), str(state_root)]


def test_client_windows_spawn_sets_breakaway_from_job(tmp_path, monkeypatch):
    """2026-08-13 (reported via log analysis of a real session): DETACHED_PROCESS and
    CREATE_NO_WINDOW control console inheritance, NOT Windows Job Object membership - a
    child is still added to the SAME job as its parent by default regardless of those two
    flags. Many terminal/IDE launchers put their process tree in a job with
    JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, which would silently kill this "detached" daemon
    the moment the invoking session ends - defeating the entire point of a persistent
    daemon. CREATE_BREAKAWAY_FROM_JOB must be set alongside the other two.

    None of the three creationflags constants exist as real subprocess module attributes
    on non-Windows Python (confirmed: hasattr is False for all three on this Linux box) -
    injected here (raising=False) so this test can exercise the Windows branch on any
    platform, same technique tests elsewhere in this project already use for OS-specific
    code paths."""
    client = _load_guard_daemon_client(monkeypatch)

    monkeypatch.setattr(client.sys, "platform", "win32")
    monkeypatch.setattr(client.subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)
    monkeypatch.setattr(client.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)
    monkeypatch.setattr(client.subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000, raising=False)

    captured = {}

    def fake_popen(argv, **kwargs):
        captured["kwargs"] = kwargs

        class _P:
            pass

        return _P()

    monkeypatch.setattr(client.subprocess, "Popen", fake_popen)
    client._start_daemon_detached(tmp_path / "plugin-install", tmp_path / "project")

    flags = captured["kwargs"]["creationflags"]
    assert flags & 0x00000008  # DETACHED_PROCESS
    assert flags & 0x08000000  # CREATE_NO_WINDOW
    assert flags & 0x01000000  # CREATE_BREAKAWAY_FROM_JOB - the actual fix


def test_client_main_defaults_state_root_to_module_root_with_one_arg(tmp_path, monkeypatch):
    """CLI backward compatibility: `guard_daemon_client.py <module_root>` alone
    (today's call shape from an unmodified run-guard.sh, or any other caller that
    hasn't been updated) must still behave exactly as before - state_root falls
    back to module_root, and target defaults to bash_hook_dispatcher."""
    client = _load_guard_daemon_client(monkeypatch)

    seen = {}

    def fake_try_daemon(state_root, target, payload_text):
        seen["state_root"] = state_root
        seen["target"] = target
        return (0, "", "")

    monkeypatch.setattr(client, "_try_daemon", fake_try_daemon)
    monkeypatch.setattr(sys, "argv", ["guard_daemon_client.py", str(tmp_path)])
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("{}"))

    client.main()
    assert seen["state_root"] == tmp_path
    assert seen["target"] == "bash_hook_dispatcher"


def test_client_main_passes_explicit_target_as_third_arg(tmp_path, monkeypatch):
    """The actual new CLI surface: a third positional argument selects the target,
    exactly as run-guard.sh's own $_daemon_target now passes it."""
    client = _load_guard_daemon_client(monkeypatch)

    seen = {}

    def fake_try_daemon(state_root, target, payload_text):
        seen["target"] = target
        return (0, "", "")

    monkeypatch.setattr(client, "_try_daemon", fake_try_daemon)
    monkeypatch.setattr(
        sys, "argv", ["guard_daemon_client.py", str(tmp_path), str(tmp_path), "locked_menu_guard"]
    )
    monkeypatch.setattr(sys, "stdin", __import__("io").StringIO("{}"))

    client.main()
    assert seen["target"] == "locked_menu_guard"


# --------------------------------------------------------------- run-guard.sh integration


LAUNCHER = STAGED_DIR / "run-guard.sh"

pytestmark_sh = pytest.mark.skipif(
    sys.platform == "win32" or not LAUNCHER.is_file(),
    reason="needs a POSIX shell + staged launcher",
)


@pytestmark_sh
def test_launcher_invokes_daemon_client_with_both_roots_when_they_differ(tmp_path):
    """End-to-end proof at the run-guard.sh level: with CLAUDE_PLUGIN_ROOT and
    CLAUDE_PROJECT_DIR pointing at two DIFFERENT directories, and guard_daemon
    true, the launcher must invoke DAEMON_CLIENT with BOTH roots as distinct
    positional args, in ($_root, $_project_root) order."""
    import json
    import os

    plugin_root = tmp_path / "plugin-install"
    project_dir = tmp_path / "project"
    (plugin_root / "scripts").mkdir(parents=True)
    (project_dir / ".claude").mkdir(parents=True)
    (project_dir / ".claude" / "team-preferences.json").write_text(
        '{"guard_daemon": true}', encoding="utf-8"
    )
    dispatcher_target = project_dir / "bash_hook_dispatcher.py"
    dispatcher_target.write_text("", encoding="utf-8")

    argv_log = plugin_root / "argv.log"
    fake_client = plugin_root / "scripts" / "guard_daemon_client.py"
    fake_client.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"open({str(argv_log)!r}, 'w').write('\\n'.join(sys.argv[1:]))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    fake_client.chmod(0o755)

    env = {
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "PATH": os.environ["PATH"],
    }
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}})
    proc = subprocess.run(
        ["sh", str(LAUNCHER), str(dispatcher_target)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert argv_log.is_file(), "the fake daemon client was never invoked"
    lines = argv_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3, (
        f"expected exactly 3 args (module_root, state_root, target), got {lines}"
    )
    assert lines[0] == str(plugin_root)
    assert lines[1] == str(project_dir)
    assert lines[2] == "bash_hook_dispatcher"


@pytestmark_sh
def test_launcher_passes_the_correct_target_name_for_each_daemon_servable_script(tmp_path):
    """The actual point of the multi-target extension at the launcher level: each of
    the five daemon-servable scripts must resolve to ITS OWN target name, not always
    bash_hook_dispatcher - and a target NOT in the servable set (a plain, unrelated
    script) must never engage the daemon at all, proving the case-match gate is
    exact, not a catch-all."""
    import json
    import os

    cases = [
        ("bash_hook_dispatcher.py", "bash_hook_dispatcher"),
        ("locked_menu_guard.py", "locked_menu_guard"),
        ("post_edit_lint.py", "post_edit_lint"),
        ("subagent_return_budget.py", "subagent_return_budget"),
        ("stop_hook_dispatcher.py", "stop_hook_dispatcher"),
        ("persona_anchor.py", "persona_anchor"),
    ]

    plugin_root = tmp_path / "plugin-install"
    project_dir = tmp_path / "project"
    (plugin_root / "scripts").mkdir(parents=True)
    (project_dir / ".claude").mkdir(parents=True)
    (project_dir / ".claude" / "team-preferences.json").write_text(
        '{"guard_daemon": true}', encoding="utf-8"
    )
    argv_log = plugin_root / "argv.log"
    fake_client = plugin_root / "scripts" / "guard_daemon_client.py"
    fake_client.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"open({str(argv_log)!r}, 'w').write('\\n'.join(sys.argv[1:]))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    fake_client.chmod(0o755)
    env = {
        "CLAUDE_PROJECT_DIR": str(project_dir),
        "CLAUDE_PLUGIN_ROOT": str(plugin_root),
        "PATH": os.environ["PATH"],
    }
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}})

    for basename, expected_target in cases:
        argv_log.unlink(missing_ok=True)
        target_script = project_dir / basename
        target_script.write_text("", encoding="utf-8")
        proc = subprocess.run(
            ["sh", str(LAUNCHER), str(target_script)],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert proc.returncode == 0, f"{basename}: {proc.stderr}"
        assert argv_log.is_file(), f"{basename}: fake daemon client was never invoked"
        lines = argv_log.read_text(encoding="utf-8").splitlines()
        assert lines[2] == expected_target, (
            f"{basename}: expected target {expected_target}, got {lines}"
        )

    # A script NOT in the daemon-servable set must never reach the daemon client at all.
    argv_log.unlink(missing_ok=True)
    unrelated = project_dir / "not_a_daemon_target.py"
    unrelated.write_text("import sys; sys.exit(0)\n", encoding="utf-8")
    proc = subprocess.run(
        ["sh", str(LAUNCHER), str(unrelated)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert not argv_log.is_file(), "an unrelated script must never engage the daemon client"


@pytestmark_sh
def test_launcher_self_locates_when_claude_plugin_root_is_unset(tmp_path):
    """The exact reported live scenario: CLAUDE_PLUGIN_ROOT is completely UNSET in this
    process (not just pointing somewhere unexpected - genuinely absent, as when Claude
    Code's hook templating substitutes it correctly into the command line but doesn't
    also export it into the spawned process's environment). Without self-location, $_root
    falls back to CLAUDE_PROJECT_DIR, and DAEMON_CLIENT resolves to
    <project>/scripts/guard_daemon_client.py - a file that only ever lives in the
    plugin's own tree, never copied into a consuming project - so the daemon silently
    never engages. The launcher is placed at its real, documented location
    (.claude/hooks/run-guard.sh under a fake plugin root) and invoked by that literal
    path, exactly as Claude Code's own templating would construct the command - proving
    $0-based self-location recovers the correct root even with the env var entirely
    missing."""
    import json
    import os
    import shutil

    plugin_root = tmp_path / "plugin-install"
    project_dir = tmp_path / "project"
    (plugin_root / "scripts").mkdir(parents=True)
    hooks_dir = plugin_root / ".claude" / "hooks"
    hooks_dir.mkdir(parents=True)
    shutil.copy2(LAUNCHER, hooks_dir / "run-guard.sh")
    (project_dir / ".claude").mkdir(parents=True)
    (project_dir / ".claude" / "team-preferences.json").write_text(
        '{"guard_daemon": true}', encoding="utf-8"
    )
    dispatcher_target = project_dir / "bash_hook_dispatcher.py"
    dispatcher_target.write_text("", encoding="utf-8")

    argv_log = plugin_root / "argv.log"
    fake_client = plugin_root / "scripts" / "guard_daemon_client.py"
    fake_client.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        f"open({str(argv_log)!r}, 'w').write('\\n'.join(sys.argv[1:]))\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )
    fake_client.chmod(0o755)

    env = {
        "CLAUDE_PROJECT_DIR": str(project_dir),
        # CLAUDE_PLUGIN_ROOT deliberately absent - the exact reported failure condition.
        "PATH": os.environ["PATH"],
    }
    payload = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}})
    proc = subprocess.run(
        ["sh", str(hooks_dir / "run-guard.sh"), str(dispatcher_target)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert argv_log.is_file(), (
        "the fake daemon client was never invoked - self-location did not recover the plugin root"
    )
    lines = argv_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert lines[0] == str(plugin_root), (
        f"module_root resolved to {lines[0]!r}, expected the plugin root {str(plugin_root)!r} "
        "- self-location fell back to something else"
    )
    assert lines[1] == str(project_dir)
    assert lines[2] == "bash_hook_dispatcher"
