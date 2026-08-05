"""scripts/statusline.sh - interpreter resolution and rendering.

2026-08-03 perf audit: the interpreter probe loop actually EXECUTES each candidate
(`python3 --version`) on every single render, with no cache - unlike run-guard.sh, which
solved this exact problem (a Windows Python-Store stub costs multi-second hangs to
version-check) by caching the resolved interpreter to `.claude/.guard-interpreter`.
statusline.sh now reads/writes that same cache file. These tests prove the cache is
actually load-bearing (a cache hit bypasses the probe loop entirely, not just producing
the same answer by coincidence) by restricting PATH so the bare-name probe loop CANNOT
succeed, while the cache holds an absolute path that still resolves.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
STATUSLINE = REPO_ROOT / "scripts" / "statusline.sh"
REAL_PYTHON3 = shutil.which("python3")
REAL_BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(
    REAL_PYTHON3 is None or REAL_BASH is None, reason="no python3/bash on PATH to test against"
)


def _run(project_dir: Path, payload: dict, path_env: str | None = None) -> subprocess.CompletedProcess:
    env = {"HOME": str(project_dir), "CLAUDE_PROJECT_DIR": str(project_dir)}
    env["PATH"] = path_env if path_env is not None else "/usr/bin:/bin"
    # Absolute path to bash itself (not a bare "bash" lookup): a test that restricts PATH
    # to prove the interpreter cache bypasses the probe loop would otherwise also fail to
    # find bash to RUN the script in the first place.
    return subprocess.run(
        [REAL_BASH, str(STATUSLINE)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        cwd=str(project_dir),
    )


def _basic_payload(project_dir: Path) -> dict:
    return {
        "model": {"display_name": "Sonnet 4.6"},
        "cost": {"total_cost_usd": 0},
        "workspace": {"project_dir": str(project_dir)},
    }


def test_renders_normally_with_no_cache_present(tmp_path):
    """Baseline: no cache file yet - falls through to the probe loop, still renders."""
    proc = _run(tmp_path, _basic_payload(tmp_path))
    assert proc.returncode == 0
    assert "Morgan dormant" in proc.stdout


def test_writes_the_cache_after_a_fresh_probe(tmp_path):
    cache = tmp_path / ".claude" / ".guard-interpreter"
    assert not cache.is_file()
    proc = _run(tmp_path, _basic_payload(tmp_path))
    assert proc.returncode == 0
    assert cache.is_file()
    cached = cache.read_text(encoding="utf-8").strip()
    assert cached  # a real interpreter name was recorded
    assert shutil.which(cached, path="/usr/bin:/bin") is not None


def test_existing_cache_is_reused_and_left_unchanged(tmp_path):
    cache_dir = tmp_path / ".claude"
    cache_dir.mkdir(parents=True)
    (cache_dir / ".guard-interpreter").write_text("python3", encoding="utf-8")
    proc = _run(tmp_path, _basic_payload(tmp_path))
    assert proc.returncode == 0
    assert "Morgan dormant" in proc.stdout
    # still exactly what we put there - the fresh-probe branch never ran (it would
    # overwrite with whatever it found, and never SHRINKS a valid entry, but same-value
    # is the cheapest way to also prove no crash/rewrite churn happened)
    assert (cache_dir / ".guard-interpreter").read_text(encoding="utf-8").strip() == "python3"


def test_cache_hit_bypasses_the_probe_loop_entirely(tmp_path):
    """The decisive proof: PATH is restricted to a curated directory holding ONLY the
    non-python utilities the script also needs (cat/dirname/mkdir) - so `command -v
    python3/python/py` (the probe loop's bare-name lookups) cannot resolve ANYTHING - yet
    the cache holds an ABSOLUTE path to the real interpreter, which `command -v` resolves
    regardless of PATH. If the render still succeeds, the cache path was taken; if the loop
    had run instead, it would have found nothing and fallen back to the dormant message."""
    cache_dir = tmp_path / ".claude"
    cache_dir.mkdir(parents=True)
    (cache_dir / ".guard-interpreter").write_text(REAL_PYTHON3, encoding="utf-8")

    curated_path = tmp_path / "curated-path"
    curated_path.mkdir()
    for tool in ("cat", "dirname", "mkdir"):
        real = shutil.which(tool)
        assert real, f"{tool} not found on the real PATH - needed to build the fixture"
        (curated_path / tool).symlink_to(real)
    # Confirm the fixture actually excludes python (otherwise this test would prove nothing).
    assert shutil.which("python3", path=str(curated_path)) is None
    assert shutil.which("python", path=str(curated_path)) is None
    assert shutil.which("py", path=str(curated_path)) is None

    proc = _run(tmp_path, _basic_payload(tmp_path), path_env=str(curated_path))

    assert proc.returncode == 0
    # The bare shell-level fallback (interpreter never found at all) is the STATIC string
    # "😴 Morgan dormant" with no separators - indistinguishable in isolation from the
    # python heredoc's OWN "😴 Morgan dormant" engagement-status text (there is genuinely no
    # open engagement in this fixture). What only the successful python render can produce
    # is the " | "-joined model/cost/preferences tail, proving the interpreter actually ran.
    assert " | " in proc.stdout
    assert "Sonnet 4.6" in proc.stdout


def test_preferences_show_split_off_by_default(tmp_path):
    proc = _run(tmp_path, _basic_payload(tmp_path))
    assert proc.returncode == 0
    assert "split:off" in proc.stdout


def test_preferences_show_split_on_when_set(tmp_path):
    prefs_dir = tmp_path / ".claude"
    prefs_dir.mkdir(parents=True)
    (prefs_dir / "team-preferences.json").write_text(
        json.dumps({"large_context_review_split": True}), encoding="utf-8"
    )
    proc = _run(tmp_path, _basic_payload(tmp_path))
    assert proc.returncode == 0
    assert "split:on" in proc.stdout
    assert "split:off" not in proc.stdout


def test_invalid_cached_entry_falls_back_to_the_probe_loop(tmp_path):
    """A stale/bogus cache (e.g. an interpreter since uninstalled) must not brick the
    statusline - `command -v` on it fails, so it falls through exactly like no cache."""
    cache_dir = tmp_path / ".claude"
    cache_dir.mkdir(parents=True)
    (cache_dir / ".guard-interpreter").write_text(
        "nonexistent-interpreter-xyz", encoding="utf-8"
    )
    proc = _run(tmp_path, _basic_payload(tmp_path))
    assert proc.returncode == 0
    # the fallback probe ran and overwrote the bogus entry with a real one
    cached = (cache_dir / ".guard-interpreter").read_text(encoding="utf-8").strip()
    assert cached != "nonexistent-interpreter-xyz"
    assert shutil.which(cached, path="/usr/bin:/bin") is not None
