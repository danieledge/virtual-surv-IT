"""The allow-list line in the tooling probe (scripts/check-review-tools.sh, 2026-07-30):
mechanical detection for Morgan's engage-banner tip. Computed fresh on every run (never
cached with the analyser table), detection-only (the script edits nothing)."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "check-review-tools.sh"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="needs bash"
)


def _run(cwd: Path) -> str:
    proc = subprocess.run(
        ["bash", str(SCRIPT)], cwd=cwd, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0
    return proc.stdout


def test_missing_allowlist_tipped_with_command(tmp_path):
    (tmp_path / ".claude").mkdir()
    out = _run(tmp_path)
    assert "ALLOWLIST: missing" in out
    assert "--permissions" in out


def test_present_allowlist_not_tipped(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(python -m scripts.*)"]}}), encoding="utf-8"
    )
    out = _run(tmp_path)
    assert "ALLOWLIST: present" in out
    assert "--permissions ." not in out


def test_python3_variant_counts_as_present(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(python3 -m scripts.*)"]}}), encoding="utf-8"
    )
    assert "ALLOWLIST: present" in _run(tmp_path)


def test_allowlist_line_is_fresh_not_cached(tmp_path):
    """The analyser table caches; the allow-list line must reflect NOW."""
    claude = tmp_path / ".claude"
    claude.mkdir()
    out = _run(tmp_path)  # first run: missing, and it writes the tool cache
    assert "ALLOWLIST: missing" in out
    (claude / "settings.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(python -m scripts.*)"]}}), encoding="utf-8"
    )
    out = _run(tmp_path)  # cached analyser table served, allow-list recomputed
    assert "ALLOWLIST: present" in out
