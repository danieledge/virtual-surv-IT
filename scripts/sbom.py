#!/usr/bin/env python3
"""Emit a CycloneDX 1.5 SBOM for what this repository ships and develops with (step 7.3).

Two sources, no network: the vendored packages inventoried in `vendor/MANIFEST.md` (the
bytes that ship inside the plugin) and the hash-pinned `requirements-dev.lock` (the tooling a
developer or CI installs). Each component carries a PyPI purl, the version, the licence from
the manifest where known, and for the lock every sha256 as a hash entry.

    python scripts/sbom.py                 # writes sbom.json in the repo root
    python scripts/sbom.py --out dist/sbom.json

CI runs it on every push and uploads the file as a build artifact; a release attaches it.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import re
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_ROW = re.compile(r"^\| ([^|]+?) \| ([^|]+?) \| <([^>]+)> \| ([^|]+?) \|", re.M)
_LOCK_PIN = re.compile(r"^([A-Za-z0-9_.\-\[\]]+)==([^\s\\]+)", re.M)


def vendored_components() -> list[dict]:
    text = (REPO / "vendor" / "MANIFEST.md").read_text(encoding="utf-8")
    out = []
    for name, version, upstream, licence in _ROW.findall(text):
        module = re.sub(r"\s*\(module `[^`]+`\)", "", name).strip()
        out.append(
            {
                "type": "library",
                "name": module,
                "version": version.strip(),
                "purl": f"pkg:pypi/{module.lower()}@{version.strip()}",
                "licenses": [{"license": {"id": licence.strip()}}],
                "externalReferences": [{"type": "vcs", "url": upstream.strip()}],
                "properties": [
                    {"name": "virt-surv-it:scope", "value": "vendored, ships in the plugin"}
                ],
            }
        )
    return out


def locked_components(lock: Path) -> list[dict]:
    text = lock.read_text(encoding="utf-8")
    out = []
    for block in re.split(r"\n(?=[A-Za-z0-9])", text):
        m = _LOCK_PIN.match(block)
        if not m:
            continue
        name, version = m.group(1).split("[", 1)[0], m.group(2)
        hashes = re.findall(r"--hash=sha256:([0-9a-f]{64})", block)
        out.append(
            {
                "type": "library",
                "name": name,
                "version": version,
                "purl": f"pkg:pypi/{name.lower()}@{version}",
                "hashes": [{"alg": "SHA-256", "content": h} for h in hashes],
                "properties": [
                    {"name": "virt-surv-it:scope", "value": f"developer tooling, {lock.name}"}
                ],
            }
        )
    return out


def build(lock: Path = REPO / "requirements-dev.lock") -> dict:
    plugin = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{uuid.uuid4()}",
        "version": 1,
        "metadata": {
            "timestamp": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat(),
            "component": {
                "type": "application",
                "name": plugin.get("name", "compliance-surveillance-team"),
                "version": plugin.get("version", ""),
                "licenses": [{"license": {"id": plugin.get("license", "AGPL-3.0-only")}}],
            },
            "tools": [{"name": "scripts/sbom.py", "version": plugin.get("version", "")}],
        },
        "components": vendored_components() + (locked_components(lock) if lock.is_file() else []),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO / "sbom.json")
    args = parser.parse_args(argv)
    bom = build()
    args.out.write_text(json.dumps(bom, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out} ({len(bom['components'])} components)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
