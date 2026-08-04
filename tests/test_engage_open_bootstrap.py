"""Drift detector: .claude/skills/.shared/engage-open.md embeds a condensed copy of
scripts/find_plugin_root.py's discovery algorithm inline (a Python heredoc the model
hand-types into the step-0 Bash call) - it CANNOT import the real module, since locating
it is exactly the problem being solved (2026-08-04 redesign, see find_plugin_root.py's own
docstring for the "unexpected EOF" corp Windows report that motivated it).

Two textual copies of the same algorithm is an accepted, unavoidable trade-off here (not a
free duplication) - this test is the mechanical backstop so they can't silently drift, same
role test_hooks_in_sync.py plays for staged-vs-live guard files.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from scripts.find_plugin_root import find_plugin_root

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / ".claude" / "skills" / ".shared" / "engage-open.md"

_HEREDOC_RE = re.compile(r"<<'PY'\n(.*?)\nPY\n", re.DOTALL)


def _extract_heredoc() -> str:
    text = DOC.read_text(encoding="utf-8")
    m = _HEREDOC_RE.search(text)
    assert m, "engage-open.md: no <<'PY' ... PY heredoc found - did the bootstrap move?"
    return m.group(1)


def _run_discovery_only(home: Path, cwd: Path) -> str:
    """Runs the embedded heredoc's discovery logic in isolation - stops it right after
    `root` is computed (before it tries to invoke engage_probe.py, which doesn't need to
    exist for this check) by injecting a print and truncating the rest."""
    src = _extract_heredoc()
    marker = "script = Path(root"
    idx = src.index(marker)
    truncated = src[:idx] + "print('ROOT=' + root)\n"
    proc = subprocess.run(
        [sys.executable, "-c", truncated, "python3"],
        cwd=cwd,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"heredoc discovery crashed: {proc.stderr}"
    line = next(ln for ln in proc.stdout.splitlines() if ln.startswith("ROOT="))
    return line[len("ROOT=") :]


def test_heredoc_present_and_parses_as_valid_python():
    src = _extract_heredoc()
    compile(src, "<engage-open.md heredoc>", "exec")


def test_heredoc_uses_no_single_quotes():
    """The whole point of the heredoc redesign: the embedded Python must never need a
    single quote, so it stays safely embeddable inside a `<<'PY'` block (or a
    single-quoted -c argument) without any quote-type collision risk."""
    assert "'" not in _extract_heredoc()


def test_repo_as_project_matches(tmp_path):
    cwd = tmp_path / "repo"
    (cwd / "docs").mkdir(parents=True)
    (cwd / "docs" / "team-operating-guide.md").write_text("x", encoding="utf-8")
    home = tmp_path / "home"
    home.mkdir()
    assert _run_discovery_only(home, cwd) == find_plugin_root(home, cwd) == ""


def test_registry_resolution_matches(tmp_path):
    home = tmp_path / "home"
    plugin_dir = tmp_path / "virtual-surv-IT"
    manifest_dir = plugin_dir / ".claude-plugin"
    manifest_dir.mkdir(parents=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": "compliance-surveillance-team@virtual-surv-it"}), encoding="utf-8"
    )
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps({"plugins": {"x": [{"installPath": str(plugin_dir)}]}}), encoding="utf-8"
    )
    cwd = tmp_path / "project"
    cwd.mkdir()
    expected = find_plugin_root(home, cwd)
    assert expected == str(plugin_dir)
    assert _run_discovery_only(home, cwd) == expected


def test_filesystem_fallback_matches(tmp_path):
    home = tmp_path / "home"
    cache = home / ".claude" / "plugins" / "cache" / "compliance-surveillance-team" / "1.0.0"
    (cache / "docs").mkdir(parents=True)
    (cache / "docs" / "team-operating-guide.md").write_text("x", encoding="utf-8")
    cwd = tmp_path / "project"
    cwd.mkdir()
    expected = find_plugin_root(home, cwd)
    assert expected == str(cache)
    assert _run_discovery_only(home, cwd) == expected


def test_no_install_found_matches(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    cwd = tmp_path / "project"
    cwd.mkdir()
    assert _run_discovery_only(home, cwd) == find_plugin_root(home, cwd) == ""
