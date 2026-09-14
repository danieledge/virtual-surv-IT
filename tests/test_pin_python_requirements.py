"""scripts/pin_python_requirements.py - the human-run generator of the hash-pinned lock files
(2026-09-13 framework review, step 7.13). Network is mocked; the lock FORMAT is the contract."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import pin_python_requirements as pin  # noqa: E402


def _fake_resolve(requirements, platform_args, timeout=600):
    if platform_args and "win_amd64" in platform_args:
        return {"pytest": "9.1.1", "colorama": "0.4.6"}  # a Windows-only dependency
    return {"pytest": "9.1.1", "pluggy": "1.6.0"}


def test_the_lock_unions_platforms_and_lists_every_pypi_digest(monkeypatch, tmp_path):
    monkeypatch.setattr(pin, "resolve", _fake_resolve)
    monkeypatch.setattr(pin, "pypi_digests", lambda name, version, timeout=30: ["a" * 64, "b" * 64])
    req = tmp_path / "requirements-dev.txt"
    req.write_text("pytest>=8\n", encoding="utf-8")
    text, warnings = pin.build_lock(req)
    assert "colorama==0.4.6 \\" in text, "the Windows-only dependency must be in the one lock"
    assert "pluggy==1.6.0 \\" in text and "pytest==9.1.1 \\" in text
    assert text.count("--hash=sha256:") == 6
    assert "--require-hashes -r requirements-dev.lock" in text
    assert "# lock-target: python=" in text and "platform=" in text
    assert warnings == []


def test_check_mode_reports_drift_and_writes_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(pin, "resolve", _fake_resolve)
    monkeypatch.setattr(pin, "pypi_digests", lambda name, version, timeout=30: ["c" * 64])
    req = tmp_path / "requirements-dev.txt"
    req.write_text("pytest>=8\n", encoding="utf-8")
    lock = tmp_path / "requirements-dev.lock"
    lock.write_text(
        "# stale\npytest==1.0.0 \\\n    --hash=sha256:" + "0" * 64 + "\n", encoding="utf-8"
    )
    assert pin.main([str(req), "--check"]) == 1
    assert "DRIFT" in capsys.readouterr().out
    assert lock.read_text(encoding="utf-8").startswith("# stale")
    assert pin.main([str(req)]) == 0
    assert "pytest==9.1.1" in lock.read_text(encoding="utf-8")
    assert pin.main([str(req), "--check"]) == 0
