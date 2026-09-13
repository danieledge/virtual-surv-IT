"""scripts/pin_release_tools.py - the human-run generator of config/release-tools.json
(2026-09-13 framework review, step 7.1), and the shape of the committed table itself."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import install_helper as ih  # noqa: E402
from scripts import pin_release_tools as pin  # noqa: E402


def _release(tag: str, names: list[str]) -> dict:
    return {
        "tag_name": tag,
        "assets": [
            {"name": n, "digest": "sha256:" + hashlib.sha256(n.encode()).hexdigest()} for n in names
        ]
        + [{"name": "no-digest.txt"}],
    }


def test_pin_entry_records_version_and_every_publisher_digest():
    spec = ih._RELEASE_TOOLS["shfmt"]
    names = [f"shfmt_v3.14.1_{p}_{a}" for p, a in (("linux", "amd64"), ("darwin", "arm64"))]
    row = pin.pin_entry(spec, _release("v3.14.1", names))
    assert row["version"] == "3.14.1" and row["tag"] == "v3.14.1"
    assert set(row["assets"]) == set(names), "an asset without a sha256 digest is not pinned"
    # The machines the installer expects that this release does not carry are named, not hidden.
    assert "shfmt_v3.14.1_windows_amd64.exe" in row["unpublished"]


def test_check_mode_reports_drift_without_writing(monkeypatch, tmp_path, capsys):
    table = {"tools": {n: {"version": "0.0.0"} for n in ih._RELEASE_TOOLS}}
    out = tmp_path / "release-tools.json"
    out.write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setattr(
        pin, "fetch_release", lambda repo, tag=None, timeout=30: _release("v9.9.9", [])
    )
    assert pin.main(["--check", "--out", str(out)]) == 1
    assert "drift:" in capsys.readouterr().out
    assert json.loads(out.read_text(encoding="utf-8")) == table, "--check must write nothing"


def test_write_mode_produces_the_table_the_installer_reads(monkeypatch, tmp_path):
    monkeypatch.setattr(
        pin, "fetch_release", lambda repo, tag=None, timeout=30: _release("v1.2.3", [])
    )
    out = tmp_path / "release-tools.json"
    assert pin.main(["--out", str(out)]) == 0
    table = json.loads(out.read_text(encoding="utf-8"))
    for name, spec in ih._RELEASE_TOOLS.items():
        assert ih.pinned_release(spec, table)[0] == "1.2.3", name


@pytest.mark.parametrize("tool", sorted(ih._RELEASE_TOOLS))
def test_the_committed_table_pins_every_tool_for_the_common_machines(tool):
    """The tracked config/release-tools.json is what a fresh install reads: every tool has a
    version, and an asset with a digest for Linux x86_64, macOS arm64 and Windows x86_64."""
    table = ih.load_release_pins()
    version, digests = ih.pinned_release(ih._RELEASE_TOOLS[tool], table)
    assert version, f"{tool} is not pinned in config/release-tools.json"
    for platform_name, machine in (("linux", "x86_64"), ("darwin", "arm64"), ("win32", "AMD64")):
        plat, arch = ih._release_platform_arch(platform_name, machine)
        asset = ih._RELEASE_TOOLS[tool].asset(plat, arch, version)
        if not asset:
            continue  # the project publishes nothing for this machine; the installer says so
        assert asset in digests, f"{tool} {version}: no pinned digest for {asset}"
        assert len(digests[asset]) == 64
