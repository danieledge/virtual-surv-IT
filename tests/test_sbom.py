"""scripts/sbom.py (2026-09-13 framework review, step 7.3): a CycloneDX SBOM from the vendor
manifest and the hash-pinned dev lock, no network, one component per vendored package."""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import sbom  # noqa: E402


def test_every_vendored_package_and_every_locked_pin_is_a_component(tmp_path):
    bom = sbom.build()
    assert bom["bomFormat"] == "CycloneDX" and bom["specVersion"] == "1.5"
    names = {c["name"].lower() for c in bom["components"]}
    manifest = (REPO / "vendor" / "MANIFEST.md").read_text(encoding="utf-8")
    for row in re.findall(r"^\| ([^|]+?) \| [^|]+? \| <", manifest, re.M):
        assert re.sub(r"\s*\(module `[^`]+`\)", "", row).strip().lower() in names, row
    lock = (REPO / "requirements-dev.lock").read_text(encoding="utf-8")
    for pin in re.findall(r"^([A-Za-z0-9_.\-]+)==", lock, re.M):
        assert pin.lower() in names, pin
    vendored = [c for c in bom["components"] if "vendored" in c["properties"][0]["value"]]
    assert all(c["licenses"][0]["license"]["id"] for c in vendored)
    locked = [c for c in bom["components"] if "developer tooling" in c["properties"][0]["value"]]
    assert all(c["hashes"] for c in locked), "every locked pin carries its sha256 set"
    assert sbom.main(["--out", str(tmp_path / "sbom.json")]) == 0
    assert (tmp_path / "sbom.json").stat().st_size > 1000
