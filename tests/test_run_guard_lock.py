"""Serialization lock in the guard launcher (scripts/staged_hooks/run-guard.sh, human-
installed via scripts/apply-run-guard-lock.sh).

Regression under test (live corporate report, 2026-08-10): a Workflow-tool fan-out fires
several subagents' tool calls within the same instant, each independently spawning this
launcher - normally hidden (one spawn finishes before the next tool call starts), but under
real concurrency N interpreter cold-starts hit CPU scheduling and endpoint-security scanning
on a Windows box AT ONCE, measured live turning ~50-100ms hook latency into 2,000-8,000ms
across the board. An mkdir-based lock (atomic, portable - no flock dependency) now queues
concurrent launches instead of letting them all spawn simultaneously.

Two failure modes are tested explicitly, not just the happy path, because this gates every
tool call in the session: a bounded wait that fails OPEN rather than hangs forever, and
stale-lock reclaim so one crashed holder can't starve every call behind it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "scripts" / "staged_hooks" / "run-guard.sh"
NOOP_TARGET = REPO_ROOT / ".claude" / "hooks" / "guard-raw-data.py"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sh") is None, reason="needs a POSIX shell"
)

PAYLOAD = json.dumps({"tool_name": "Read", "tool_input": {"file_path": "/tmp/harmless"}})


def _env(project_dir: Path) -> dict:
    import os

    return {"CLAUDE_PROJECT_DIR": str(project_dir), "PATH": os.environ["PATH"]}


def _run(project_dir: Path, args=None, payload: str = PAYLOAD, timeout: float = 30):
    return subprocess.run(
        ["sh", str(LAUNCHER), *(args or [str(NOOP_TARGET)])],
        input=payload,
        capture_output=True,
        text=True,
        env=_env(project_dir),
        timeout=timeout,
    )


def _lock_dir(project_dir: Path) -> Path:
    return project_dir / ".claude" / ".guard-lock"


@pytest.fixture
def proj(tmp_path):
    p = tmp_path / "proj"
    (p / ".claude").mkdir(parents=True)
    return p


def test_normal_call_still_passes_stdin_and_exit_code_through(proj):
    """The lock changes HOW the interpreter runs (child + wait, not exec) - it must not
    change the documented contract: stdin/exit code pass through unchanged."""
    blocking_payload = json.dumps(
        {"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "data/raw"}}
    )
    (proj / "data" / "raw").mkdir(parents=True)
    (proj / "data" / "raw" / "trades.csv").write_text("x", encoding="utf-8")
    proc = _run(proj, payload=blocking_payload)
    assert proc.returncode == 2  # the guard's own block, relayed through unchanged


def test_lock_is_released_after_a_normal_call(proj):
    assert _run(proj).returncode == 0
    assert not _lock_dir(proj).exists()


def test_lock_acquires_promptly_when_claude_dir_does_not_exist_yet(tmp_path):
    """mkdir "$LOCK_DIR" deliberately has no -p (an existing target failing IS the
    "someone else holds it" signal the loop polls on) - so the parent must be created
    separately, once, up front. Without that, a missing .claude/ fails every acquisition
    attempt the same way real contention would, wasting the full ~1.5s wait budget on every
    call rather than succeeding immediately."""
    proj_dir = tmp_path / "proj-no-claude-yet"
    proj_dir.mkdir()
    assert not (proj_dir / ".claude").exists()
    start = time.monotonic()
    proc = _run(proj_dir)
    elapsed = time.monotonic() - start
    assert proc.returncode == 0
    assert elapsed < 1.0, (
        f"took {elapsed:.2f}s - should acquire immediately, not wait out the budget"
    )
    assert not _lock_dir(proj_dir).exists()  # released after this call's own completion


def test_concurrent_calls_are_actually_serialized(proj):
    """Real concurrency (a thread pool, not a loop) driving N launcher invocations that each
    record their own start/end wall-clock around a short sleep - proves the lock queues them
    rather than letting them all run at once, the exact live failure mode this fixes.

    Also the regression net for the reclaim race (2026-09-12, H-20): the first cut of the
    dead-holder check reclaimed on a read taken one poll earlier, so it tore down a lock a
    DIFFERENT caller had created in between and ran alongside it - 1-2 of these 5 calls
    overlapping, reproducibly. The reclaim re-reads the stamp and only removes a lock that
    still names the same dead holder."""
    n = 5
    marker = proj / "timings.log"
    target = proj / "record_timing.py"
    target.write_text(
        "import sys, time\n"
        "start = time.time()\n"
        "time.sleep(0.15)\n"
        "end = time.time()\n"
        f"open({str(marker)!r}, 'a').write(f'{{start}} {{end}}\\n')\n"
        "sys.exit(0)\n",
        encoding="utf-8",
    )

    def call(_i):
        return _run(proj, args=[str(target)])

    with ThreadPoolExecutor(max_workers=n) as pool:
        results = list(pool.map(call, range(n)))

    assert all(r.returncode == 0 for r in results)
    spans = sorted(
        (float(a), float(b))
        for a, b in (line.split() for line in marker.read_text(encoding="utf-8").splitlines())
    )
    assert len(spans) == n
    overlaps = sum(1 for i in range(1, n) if spans[i][0] < spans[i - 1][1])
    assert overlaps == 0, f"{overlaps} of {n} calls ran concurrently - lock did not serialize"


def test_stale_lock_is_reclaimed_quickly_not_waited_out(proj):
    """A lock whose stamp carries no pid is reclaimed on the AGE backstop.

    The threshold moved from 10s to 120s on 2026-09-12 (audit H-20): 10s sat four lines below
    this launcher's own recorded measurement of 25-90s cold starts under fan-out contention,
    so a genuinely working holder was declared abandoned and its lock removed - and its own
    EXIT trap then deleted whichever other process's lock directory existed by then. Age is
    the backstop for a pid-less stamp now; the pid test below is the primary signal.
    """
    lock = _lock_dir(proj)
    lock.mkdir(parents=True)
    (lock / "acquired-at").write_text(str(int(time.time()) - 300), encoding="utf-8")
    start = time.monotonic()
    proc = _run(proj)
    elapsed = time.monotonic() - start
    assert proc.returncode == 0
    assert elapsed < 1.0, f"took {elapsed:.2f}s - should reclaim a stale lock near-instantly"
    assert not lock.exists()  # released after this call's own (successful) acquisition


def test_a_lock_whose_holder_is_dead_is_reclaimed_whatever_its_age(proj):
    """The pid is the primary signal (H-20). A holder that crashed or was SIGKILLed - the one
    case the EXIT trap cannot cover - is gone the moment its pid is gone, and a waiter should
    not have to sit out a 120-second backstop to find that out."""
    lock = _lock_dir(proj)
    lock.mkdir(parents=True)
    dead_pid = _a_dead_pid()
    (lock / "acquired-at").write_text(f"{int(time.time())}\n{dead_pid}\n", encoding="utf-8")
    start = time.monotonic()
    proc = _run(proj)
    elapsed = time.monotonic() - start
    assert proc.returncode == 0
    assert elapsed < 1.0, f"took {elapsed:.2f}s - a dead holder should be reclaimed at once"
    assert not lock.exists()


def test_a_lock_whose_holder_is_alive_is_never_reclaimed(proj):
    """The other direction, and the one that mattered: a working holder must keep its lock
    however long it has been working. This caller waits its budget and then proceeds without
    the lock (fail open, performance only) - it must NOT tear down a live holder's lock."""
    lock = _lock_dir(proj)
    lock.mkdir(parents=True)
    # This test process is unquestionably alive, so it is the holder pid.
    (lock / "acquired-at").write_text(
        f"{int(time.time()) - 300}\n{os.getpid()}\n", encoding="utf-8"
    )
    proc = _run(proj, timeout=30)
    assert proc.returncode == 0
    assert lock.exists(), "a live holder's lock was reclaimed on age alone"


def _a_dead_pid() -> int:
    """A pid that is certainly not running: spawn a trivial process and wait for it.

    Reusing a hard-coded high number risks colliding with a real process on a busy box, which
    would turn this into a flaky test of the opposite behaviour."""
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_a_genuinely_held_lock_fails_open_within_the_wait_budget(proj):
    """The lock must never turn into an indefinite hang - a fresh (non-stale) lock held by
    someone else must cause THIS call to give up and proceed WITHOUT it after a bounded
    wait, not block forever. Fail open on a broken serialization mechanism, same posture as
    the no-interpreter-found case elsewhere in this launcher."""
    lock = _lock_dir(proj)
    lock.mkdir(parents=True)
    (lock / "acquired-at").write_text(str(int(time.time())), encoding="utf-8")  # fresh, not stale
    start = time.monotonic()
    proc = _run(proj, timeout=10)
    elapsed = time.monotonic() - start
    assert proc.returncode == 0  # proceeded anyway - fail open, not a hang
    assert elapsed < 5.0, (
        f"took {elapsed:.2f}s - the wait budget is ~1.5s, this should not be near the 10s test timeout"
    )
    # This call never owned the lock (gave up waiting), so it must not have torn down
    # the still-fresh lock it doesn't own.
    assert lock.exists()


def test_lock_dir_matches_the_documented_gitignore_entry():
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert re.search(r"^\.claude/\.guard-lock/?$", gitignore, re.MULTILINE), (
        ".claude/.guard-lock (transient, environment-specific) should be gitignored, same "
        "treatment as .guard-interpreter and .raw-data-present"
    )
